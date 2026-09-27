"""C.4 functional and migration gates, using disposable SQLite/PostgreSQL only."""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from .test_fase5a3b_sinais_vitais_rbac_tenant import (
    BACKEND, _auth_headers, _create_ilpi_user, _create_platform_user,
    _create_residente, _database_url, _detail_code, _grant_permissions,
    _new_id, _new_institution, _reset_postgres, _with_client,
    main, m,
)

REV_010 = "010_f5a3a2_grau_dependencia"
REV_011 = "011_f5a4a_intercorrencias_rbac"
KEYS = {f"intercorrencias:{action}" for action in ("ler", "criar", "atualizar")}
BASE = "/api/intercorrencias/"


def _migrate(ref, command="upgrade", target="head", success=True):
    url = _database_url(ref)
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    env.pop("APP_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"database_url={url}", command, target],
        cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert (result.returncode == 0) == success, result.stdout + result.stderr


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("C4_TEST_POSTGRES_URL") else []))
def c4_db(request, tmp_path):
    if request.param == "sqlite":
        ref = tmp_path / "c4-intercorrencias.db"
    else:
        ref = os.environ["C4_TEST_POSTGRES_URL"]
        url = make_url(ref)
        assert url.host in {"127.0.0.1", "localhost"}
        assert url.port == 55484 and url.database == "facilpi_c4_test"
        asyncio.run(_reset_postgres(ref))
    _migrate(ref)
    return ref


async def _setup(db, permissions=None, nome="Autor C4"):
    ilpi = _new_institution("ILPI C4")
    user = await _create_ilpi_user(db, ilpi, permissions=KEYS if permissions is None else permissions, nome=nome)
    resident = await _create_residente(db, ilpi.id)
    await db.commit()
    return ilpi, user, resident, _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)


async def _create(client, resident, headers, **fields):
    response = await client.post(BASE, headers=headers, json={
        "residente_id": resident.id, "tipo": "queda", "gravidade": "leve", **fields,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _operations(row_id, resident_id):
    return (
        ("GET", BASE, None),
        ("GET", BASE + row_id, None),
        ("POST", BASE, {"residente_id": resident_id, "tipo": "queda", "gravidade": "leve"}),
        ("PATCH", BASE + row_id, {"providencia": "Observacao registrada"}),
        ("POST", BASE + row_id + "/encerrar", {"desfecho": "Registro concluido"}),
    )


@pytest.mark.parametrize("mode", ["anonymous", "no_permission", "platform", "platform_hostile_grants", "password_change"])
def test_auth_rbac_platform(c4_db, mode):
    async def scenario(client, db):
        ilpi, user, resident, headers = await _setup(db, permissions=set())
        if mode == "anonymous":
            headers = {}
        elif mode.startswith("platform"):
            user = await _create_platform_user(db)
            if mode == "platform_hostile_grants":
                profile = (await db.execute(select(m.Perfil).where(m.Perfil.chave == "platform_superuser"))).scalar_one()
                await _grant_permissions(db, profile.id, KEYS)
            await db.commit()
            headers = _auth_headers(user, scope="global")
        elif mode == "password_change":
            user.exige_troca_senha = True
            await db.commit()
        for method, path, payload in _operations(_new_id(), resident.id):
            response = await client.request(method, path, headers=headers, json=payload)
            assert response.status_code in ({401, 403} if mode == "anonymous" else {403})
            if mode in {"no_permission", "platform", "platform_hostile_grants"}:
                assert _detail_code(response) == "PERMISSION_DENIED"
    asyncio.run(_with_client(c4_db, scenario))


@pytest.mark.parametrize("permission,allowed", [("ler", {0, 1}), ("criar", {2}), ("atualizar", {3, 4})])
def test_permissions_are_separate(c4_db, permission, allowed):
    async def scenario(client, db):
        ilpi, _, resident, admin_headers = await _setup(db)
        row = await _create(client, resident, admin_headers)
        user = await _create_ilpi_user(db, ilpi, permissions={f"intercorrencias:{permission}"}, profile_key=f"c4_{permission}")
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        for index, (method, path, payload) in enumerate(_operations(row["id"], resident.id)):
            response = await client.request(method, path, headers=headers, json=payload)
            assert response.status_code == ((201 if index == 2 else 200) if index in allowed else 403), response.text
    asyncio.run(_with_client(c4_db, scenario))


def test_tenant_parent_and_cross_tenant_404(c4_db):
    async def scenario(client, db):
        ilpi, user, resident, headers = await _setup(db)
        other_ilpi, _, other_resident, other_headers = await _setup(db, nome="Outro autor")
        row = await _create(client, resident, headers)
        other_row = await _create(client, other_resident, other_headers)
        response = await client.get(BASE, headers=headers, params={"ilpi_id": other_ilpi.id, "instituicao_id": other_ilpi.id})
        assert [r["id"] for r in response.json()] == [row["id"]]
        filtered = await client.get(BASE, headers=headers, params={"residente_id": resident.id})
        assert [r["id"] for r in filtered.json()] == [row["id"]]
        for parent in (other_resident.id, _new_id()):
            response = await client.post(BASE, headers=headers, json={"residente_id": parent, "tipo": "queda", "gravidade": "leve"})
            assert response.status_code == 404
            response = await client.get(BASE, headers=headers, params={"residente_id": parent})
            assert response.status_code == 404
        for target in (other_row["id"], _new_id()):
            for method, path, payload in _operations(target, resident.id):
                if path == BASE:
                    continue
                response = await client.request(method, path, headers=headers, json=payload)
                assert response.status_code == 404
                assert _detail_code(response) == "RESOURCE_NOT_FOUND"
        stored = (await db.execute(select(m.Intercorrencia).where(m.Intercorrencia.id == other_row["id"]))).scalar_one()
        assert stored.situacao == "aberta" and stored.ilpi_id == other_ilpi.id
        assert (await client.delete(BASE + row["id"], headers=headers)).status_code == 405
        assert (await client.delete(BASE + other_row["id"], headers=headers)).status_code == 405
    asyncio.run(_with_client(c4_db, scenario))


@pytest.mark.parametrize("gravidade", ["leve", "moderada", "grave"])
def test_create_read_sbar_and_severity(c4_db, gravidade):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        fields = {key: f"Texto {key}" for key in ("sbar_situacao", "sbar_contexto", "sbar_avaliacao", "sbar_recomendacao", "providencia")}
        row = await _create(client, resident, headers, gravidade=gravidade, **fields)
        assert row["situacao"] == "aberta" and row["gravidade"] == gravidade
        assert row["desfecho"] is None and row["data"]
        assert all(row[key] == value for key, value in fields.items())
        result = await client.get(BASE + row["id"], headers=headers)
        assert result.status_code == 200 and result.json() == row
    asyncio.run(_with_client(c4_db, scenario))


@pytest.mark.parametrize("fields", [
    {"gravidade": "critica"}, {"gravidade": None}, {"gravidade": "Leve"},
    {"situacao": "encerrada"}, {"situacao": "Aberta"}, {"situacao": None},
    {"tipo": " "}, {"tipo": "x" * 101}, {"desfecho": "Nao encerrar na criacao"},
])
def test_invalid_creation(c4_db, fields):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        response = await client.post(BASE, headers=headers, json={"residente_id": resident.id, "tipo": "queda", "gravidade": "leve", **fields})
        assert response.status_code == 422
        assert (await db.execute(select(func.count()).select_from(m.Intercorrencia))).scalar_one() == 0
        assert (await db.execute(select(func.count()).select_from(m.Auditoria).where(m.Auditoria.entidade == "intercorrencias"))).scalar_one() == 0
    asyncio.run(_with_client(c4_db, scenario))


def test_hostile_payload_authorship_correction_close_audit(c4_db):
    async def scenario(client, db):
        ilpi, creator, resident, headers = await _setup(db)
        employee = (await db.execute(select(m.Funcionario).where(m.Funcionario.usuario_id == creator.id))).scalar_one()
        employee.nome = "Nome profissional autenticado"
        await db.commit()
        hostile = {key: _new_id() for key in ("ilpi_id", "instituicao_id", "profissional", "usuario_id", "autor", "executor", "responsavel", "id", "autor_id")}
        hostile["data"] = "1900-01-01T00:00:00Z"
        row = await _create(client, resident, headers, **hostile)
        assert row["responsavel"] == employee.nome
        assert row["id"] != hostile["id"] and row["data"][:4] != "1900"
        editor = await _create_ilpi_user(db, ilpi, permissions=KEYS, profile_key="c4_editor", nome="Editor")
        await db.commit()
        editor_headers = _auth_headers(editor, scope="ilpi", ilpi_id=ilpi.id)
        correction = await client.patch(BASE + row["id"], headers=editor_headers, json={"tipo": " queda corrigida ", "gravidade": "moderada", "providencia": "Observacao", **hostile})
        assert correction.status_code == 200, correction.text
        assert correction.json()["responsavel"] == employee.nome
        assert correction.json()["tipo"] == "queda corrigida"
        assert correction.json()["data"] == row["data"]
        closed = await client.post(BASE + row["id"] + "/encerrar", headers=editor_headers, json={"desfecho": " Registro concluido ", "tipo": "nao sobrescrever", **hostile})
        assert closed.status_code == 200, closed.text
        assert closed.json()["situacao"] == "encerrada"
        assert closed.json()["desfecho"] == "Registro concluido"
        assert closed.json()["responsavel"] == employee.nome
        assert closed.json()["tipo"] == "queda corrigida"
        audit = (await db.execute(select(m.Auditoria).where(m.Auditoria.registro_id == row["id"]))).scalars().all()
        by_action = {item.acao: item for item in audit}
        assert set(by_action) == {"intercorrencias.criar", "intercorrencias.corrigir", "intercorrencias.encerrar"}
        for item in audit:
            assert item.ilpi_id == ilpi.id and item.entidade == "intercorrencias"
            assert item.created_at is not None
            assert item.usuario_id == (creator.id if item.acao.endswith("criar") else editor.id)
        before = json.loads(by_action["intercorrencias.corrigir"].valores_anteriores)
        after = json.loads(by_action["intercorrencias.corrigir"].valores_posteriores)
        assert before["tipo"] == "queda" and after["tipo"] == "queda corrigida"
        assert json.loads(by_action["intercorrencias.encerrar"].valores_anteriores)["situacao"] == "aberta"
        stored = (await db.execute(select(m.Intercorrencia).where(m.Intercorrencia.id == row["id"]))).scalar_one()
        assert stored.ilpi_id == ilpi.id and stored.residente_id == resident.id
    asyncio.run(_with_client(c4_db, scenario))


def test_professional_fallback(c4_db):
    async def scenario(client, db):
        _, user, resident, headers = await _setup(db)
        employee = (await db.execute(select(m.Funcionario).where(m.Funcionario.usuario_id == user.id))).scalar_one()
        employee.nome = ""
        await db.commit()
        row = await _create(client, resident, headers, responsavel="Falso")
        assert row["responsavel"] == user.nome
    asyncio.run(_with_client(c4_db, scenario))


@pytest.mark.parametrize("fields", [
    {"residente_id": "replace"}, {"residente_id": None}, {"situacao": "encerrada"},
    {"situacao": "aberta"}, {"desfecho": "Bypass"}, {"tipo": None},
    {"tipo": " "}, {"gravidade": None}, {"gravidade": "critica"}, {},
])
def test_controlled_correction(c4_db, fields):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        row = await _create(client, resident, headers)
        response = await client.patch(BASE + row["id"], headers=headers, json=fields)
        assert response.status_code == 422
        current = await client.get(BASE + row["id"], headers=headers)
        assert current.json() == row
    asyncio.run(_with_client(c4_db, scenario))


@pytest.mark.parametrize("payload", [{}, {"desfecho": None}, {"desfecho": ""}, {"desfecho": " \n\t"}])
def test_close_requires_outcome(c4_db, payload):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        row = await _create(client, resident, headers)
        response = await client.post(BASE + row["id"] + "/encerrar", headers=headers, json=payload)
        assert response.status_code == 422
        assert (await client.get(BASE + row["id"], headers=headers)).json() == row
    asyncio.run(_with_client(c4_db, scenario))


def test_closed_record_immutable_no_delete_or_side_effects(c4_db):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        tables = (m.GrauDependencia, m.PlanoCuidados, m.Tarefa, m.Avaliacao, m.SinalVital, m.Medicamento, m.Prescricao, m.QuartoLeito, m.Alerta)
        async def counts():
            return [(await db.execute(select(func.count()).select_from(table))).scalar_one() for table in tables]
        before = await counts()
        row = await _create(client, resident, headers)
        response = await client.post(BASE + row["id"] + "/encerrar", headers=headers, json={"desfecho": "Concluido"})
        assert response.status_code == 200
        closed = response.json()
        for method, path, payload in (
            ("PATCH", BASE + row["id"], {"providencia": "Silenciosa"}),
            ("POST", BASE + row["id"] + "/encerrar", {"desfecho": "Sobrescrever"}),
        ):
            assert (await client.request(method, path, headers=headers, json=payload)).status_code == 409
        assert (await client.delete(BASE + row["id"], headers=headers)).status_code == 405
        assert (await client.put(BASE + row["id"], headers=headers, json={"tipo": "Sobrescrever"})).status_code == 405
        assert (await client.get(BASE + row["id"], headers=headers)).json() == closed
        assert await counts() == before
        assert (await db.execute(select(func.count()).select_from(m.Auditoria).where(m.Auditoria.registro_id == row["id"]))).scalar_one() == 2
    asyncio.run(_with_client(c4_db, scenario))


@pytest.mark.parametrize("competitor", ["correction", "close"])
def test_stale_correction_cannot_overwrite(c4_db, monkeypatch, competitor):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        row = await _create(client, resident, headers)
        original = main.get_intercorrencia
        intercepted = False
        async def read_then_compete(*args, **kwargs):
            nonlocal intercepted
            obj = await original(*args, **kwargs)
            if not intercepted:
                intercepted = True
                if competitor == "close":
                    response = await client.post(BASE + row["id"] + "/encerrar", headers=headers, json={"desfecho": "Concluido"})
                else:
                    response = await client.patch(BASE + row["id"], headers=headers, json={"tipo": "Correcao concorrente"})
                assert response.status_code == 200, response.text
            return obj
        monkeypatch.setattr(main, "get_intercorrencia", read_then_compete)
        response = await client.patch(BASE + row["id"], headers=headers, json={"tipo": "Correcao obsoleta"})
        assert response.status_code == 409, response.text
        current = (await client.get(BASE + row["id"], headers=headers)).json()
        assert current["tipo"] != "Correcao obsoleta"
        assert current["situacao"] == ("encerrada" if competitor == "close" else "aberta")
        assert (await db.execute(select(func.count()).select_from(m.Auditoria).where(m.Auditoria.registro_id == row["id"]))).scalar_one() == 2
    asyncio.run(_with_client(c4_db, scenario))


@pytest.mark.parametrize("operation", ["create", "correct", "close"])
def test_audit_failure_rolls_back(c4_db, monkeypatch, operation):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        row = await _create(client, resident, headers)
        def fail_audit(*args, **kwargs):
            raise RuntimeError("audit failure fixture")
        monkeypatch.setattr(main, "add_audit", fail_audit)
        with pytest.raises(RuntimeError, match="audit failure fixture"):
            if operation == "create":
                await _create(client, resident, headers)
            elif operation == "correct":
                await client.patch(BASE + row["id"], headers=headers, json={"tipo": "Nao persistir"})
            else:
                await client.post(BASE + row["id"] + "/encerrar", headers=headers, json={"desfecho": "Nao persistir"})
        assert (await client.get(BASE + row["id"], headers=headers)).json() == row
        assert (await db.execute(select(func.count()).select_from(m.Intercorrencia))).scalar_one() == 1
    asyncio.run(_with_client(c4_db, scenario))


def test_migration_baselines_clones_downgrade_idempotence(c4_db):
    _migrate(c4_db, "downgrade", REV_010)
    async def baseline(client, db):
        assert (await db.execute(select(func.count()).select_from(m.Permissao))).scalar_one() == 56
        ilpi = _new_institution()
        await _create_ilpi_user(db, ilpi, permissions=set(), profile_key="ilpi_admin")
        await db.execute(text(
            "INSERT INTO perfil_permissoes (perfil_id, permissao_id) "
            "SELECT clone.id, pp.permissao_id FROM perfis clone CROSS JOIN perfil_permissoes pp "
            "JOIN perfis template ON template.id = pp.perfil_id "
            "WHERE clone.chave = 'ilpi_admin' AND clone.ilpi_id IS NOT NULL "
            "AND template.chave = 'ilpi_admin' AND template.ilpi_id IS NULL"
        ))
        await db.commit()
    asyncio.run(_with_client(c4_db, baseline))
    _migrate(c4_db, target=REV_011)
    _migrate(c4_db, target=REV_011)
    async def check(client, db):
        assert (await db.execute(select(func.count()).select_from(m.Permissao))).scalar_one() == 59
        assert (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == REV_011
        profiles = (await db.execute(select(m.Perfil))).scalars().all()
        for profile in profiles:
            keys = set((await db.execute(select(m.Permissao.chave).join(m.PerfilPermissao).where(m.PerfilPermissao.perfil_id == profile.id))).scalars())
            if profile.chave == "ilpi_admin":
                assert len(keys) == 55 and KEYS <= keys
            elif profile.chave == "platform_superuser":
                assert len(keys) == 15 and not KEYS & keys
    asyncio.run(_with_client(c4_db, check))
    _migrate(c4_db, "downgrade", REV_010)
    async def restored(client, db):
        assert (await db.execute(select(func.count()).select_from(m.Permissao))).scalar_one() == 56
        for profile in (await db.execute(select(m.Perfil).where(m.Perfil.chave == "ilpi_admin"))).scalars():
            assert (await db.execute(select(func.count()).select_from(m.PerfilPermissao).where(m.PerfilPermissao.perfil_id == profile.id))).scalar_one() == 52
    asyncio.run(_with_client(c4_db, restored))


def test_migration_refuses_external_grant_downgrade(c4_db):
    # Roda a partir de 011, nao de head: o alvo aqui e a guarda da propria 011.
    # Partindo de head, a recusa acontece no meio de uma cadeia de downgrades, e o
    # estado resultante depende do backend: PostgreSQL envolve a cadeia inteira em
    # uma transacao e reverte tudo, SQLite comita cada passo. Isolar a transicao
    # 011->010 mantem o invariante e o torna deterministico nos dois bancos, alem de
    # nao depender de qual venha a ser o head futuro.
    _migrate(c4_db, "downgrade", REV_011)
    async def scenario(client, db):
        await _setup(db)
    asyncio.run(_with_client(c4_db, scenario))
    _migrate(c4_db, "downgrade", REV_010, success=False)
    async def intact(client, db):
        assert (await db.execute(select(func.count()).select_from(m.Permissao))).scalar_one() == 59
        assert (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == REV_011
    asyncio.run(_with_client(c4_db, intact))


# ---- Leitura de registro legado: gravidade NULL ----
# `intercorrencias.gravidade` nasceu nullable na 001 e nenhuma migration a
# tornou NOT NULL nem fez backfill; antes da C.4 a entrada aceitava gravidade
# ausente ou texto livre. A insercao e direta no banco descartavel porque a API
# atual recusa esses valores. A leitura devolve o que esta gravado, sem inferir.

async def _insert_legacy(db, ilpi, resident, gravidade):
    row = m.Intercorrencia(
        residente_id=resident.id, ilpi_id=ilpi.id, tipo="queda legada",
        gravidade=gravidade, situacao="aberta",
        ocorrido_em=datetime.now(timezone.utc) - timedelta(days=30),
    )
    db.add(row)
    await db.commit()
    return row.id


def test_legacy_severity_does_not_break_reads(c4_db):
    async def scenario(client, db):
        ilpi, _, resident, headers = await _setup(db)
        current = await _create(client, resident, headers)
        null_id = await _insert_legacy(db, ilpi, resident, None)
        free_text_id = await _insert_legacy(db, ilpi, resident, "Alta")
        listed = await client.get(BASE, headers=headers)
        assert listed.status_code == 200, listed.text
        by_id = {row["id"]: row for row in listed.json()}
        assert set(by_id) == {current["id"], null_id, free_text_id}
        assert by_id[null_id]["gravidade"] is None
        assert by_id[free_text_id]["gravidade"] == "Alta"
        assert by_id[current["id"]]["gravidade"] == "leve"
        filtered = await client.get(BASE, headers=headers, params={"residente_id": resident.id})
        assert filtered.status_code == 200, filtered.text
        assert {row["id"] for row in filtered.json()} == set(by_id)
        for row_id in (null_id, free_text_id):
            single = await client.get(BASE + row_id, headers=headers)
            assert single.status_code == 200, single.text
            assert single.json() == by_id[row_id]
        stored = (await db.execute(select(m.Intercorrencia.gravidade).where(m.Intercorrencia.id == null_id))).scalar_one()
        assert stored is None
    asyncio.run(_with_client(c4_db, scenario))


def test_legacy_null_severity_correction_and_close_respond(c4_db):
    # Encerrar pelo Meu Plantao comitava e so depois a resposta quebrava em 500:
    # o registro fechava e a tela mostrava erro.
    async def scenario(client, db):
        ilpi, _, resident, headers = await _setup(db)
        legacy_id = await _insert_legacy(db, ilpi, resident, None)
        corrected = await client.patch(BASE + legacy_id, headers=headers, json={"providencia": "Observacao"})
        assert corrected.status_code == 200, corrected.text
        assert corrected.json()["gravidade"] is None and corrected.json()["providencia"] == "Observacao"
        closed = await client.post(BASE + legacy_id + "/encerrar", headers=headers, json={"desfecho": "Registro concluido"})
        assert closed.status_code == 200, closed.text
        assert closed.json()["situacao"] == "encerrada" and closed.json()["gravidade"] is None
        stored = (await db.execute(select(m.Intercorrencia).where(m.Intercorrencia.id == legacy_id))).scalar_one()
        await db.refresh(stored)
        assert stored.gravidade is None and stored.situacao == "encerrada"
    asyncio.run(_with_client(c4_db, scenario))


def test_input_still_requires_severity(c4_db):
    # A leitura tolerante nao abre a entrada: gravidade segue obrigatoria na
    # criacao e nao pode ser apagada na correcao, nem de registro legado.
    async def scenario(client, db):
        ilpi, _, resident, headers = await _setup(db)
        missing = await client.post(BASE, headers=headers, json={"residente_id": resident.id, "tipo": "queda"})
        assert missing.status_code == 422
        assert (await db.execute(select(func.count()).select_from(m.Intercorrencia))).scalar_one() == 0
        legacy_id = await _insert_legacy(db, ilpi, resident, None)
        for fields in ({"gravidade": None}, {"gravidade": "Alta"}):
            response = await client.patch(BASE + legacy_id, headers=headers, json=fields)
            assert response.status_code == 422
        assert (await client.get(BASE + legacy_id, headers=headers)).json()["gravidade"] is None
    asyncio.run(_with_client(c4_db, scenario))


# ---- #110: situacao e tipo legados na leitura ----
# Antes da C.4 a entrada aceitava situacao "Aberta"/NULL (default "Aberta") e
# tipo vazio. A leitura devolve o gravado; as regras operacionais continuam
# considerando so `aberta`/`encerrada`. Linhas inseridas direto no banco
# descartavel, porque a API atual recusa esses valores.

RESPONSE_KEYS = {
    "residente_id", "tipo", "gravidade", "situacao", "sbar_situacao", "sbar_contexto",
    "sbar_avaliacao", "sbar_recomendacao", "providencia", "desfecho", "ocorrido_em",
    "id", "responsavel", "data",
}
LEGACY_SITUACOES = ["Aberta", None, "Encerrada"]
LEGACY_TIPOS = ["", "   "]


async def _insert_raw(db, ilpi, resident, *, tipo="queda legada", situacao="aberta", gravidade="grave"):
    row = m.Intercorrencia(
        residente_id=resident.id, ilpi_id=ilpi.id, tipo=tipo, gravidade=gravidade, situacao=situacao,
        ocorrido_em=datetime.now(timezone.utc) - timedelta(days=30),
    )
    db.add(row)
    await db.commit()
    if situacao is None:
        # O ORM aplica o default do modelo a None explicito; NULL real so por UPDATE.
        await db.execute(
            m.Intercorrencia.__table__.update().where(m.Intercorrencia.id == row.id).values(situacao=None)
        )
        await db.commit()
    stored = (await db.execute(select(m.Intercorrencia.situacao).where(m.Intercorrencia.id == row.id))).scalar_one()
    assert stored == situacao
    return row.id


async def _audits_for(db, row_id):
    return (await db.execute(
        select(func.count()).select_from(m.Auditoria).where(m.Auditoria.registro_id == row_id)
    )).scalar_one()


async def _assert_reads_as_stored(client, headers, resident, row_id, current_id, **stored):
    listed = await client.get(BASE, headers=headers)
    assert listed.status_code == 200, listed.text
    by_id = {row["id"]: row for row in listed.json()}
    assert set(by_id) == {current_id, row_id}
    filtered = await client.get(BASE, headers=headers, params={"residente_id": resident.id})
    assert filtered.status_code == 200, filtered.text
    assert {row["id"] for row in filtered.json()} == set(by_id)
    single = await client.get(BASE + row_id, headers=headers)
    assert single.status_code == 200, single.text
    assert single.json() == by_id[row_id]
    for key, value in stored.items():
        assert by_id[row_id][key] == value, key


@pytest.mark.parametrize("situacao", LEGACY_SITUACOES)
def test_legacy_situacao_reads_as_stored_and_stays_locked(c4_db, situacao):
    async def scenario(client, db):
        ilpi, _, resident, headers = await _setup(db)
        current = await _create(client, resident, headers)
        legacy_id = await _insert_raw(db, ilpi, resident, situacao=situacao)
        await _assert_reads_as_stored(client, headers, resident, legacy_id, current["id"], situacao=situacao)
        # A regra operacional nao muda: fora de `aberta`, correcao e encerramento seguem 409.
        for response in (
            await client.patch(BASE + legacy_id, headers=headers, json={"providencia": "Observacao"}),
            await client.post(BASE + legacy_id + "/encerrar", headers=headers, json={"desfecho": "Concluido"}),
        ):
            assert response.status_code == 409, response.text
            assert _detail_code(response) == "INTERCORRENCIA_NAO_ABERTA"
        stored = (await db.execute(
            select(m.Intercorrencia.situacao, m.Intercorrencia.providencia, m.Intercorrencia.desfecho)
            .where(m.Intercorrencia.id == legacy_id)
        )).one()
        assert tuple(stored) == (situacao, None, None)
        assert await _audits_for(db, legacy_id) == 0
    asyncio.run(_with_client(c4_db, scenario))


@pytest.mark.parametrize("tipo", LEGACY_TIPOS)
def test_legacy_blank_tipo_reads_corrects_and_closes(c4_db, tipo):
    # Antes: PATCH e /encerrar comitavam, auditavam e so depois respondiam 500.
    async def scenario(client, db):
        ilpi, _, resident, headers = await _setup(db)
        current = await _create(client, resident, headers)
        legacy_id = await _insert_raw(db, ilpi, resident, tipo=tipo)
        await _assert_reads_as_stored(client, headers, resident, legacy_id, current["id"], tipo=tipo)
        corrected = await client.patch(BASE + legacy_id, headers=headers, json={"providencia": "Observacao"})
        assert corrected.status_code == 200, corrected.text
        assert corrected.json()["tipo"] == tipo and corrected.json()["providencia"] == "Observacao"
        closed = await client.post(BASE + legacy_id + "/encerrar", headers=headers, json={"desfecho": "Concluido"})
        assert closed.status_code == 200, closed.text
        assert closed.json()["situacao"] == "encerrada" and closed.json()["tipo"] == tipo
        stored = (await db.execute(select(m.Intercorrencia.tipo).where(m.Intercorrencia.id == legacy_id))).scalar_one()
        assert stored == tipo
    asyncio.run(_with_client(c4_db, scenario))


def test_projections_ignore_out_of_contract_situacao(c4_db):
    async def scenario(client, db):
        ilpi, user, resident, headers = await _setup(db)
        profile_id = (await db.execute(
            select(m.UsuarioIlpiPerfil.perfil_id).where(m.UsuarioIlpiPerfil.usuario_id == user.id)
        )).scalar_one()
        await _grant_permissions(db, profile_id, {"plantao:ler", "alertas:ler"})
        await db.commit()
        valid = await _create(client, resident, headers, gravidade="grave")
        legacy_ids = {
            await _insert_raw(db, ilpi, resident, situacao=situacao) for situacao in LEGACY_SITUACOES
        }

        plantao = await client.get("/api/plantao/", headers=headers)
        assert plantao.status_code == 200, plantao.text
        ids = {item["registro_id"] for item in plantao.json() if item["origem"] == "intercorrencia"}
        assert ids == {valid["id"]}

        resumo = await client.get("/api/dashboard/resumo", headers=headers)
        assert resumo.status_code == 200, resumo.text
        assert resumo.json()["intercorrencias_abertas"] == 1

        alertas = await client.get("/api/central-alertas/", headers=headers)
        assert alertas.status_code == 200, alertas.text
        texto = alertas.text
        assert valid["id"] in texto
        assert not any(legacy_id in texto for legacy_id in legacy_ids)
    asyncio.run(_with_client(c4_db, scenario))


def test_input_contract_unchanged_by_tolerant_read(c4_db):
    async def scenario(client, db):
        ilpi, _, resident, headers = await _setup(db)
        base = {"residente_id": resident.id, "tipo": "queda", "gravidade": "leve"}
        for payload in (
            {**base, "situacao": "Aberta"},
            {**base, "situacao": None},
            {**base, "tipo": " "},
            {"residente_id": resident.id, "tipo": "queda"},
        ):
            response = await client.post(BASE, headers=headers, json=payload)
            assert response.status_code == 422, (payload, response.text)
        assert (await db.execute(select(func.count()).select_from(m.Intercorrencia))).scalar_one() == 0
        current = await _create(client, resident, headers)
        for fields in ({"situacao": "encerrada"}, {"tipo": " "}):
            response = await client.patch(BASE + current["id"], headers=headers, json=fields)
            assert response.status_code == 422, (fields, response.text)
    asyncio.run(_with_client(c4_db, scenario))


def test_valid_record_response_shape_unchanged(c4_db):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        created = await _create(client, resident, headers, tipo="  queda  ")
        assert set(created) == RESPONSE_KEYS
        # A entrada continua normalizando `tipo`; a leitura so devolve o gravado.
        assert (created["tipo"], created["gravidade"], created["situacao"]) == ("queda", "leve", "aberta")
        single = await client.get(BASE + created["id"], headers=headers)
        assert single.status_code == 200 and single.json() == created
    asyncio.run(_with_client(c4_db, scenario))

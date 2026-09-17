"""B1: hora real da intercorrencia (ocorrido_em) e emenda S.1 do cuidador.

Somente bancos descartaveis: SQLite em tmp_path e PostgreSQL 55484/facilpi_c4_test,
reaproveitando a fixture c4_db. storage/app.db nunca e alvo.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect as sa_inspect, select, text

from .test_fase5a4a_intercorrencias_rbac_tenant import (  # noqa: F401
    BASE, KEYS, _create, _migrate, _setup, c4_db,
)
from .test_fase5a3b_sinais_vitais_rbac_tenant import (
    BACKEND, _auth_headers, _create_ilpi_user, _detail_code, _new_id, _with_client, m,
)

REV_018 = "018_a3_documentos_arquivo"


def _head_da_cadeia():
    """Ponta atual da cadeia Alembic, lida dos proprios scripts.

    A fixture `c4_db` sobe ate `head`, que avanca a cada migration nova. Fixar o
    valor esperado em uma revisao literal fazia este teste quebrar em toda
    migration seguinte — foi o que a 020 expos, sem que nada da 019 tivesse
    mudado. A afirmacao permanece a mesma: reaplicar `upgrade head` sobre head
    deixa o banco no head real, sem mover nem corromper a linha de versao.

    `script_location` e resolvido em absoluto para nao depender do cwd do pytest.
    """
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


# Capacidade do cuidador decidida pela Control Tower: le e cria, nao atualiza.
CUIDADOR_KEYS = {"intercorrencias:ler", "intercorrencias:criar"}


def _iso(momento):
    return momento.isoformat()


def _aware(valor):
    """Le o datetime da resposta/ORM sempre com fuso: SQLite devolve naive."""
    if isinstance(valor, str):
        valor = datetime.fromisoformat(valor)
    return valor.replace(tzinfo=timezone.utc) if valor.tzinfo is None else valor


# ---------------------------------------------------------------- criacao ----

def test_ocorrido_em_omitido_assume_agora(c4_db):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        antes = datetime.now(timezone.utc)
        row = await _create(client, resident, headers)
        depois = datetime.now(timezone.utc)

        assert row["ocorrido_em"] is not None
        assert antes - timedelta(seconds=5) <= _aware(row["ocorrido_em"]) <= depois + timedelta(seconds=5)
        obj = (await db.execute(select(m.Intercorrencia))).scalar_one()
        assert obj.ocorrido_em is not None
    asyncio.run(_with_client(c4_db, scenario))


def test_ocorrido_em_retroativo_e_aceito_e_separado_do_registro(c4_db):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        madrugada = datetime.now(timezone.utc) - timedelta(hours=6)
        row = await _create(client, resident, headers, ocorrido_em=_iso(madrugada))

        assert abs((_aware(row["ocorrido_em"]) - madrugada).total_seconds()) < 1
        # data e o timestamp tecnico: fica no presente, nao na madrugada.
        registrado = _aware(row["data"])
        assert registrado - madrugada > timedelta(hours=5)
    asyncio.run(_with_client(c4_db, scenario))


def test_ocorrido_em_normalizado_para_utc(c4_db):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        brasilia = timezone(timedelta(hours=-3))
        momento = (datetime.now(timezone.utc) - timedelta(hours=2)).astimezone(brasilia)
        row = await _create(client, resident, headers, ocorrido_em=_iso(momento))
        assert abs((_aware(row["ocorrido_em"]) - momento).total_seconds()) < 1
    asyncio.run(_with_client(c4_db, scenario))


def test_ocorrido_em_naive_recusado(c4_db):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        sem_fuso = datetime.now().replace(microsecond=0).isoformat()
        response = await client.post(BASE, headers=headers, json={
            "residente_id": resident.id, "tipo": "queda", "gravidade": "leve", "ocorrido_em": sem_fuso,
        })
        assert response.status_code == 422, response.text
        assert (await db.execute(select(func.count()).select_from(m.Intercorrencia))).scalar_one() == 0
    asyncio.run(_with_client(c4_db, scenario))


def test_ocorrido_em_futuro_recusado(c4_db):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        futuro = datetime.now(timezone.utc) + timedelta(hours=1)
        response = await client.post(BASE, headers=headers, json={
            "residente_id": resident.id, "tipo": "queda", "gravidade": "leve", "ocorrido_em": _iso(futuro),
        })
        assert response.status_code == 422, response.text
        assert (await db.execute(select(func.count()).select_from(m.Intercorrencia))).scalar_one() == 0
    asyncio.run(_with_client(c4_db, scenario))


def test_patch_recusa_corrigir_ocorrido_em(c4_db):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        row = await _create(client, resident, headers)
        original = row["ocorrido_em"]
        response = await client.patch(BASE + row["id"], headers=headers, json={
            "ocorrido_em": _iso(datetime.now(timezone.utc) - timedelta(days=1)),
        })
        assert response.status_code == 422, response.text
        # Recusa explicita, nao no-op silencioso: o valor continua o mesmo.
        assert (await client.get(BASE + row["id"], headers=headers)).json()["ocorrido_em"] == original
    asyncio.run(_with_client(c4_db, scenario))


# --------------------------------------------------------------- ordenacao ----

def test_listagem_ordena_por_ocorrido_em_e_nao_por_criacao(c4_db):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        agora = datetime.now(timezone.utc)
        # Ordem de CRIACAO: antiga, recente, intermediaria.
        for rotulo, atraso in (("antiga", 9), ("recente", 1), ("intermediaria", 5)):
            await _create(client, resident, headers, tipo=rotulo,
                          ocorrido_em=_iso(agora - timedelta(hours=atraso)))

        listados = (await client.get(BASE, headers=headers)).json()
        assert [item["tipo"] for item in listados] == ["recente", "intermediaria", "antiga"]
    asyncio.run(_with_client(c4_db, scenario))


def test_plantao_corta_pelo_evento_mais_recente(c4_db):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db, permissions=KEYS | {"plantao:ler"})
        agora = datetime.now(timezone.utc)
        for rotulo, atraso in (("antiga", 9), ("recente", 1), ("intermediaria", 5)):
            await _create(client, resident, headers, tipo=rotulo,
                          ocorrido_em=_iso(agora - timedelta(hours=atraso)))

        # limit menor que o total: quem sobrevive ao corte e decidido pela hora do
        # evento. A ordem final da projecao e por registro_id, entao a assercao e
        # sobre o CONJUNTO retirado, nao sobre a sequencia.
        resposta = await client.get("/api/plantao/", headers=headers, params={"limit": 2})
        assert resposta.status_code == 200, resposta.text
        descricoes = {item["descricao"] for item in resposta.json()}
        assert descricoes == {"Intercorrencia aberta: recente", "Intercorrencia aberta: intermediaria"}
    asyncio.run(_with_client(c4_db, scenario))


# --------------------------------------------------------------- prontuario ----

def test_prontuario_separa_ocorrido_de_registrado(c4_db):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        madrugada = datetime.now(timezone.utc) - timedelta(hours=8)
        row = await _create(client, resident, headers, ocorrido_em=_iso(madrugada))

        resposta = await client.get(f"/api/residentes/{resident.id}/prontuario", headers=headers)
        assert resposta.status_code == 200, resposta.text
        evento = next(e for e in resposta.json()["items"] if e["registro_id"] == row["id"])
        assert abs((_aware(evento["ocorrido_em"]) - madrugada).total_seconds()) < 1
        # registrado_em continua sendo o timestamp tecnico data.
        assert _aware(evento["registrado_em"]) - _aware(evento["ocorrido_em"]) > timedelta(hours=7)
    asyncio.run(_with_client(c4_db, scenario))


def test_prontuario_keyset_pagina_sem_perda_nem_duplicata(c4_db):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        agora = datetime.now(timezone.utc)
        esperados = []
        for indice in range(7):
            row = await _create(client, resident, headers, tipo=f"evento-{indice}",
                                ocorrido_em=_iso(agora - timedelta(hours=indice + 1)))
            esperados.append(row["id"])

        coletados, cursor = [], None
        for _ in range(10):  # teto de seguranca contra laco infinito
            params = {"origem": "intercorrencia", "limit": 2}
            if cursor:
                params["cursor"] = cursor
            pagina = (await client.get(
                f"/api/residentes/{resident.id}/prontuario", headers=headers, params=params)).json()
            coletados.extend(e["registro_id"] for e in pagina["items"])
            cursor = pagina["next_cursor"]
            if not pagina["has_more"]:
                break

        assert len(coletados) == len(set(coletados)) == len(esperados)
        # Ordem global desc por ocorrido_em: evento-0 e o mais recente.
        assert coletados == esperados
    asyncio.run(_with_client(c4_db, scenario))


# ------------------------------------------------------------------- RBAC ----

def test_cuidador_le_e_cria_mas_nao_atualiza(c4_db):
    async def scenario(client, db):
        ilpi, _, resident, admin_headers = await _setup(db)
        row = await _create(client, resident, admin_headers)
        cuidador = await _create_ilpi_user(db, ilpi, permissions=CUIDADOR_KEYS, profile_key="cuidador")
        await db.commit()
        headers = _auth_headers(cuidador, scope="ilpi", ilpi_id=ilpi.id)

        assert (await client.get(BASE, headers=headers)).status_code == 200
        assert (await client.get(BASE + row["id"], headers=headers)).status_code == 200
        criada = await client.post(BASE, headers=headers, json={
            "residente_id": resident.id, "tipo": "engasgo", "gravidade": "moderada"})
        assert criada.status_code == 201, criada.text

        for metodo, caminho, payload in (
            ("PATCH", BASE + row["id"], {"providencia": "tentativa"}),
            ("POST", BASE + row["id"] + "/encerrar", {"desfecho": "tentativa"}),
        ):
            negado = await client.request(metodo, caminho, headers=headers, json=payload)
            assert negado.status_code == 403, negado.text
            assert _detail_code(negado) == "PERMISSION_DENIED"
    asyncio.run(_with_client(c4_db, scenario))


def test_019_concede_ao_template_cuidador_sem_atualizar(c4_db):
    async def scenario(client, db):
        chaves = {row[0] for row in (await db.execute(text(
            "SELECT p.chave FROM permissoes p "
            "JOIN perfil_permissoes pp ON pp.permissao_id = p.id "
            "JOIN perfis perf ON perf.id = pp.perfil_id "
            "WHERE perf.chave = 'cuidador' AND perf.ilpi_id IS NULL"
        ))).all()}
        assert CUIDADOR_KEYS <= chaves
        assert "intercorrencias:atualizar" not in chaves
        # Catalogo intocado: a 019 concede vinculos, nao cria permissao.
        assert (await db.execute(select(func.count()).select_from(m.Permissao))).scalar_one() == 94
    asyncio.run(_with_client(c4_db, scenario))


def test_019_alcanca_clone_local_preexistente(c4_db):
    """Clone criado antes da 019 tambem recebe os grants."""
    _migrate(c4_db, "downgrade", REV_018)
    ilpi_id = _new_id()
    perfil_id = _new_id()

    async def semear(client, db):
        await db.execute(text(
            "INSERT INTO instituicoes (id, razao_social, cnpj, situacao) VALUES (:i, :r, :c, 'ativa')"
        ), {"i": ilpi_id, "r": "ILPI Clone B1", "c": _new_id()[:14]})
        await db.execute(text(
            "INSERT INTO perfis (id, ilpi_id, nome, chave, descricao, escopo, situacao) "
            "VALUES (:p, :i, 'Cuidador', 'cuidador', 'clone local', 'ilpi', 'ativo')"
        ), {"p": perfil_id, "i": ilpi_id})
        await db.commit()
    asyncio.run(_with_client(c4_db, semear))

    _migrate(c4_db)

    async def conferir(client, db):
        chaves = {row[0] for row in (await db.execute(text(
            "SELECT p.chave FROM permissoes p JOIN perfil_permissoes pp ON pp.permissao_id = p.id "
            "WHERE pp.perfil_id = :p"
        ), {"p": perfil_id})).all()}
        assert chaves == CUIDADOR_KEYS
    asyncio.run(_with_client(c4_db, conferir))


# -------------------------------------------------------------- migration ----

def test_migration_backfill_usa_data_do_registro(c4_db):
    _migrate(c4_db, "downgrade", REV_018)
    ilpi_id, residente_id = _new_id(), _new_id()
    com_data, sem_data = _new_id(), _new_id()
    marca = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)

    async def semear(client, db):
        await db.execute(text(
            "INSERT INTO instituicoes (id, razao_social, cnpj, situacao) VALUES (:i, 'ILPI B1', :c, 'ativa')"
        ), {"i": ilpi_id, "c": _new_id()[:14]})
        await db.execute(text(
            "INSERT INTO residentes (id, instituicao_id, nome, data_nascimento) "
            "VALUES (:r, :i, 'Residente B1', '1940-01-01')"
        ), {"r": residente_id, "i": ilpi_id})
        await db.execute(text(
            "INSERT INTO intercorrencias (id, residente_id, ilpi_id, tipo, situacao, data) "
            "VALUES (:id, :r, :i, 'historica', 'aberta', :d)"
        ), {"id": com_data, "r": residente_id, "i": ilpi_id, "d": marca})
        # data nasceu nullable na 001; o backfill precisa cobrir esse caso.
        await db.execute(text(
            "INSERT INTO intercorrencias (id, residente_id, ilpi_id, tipo, situacao, data) "
            "VALUES (:id, :r, :i, 'sem_data', 'aberta', NULL)"
        ), {"id": sem_data, "r": residente_id, "i": ilpi_id})
        await db.commit()
    asyncio.run(_with_client(c4_db, semear))

    _migrate(c4_db)

    async def conferir(client, db):
        linhas = {row[0]: row[1] for row in (await db.execute(text(
            "SELECT id, ocorrido_em FROM intercorrencias"))).all()}
        assert abs((_aware(linhas[com_data]) - marca).total_seconds()) < 1
        # NOT NULL efetivo: nenhuma linha ficou sem hora de evento.
        assert linhas[sem_data] is not None
    asyncio.run(_with_client(c4_db, conferir))


def test_migration_idempotente_e_downgrade_reverte(c4_db):
    # Reaplicar head sobre head nao deve quebrar.
    _migrate(c4_db)

    async def com_coluna(client, db):
        assert (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == _head_da_cadeia()
        await db.execute(text("SELECT ocorrido_em FROM intercorrencias"))
    asyncio.run(_with_client(c4_db, com_coluna))

    _migrate(c4_db, "downgrade", REV_018)

    async def sem_coluna(client, db):
        chaves = {row[0] for row in (await db.execute(text(
            "SELECT p.chave FROM permissoes p JOIN perfil_permissoes pp ON pp.permissao_id = p.id "
            "JOIN perfis perf ON perf.id = pp.perfil_id "
            "WHERE perf.chave = 'cuidador' AND perf.ilpi_id IS NULL"))).all()}
        # Sem esta limpeza, 015 e 011 recusariam os proprios downgrades.
        assert not (CUIDADOR_KEYS & chaves)
        with pytest.raises(Exception):
            await db.execute(text("SELECT ocorrido_em FROM intercorrencias"))
    asyncio.run(_with_client(c4_db, sem_coluna))


def test_fk_composta_e_indices_sobrevivem_a_recriacao(c4_db):
    """batch_alter_table recria a tabela inteira no SQLite. A FK composta
    (residente_id, ilpi_id) da 003 e os indices anteriores precisam sair intactos.

    A assercao e sobre a DECLARACAO do schema, nao sobre a imposicao: a engine das
    fixtures nao liga PRAGMA foreign_keys, entao um INSERT cross-tenant passaria aqui
    mesmo com a FK presente. A imposicao real ja e coberta pelos testes de API da C.4.
    Introspeccao via inspector serve SQLite e PostgreSQL sem ramificar por dialeto.
    """
    async def scenario(client, db):
        conexao = await db.connection()
        fks = await conexao.run_sync(lambda c: sa_inspect(c).get_foreign_keys("intercorrencias"))
        composta = [
            fk for fk in fks
            if set(fk["constrained_columns"]) == {"residente_id", "ilpi_id"}
            and fk["referred_table"] == "residentes"
        ]
        assert composta, f"FK composta perdida na recriacao: {fks}"
        assert set(composta[0]["referred_columns"]) == {"id", "instituicao_id"}

        indices = await conexao.run_sync(
            lambda c: {i["name"] for i in sa_inspect(c).get_indexes("intercorrencias")})
        assert {"ix_intercorrencias_residente_id", "ix_intercorrencias_ilpi_id",
                "ix_intercorrencias_ilpi_residente_ocorrido"} <= indices

        colunas = await conexao.run_sync(
            lambda c: {col["name"]: col for col in sa_inspect(c).get_columns("intercorrencias")})
        assert colunas["ocorrido_em"]["nullable"] is False
    asyncio.run(_with_client(c4_db, scenario))

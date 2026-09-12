"""H0-3 (Issue #25): ato dedicado de validacao documental.

Fecha o bypass do PUT generico (documentos:atualizar + situacao="validado")
substituindo-o por POST /documentos/{id}/validar, com permissao propria
(documentos:validar), tenant da sessao, autoria/timestamp do backend e
auditoria dedicada. Cobre RBAC, tenant, payload hostil, transicoes
protegidas, gate de Admissao e migration 017 (SQLite/PostgreSQL).
"""

import asyncio
import json
import os

import pytest
from sqlalchemy import func, select, text

from .test_d3_admissao_migration import _engine, _migrate, _ref
from .test_d3_admissao_migration import HEAD as PRE_017_HEAD
from .test_d3_admissao import ALL, DOMAIN, URL as ADMISSOES_URL, _client, _create, _setup
from .test_d2_rotina import _code, _create_platform_user, _headers, _new_id
from src.infrastructure import models as m

HEAD = "017_h03_documentos_validar"


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def h03_db(request, tmp_path):
    ref = _ref(request, tmp_path)
    _migrate(ref, target=HEAD)
    return ref


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def pre017_db(request, tmp_path):
    # Banco parado exatamente antes da 017, para testar a propria transicao
    # de upgrade/downgrade (017 depende de 016 = PRE_017_HEAD).
    ref = _ref(request, tmp_path)
    _migrate(ref, target=PRE_017_HEAD)
    return ref


async def _create_doc(client, h, resident_id, **kwargs):
    payload = {"residente_id": resident_id, "tipo": "Identificacao", "obrigatorio": True, **kwargs}
    r = await client.post("/api/documentos/", headers=h, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def _reload_doc(db, doc_id):
    return (await db.execute(select(m.Documento).where(m.Documento.id == doc_id))).scalar_one()


async def _audit_count(db, doc_id):
    return await db.scalar(
        select(func.count()).select_from(m.Auditoria).where(
            m.Auditoria.acao == "documentos.validar", m.Auditoria.registro_id == doc_id
        )
    )


# ---- 01/11/12: PUT generico nao pode validar nem alterar documento validado ----

def test_put_generico_situacao_validado_bloqueado(h03_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        r = await client.put(f"/api/documentos/{doc['id']}", headers=h, json={"situacao": "validado"})
        assert r.status_code == 422, r.text
        assert _code(r) == "DOCUMENTO_TRANSICAO_PROTEGIDA"
        stored = await _reload_doc(db, doc["id"])
        assert stored.situacao == "pendente"
        assert stored.validado_por is None
    asyncio.run(_client(h03_db, op))


@pytest.mark.parametrize("origem", ["pendente", "rejeitado"])
def test_put_para_validado_bloqueado_a_partir_de_qualquer_origem(h03_db, origem):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        if origem != "pendente":
            r = await client.put(f"/api/documentos/{doc['id']}", headers=h, json={"situacao": origem})
            assert r.status_code == 200, r.text
        r = await client.put(f"/api/documentos/{doc['id']}", headers=h, json={"situacao": "validado"})
        assert r.status_code == 422, r.text
        assert _code(r) == "DOCUMENTO_TRANSICAO_PROTEGIDA"
    asyncio.run(_client(h03_db, op))


@pytest.mark.parametrize("destino", ["pendente", "rejeitado"])
def test_documento_validado_put_situacao_diferente_bloqueado(h03_db, destino):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        r = await client.post(f"/api/documentos/{doc['id']}/validar", headers=h, json={})
        assert r.status_code == 200, r.text
        r = await client.put(f"/api/documentos/{doc['id']}", headers=h, json={"situacao": destino})
        assert r.status_code == 422, r.text
        assert _code(r) == "DOCUMENTO_TRANSICAO_PROTEGIDA"
    asyncio.run(_client(h03_db, op))


def test_documento_validado_put_situacao_validado_de_novo_bloqueado(h03_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        r = await client.post(f"/api/documentos/{doc['id']}/validar", headers=h, json={})
        assert r.status_code == 200, r.text
        r = await client.put(f"/api/documentos/{doc['id']}", headers=h, json={"situacao": "validado"})
        assert r.status_code == 422, r.text
    asyncio.run(_client(h03_db, op))


def test_put_outros_campos_continua_funcionando(h03_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        r = await client.put(f"/api/documentos/{doc['id']}", headers=h, json={"numero": "123", "arquivo": "a.pdf"})
        assert r.status_code == 200, r.text
        assert r.json()["numero"] == "123"
        assert r.json()["situacao"] == "pendente"
    asyncio.run(_client(h03_db, op))


# ---- 02/03/06: RBAC do ato dedicado ----

def test_post_validar_autorizado(h03_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        r = await client.post(f"/api/documentos/{doc['id']}/validar", headers=h, json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["situacao"] == "validado"
        assert body["validado_por"] == user.id
        assert body["validado_em"] is not None
    asyncio.run(_client(h03_db, op))


def test_post_validar_sem_permissao_bloqueado(h03_db):
    async def op(client, db):
        perms = (ALL | DOMAIN) - {"documentos:validar"}
        tenant, user, resident, employee, h = await _setup(db, permissions=perms)
        doc = await _create_doc(client, h, resident.id)
        r = await client.post(f"/api/documentos/{doc['id']}/validar", headers=h, json={})
        assert r.status_code == 403, r.text
        stored = await _reload_doc(db, doc["id"])
        assert stored.situacao == "pendente"
    asyncio.run(_client(h03_db, op))


def test_platform_superuser_bloqueado(h03_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        platform_user = await _create_platform_user(db)
        await db.commit()
        h_platform = _headers(platform_user, scope="global")
        r = await client.post(f"/api/documentos/{doc['id']}/validar", headers=h_platform, json={})
        assert r.status_code == 403, r.text
        stored = await _reload_doc(db, doc["id"])
        assert stored.situacao == "pendente"
    asyncio.run(_client(h03_db, op))


# ---- 04: payload hostil, zero efeito colateral ----

@pytest.mark.parametrize("payload", [
    {"situacao": "validado"},
    {"validado_por": "outro-usuario"},
    {"usuario_id": "outro-usuario"},
    {"ilpi_id": "outra-ilpi"},
    {"validado_em": "2020-01-01T00:00:00Z"},
    {"campo_desconhecido": "x"},
])
def test_post_validar_payload_hostil_sem_efeito_colateral(h03_db, payload):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        r = await client.post(f"/api/documentos/{doc['id']}/validar", headers=h, json=payload)
        assert r.status_code == 422, r.text
        stored = await _reload_doc(db, doc["id"])
        assert stored.situacao == "pendente"
        assert stored.validado_por is None
        assert stored.validado_em is None
        assert await _audit_count(db, doc["id"]) == 0
    asyncio.run(_client(h03_db, op))


# ---- Revisao pos-review: guard deve usar o MESMO valor normalizado (.strip())
# que sera persistido, nao o valor cru do payload; senao " validado "/
# "validado\t" escapam do bloqueio e sao persistidos sem autoria/auditoria. ----

@pytest.mark.parametrize("situacao_hostil", ["validado", " validado ", "validado ", "\tvalidado\t"])
def test_put_situacao_validado_com_variacoes_de_espaco_bloqueado(h03_db, situacao_hostil):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        r = await client.put(f"/api/documentos/{doc['id']}", headers=h, json={"situacao": situacao_hostil})
        assert r.status_code == 422, r.text
        assert _code(r) == "DOCUMENTO_TRANSICAO_PROTEGIDA"
        stored = await _reload_doc(db, doc["id"])
        assert stored.situacao == "pendente"
        assert stored.validado_por is None
        assert stored.validado_em is None
        assert await _audit_count(db, doc["id"]) == 0
    asyncio.run(_client(h03_db, op))


# ---- 05/14: cross-tenant e inexistente sao indistinguiveis ----

def test_post_validar_cross_tenant_404(h03_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        _, _, _, _, h_other = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        r = await client.post(f"/api/documentos/{doc['id']}/validar", headers=h_other, json={})
        assert r.status_code == 404, r.text
        assert _code(r) == "RESOURCE_NOT_FOUND"
        stored = await _reload_doc(db, doc["id"])
        assert stored.situacao == "pendente"
    asyncio.run(_client(h03_db, op))


def test_post_validar_inexistente_e_cross_tenant_identicos(h03_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        _, _, _, _, h_other = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        r_missing = await client.post(f"/api/documentos/{_new_id()}/validar", headers=h, json={})
        r_cross = await client.post(f"/api/documentos/{doc['id']}/validar", headers=h_other, json={})
        assert r_missing.status_code == r_cross.status_code == 404
        assert r_missing.json() == r_cross.json()
    asyncio.run(_client(h03_db, op))


# ---- 07: validacao legitima -> autor, timestamp, auditoria unica, sem segredo ----

def test_validacao_legitima_autor_timestamp_auditoria(h03_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        r = await client.post(f"/api/documentos/{doc['id']}/validar", headers=h, json={})
        assert r.status_code == 200, r.text
        stored = await _reload_doc(db, doc["id"])
        assert stored.validado_por == user.id
        assert stored.validado_em is not None
        rows = (await db.execute(
            select(m.Auditoria).where(m.Auditoria.acao == "documentos.validar", m.Auditoria.registro_id == doc["id"])
        )).scalars().all()
        assert len(rows) == 1
        audit = rows[0]
        assert audit.usuario_id == user.id
        assert audit.ilpi_id == tenant.id
        posteriores = json.loads(audit.valores_posteriores)
        assert posteriores["situacao"] == "validado"
        assert posteriores["validado_por"] == user.id
        sensitive = ("senha", "password", "token", "cookie", "segredo", "secret")
        assert not any(key in posteriores for key in sensitive)
    asyncio.run(_client(h03_db, op))


# ---- 08/09: gate de Admissao antes/depois da validacao ----

def test_admissao_bloqueada_antes_e_avanca_apos_validacao(h03_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        admissao = await _create(client, h, resident)
        doc = await _create_doc(client, h, resident.id)
        r = await client.get(f"{ADMISSOES_URL}{admissao['id']}/pendencias", headers=h)
        assert r.status_code == 200, r.text
        pendentes = [p for p in r.json()["pendencias"] if p["codigo"] == "documentacao_pendente"]
        assert pendentes, "documento obrigatorio nao validado deveria bloquear"
        r = await client.post(f"/api/documentos/{doc['id']}/validar", headers=h, json={})
        assert r.status_code == 200, r.text
        r = await client.get(f"{ADMISSOES_URL}{admissao['id']}/pendencias", headers=h)
        assert r.status_code == 200, r.text
        pendentes = [p for p in r.json()["pendencias"] if p["codigo"] == "documentacao_pendente"]
        assert not pendentes
    asyncio.run(_client(h03_db, op))


# ---- 13: revalidacao explicitamente proibida ----

def test_post_validar_novamente_conflito(h03_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        r1 = await client.post(f"/api/documentos/{doc['id']}/validar", headers=h, json={})
        assert r1.status_code == 200, r1.text
        r2 = await client.post(f"/api/documentos/{doc['id']}/validar", headers=h, json={})
        assert r2.status_code == 409, r2.text
        assert _code(r2) == "DOCUMENTO_JA_VALIDADO"
    asyncio.run(_client(h03_db, op))


# ---- 15: legado (situacao=validado sem autoria) permanece reconhecido ----

def test_legado_sem_autoria_reconhecido_pela_admissao(h03_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        admissao = await _create(client, h, resident)
        doc = m.Documento(
            id=_new_id(), instituicao_id=tenant.id, residente_id=resident.id,
            tipo="Legado", obrigatorio=True, situacao="validado",
        )
        db.add(doc)
        await db.commit()
        r = await client.get(f"{ADMISSOES_URL}{admissao['id']}/pendencias", headers=h)
        assert r.status_code == 200, r.text
        pendentes = [p for p in r.json()["pendencias"] if p["codigo"] == "documentacao_pendente"]
        assert not pendentes
        stored = await _reload_doc(db, doc.id)
        assert stored.validado_por is None
        assert stored.validado_em is None
    asyncio.run(_client(h03_db, op))


# ---- 16/17/18: migration 017 (SQLite + PostgreSQL descartaveis) e RBAC ----

TEMPLATE_ID_QUERY = "SELECT id FROM perfis WHERE chave='ilpi_admin' AND ilpi_id IS NULL"
SUPER_ID_QUERY = "SELECT id FROM perfis WHERE chave='platform_superuser' AND ilpi_id IS NULL"


async def _one(engine, sql, params=None):
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params or {})).first()


def test_migration_017_upgrade_concede_ilpi_admin_e_clones_zero_platform_superuser(pre017_db):
    async def run():
        engine = _engine(pre017_db)
        try:
            template_id = (await _one(engine, TEMPLATE_ID_QUERY))[0]
            super_id = (await _one(engine, SUPER_ID_QUERY))[0]
            clone_id, tenant_id = _new_id(), _new_id()
            async with engine.begin() as conn:
                await conn.execute(text("INSERT INTO instituicoes (id, razao_social) VALUES (:id, 'H03')"), {"id": tenant_id})
                await conn.execute(
                    text(
                        "INSERT INTO perfis (id, ilpi_id, nome, chave, escopo, situacao) "
                        "VALUES (:id, :ilpi, 'Admin H03', 'ilpi_admin', 'ilpi', 'ativo')"
                    ),
                    {"id": clone_id, "ilpi": tenant_id},
                )
            before = (await _one(engine, "SELECT count(*) FROM permissoes"))[0]
        finally:
            await engine.dispose()

        _migrate(pre017_db, target=HEAD)

        engine = _engine(pre017_db)
        try:
            after = (await _one(engine, "SELECT count(*) FROM permissoes"))[0]
            assert after == before + 1
            perm = await _one(engine, "SELECT id FROM permissoes WHERE chave='documentos:validar'")
            assert perm is not None
            perm_id = perm[0]
            assert await _one(engine, "SELECT 1 FROM perfil_permissoes WHERE perfil_id=:p AND permissao_id=:m", {"p": template_id, "m": perm_id})
            assert await _one(engine, "SELECT 1 FROM perfil_permissoes WHERE perfil_id=:p AND permissao_id=:m", {"p": clone_id, "m": perm_id})
            assert not await _one(engine, "SELECT 1 FROM perfil_permissoes WHERE perfil_id=:p AND permissao_id=:m", {"p": super_id, "m": perm_id})
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_migration_017_downgrade_recusa_perder_evidencia_de_validacao(pre017_db):
    async def run():
        _migrate(pre017_db, target=HEAD)
        engine = _engine(pre017_db)
        tenant_id, resident_id, user_id, doc_id = _new_id(), _new_id(), _new_id(), _new_id()
        try:
            async with engine.begin() as conn:
                await conn.execute(text("INSERT INTO instituicoes (id, razao_social) VALUES (:id, 'H03')"), {"id": tenant_id})
                await conn.execute(
                    text("INSERT INTO users (id, nome, email, password_hash, ativo) VALUES (:id, 'H03', :email, 'x', true)"),
                    {"id": user_id, "email": f"{user_id}@example.com"},
                )
                await conn.execute(
                    text("INSERT INTO residentes (id, instituicao_id, nome, data_nascimento, situacao) VALUES (:id, :tenant, 'R', '1940-01-01', 'Ativo')"),
                    {"id": resident_id, "tenant": tenant_id},
                )
                await conn.execute(
                    text(
                        "INSERT INTO documentos (id, instituicao_id, residente_id, tipo, obrigatorio, situacao, validado_por, validado_em) "
                        "VALUES (:id, :tenant, :res, 'D', true, 'validado', :user, CURRENT_TIMESTAMP)"
                    ),
                    {"id": doc_id, "tenant": tenant_id, "res": resident_id, "user": user_id},
                )
        finally:
            await engine.dispose()

        result = _migrate(pre017_db, target="016_d3_admissao", command="downgrade", success=False)
        assert "validado_por" in (result.stdout + result.stderr)

        engine = _engine(pre017_db)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE documentos SET validado_por=NULL, validado_em=NULL WHERE id=:id"), {"id": doc_id})
        finally:
            await engine.dispose()

        _migrate(pre017_db, target="016_d3_admissao", command="downgrade", success=True)
    asyncio.run(run())


# ---- Revisao pos-review: validacao/persistencia atomicas sob concorrencia ----
#
# validar_documento agora le com SELECT ... FOR UPDATE e escreve com um
# UPDATE condicional (WHERE situacao != 'validado'); update_item aplica o
# mesmo UPDATE condicional quando o PUT toca "situacao" de um Documento.
#
# No PostgreSQL, FOR UPDATE serializa de fato no nivel de linha: quem chega
# depois bloqueia na propria leitura ate o primeiro commit, e ja enxerga
# situacao=="validado" ao desbloquear.
# No SQLite, FOR UPDATE e compilado como um SELECT comum (dialeto ignora a
# clausula) — as duas leituras iniciais podem ver "pendente" simultaneamente;
# a corretude final nao depende do lock, e sim do UPDATE condicional: cada
# UPDATE reavalia seu WHERE contra o estado atual da linha no momento da
# escrita (semantica padrao de SQL), e o SQLite serializa escritores reais
# (lock de escrita de banco inteiro + PRAGMA busy_timeout ja configurado por
# test_d3_admissao_migration.py:_engine). O resultado observavel final e o
# mesmo nos dois bancos (nenhuma sobrescrita/duplicacao); o que difere e
# apenas o mecanismo interno de resolucao da corrida.

def test_concorrencia_post_validar_apenas_uma_vence(h03_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        r1, r2 = await asyncio.gather(
            client.post(f"/api/documentos/{doc['id']}/validar", headers=h, json={}),
            client.post(f"/api/documentos/{doc['id']}/validar", headers=h, json={}),
        )
        statuses = sorted([r1.status_code, r2.status_code])
        assert statuses == [200, 409], (r1.status_code, r2.status_code, r1.text, r2.text)
        vencedor = r1 if r1.status_code == 200 else r2
        assert _code(r2 if r1.status_code == 200 else r1) == "DOCUMENTO_JA_VALIDADO"
        stored = await _reload_doc(db, doc["id"])
        assert stored.situacao == "validado"
        assert stored.validado_por == user.id
        assert vencedor.json()["validado_por"] == user.id
        assert await _audit_count(db, doc["id"]) == 1
    asyncio.run(_client(h03_db, op))


def test_concorrencia_put_nao_sobrescreve_validacao_concluida(h03_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        put_result, post_result = await asyncio.gather(
            client.put(f"/api/documentos/{doc['id']}", headers=h, json={"situacao": "rejeitado"}),
            client.post(f"/api/documentos/{doc['id']}/validar", headers=h, json={}),
        )
        # O POST nunca pode "perder": o PUT jamais escreve "validado" (nem
        # concorrente, nem sequencial), entao o pior caso para o POST e
        # validar um documento que o PUT tenha acabado de deixar "rejeitado"
        # — o que ainda e uma transicao valida para /validar.
        assert post_result.status_code == 200, post_result.text
        assert put_result.status_code in (200, 422), put_result.text
        if put_result.status_code == 422:
            assert _code(put_result) == "DOCUMENTO_TRANSICAO_PROTEGIDA"
        # Invariante central pedida na revisao: independentemente de quem
        # executou primeiro, uma validacao concluida nunca e revertida.
        stored = await _reload_doc(db, doc["id"])
        assert stored.situacao == "validado"
        assert stored.validado_por == user.id
        assert stored.validado_em is not None
        assert await _audit_count(db, doc["id"]) == 1
    asyncio.run(_client(h03_db, op))

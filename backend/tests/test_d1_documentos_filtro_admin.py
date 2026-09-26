"""D1: filtro por residente em GET /documentos/ e emenda S.1 do administrativo.

Somente bancos descartaveis: SQLite em tmp_path e PostgreSQL 55486/facilpi_d3_test.
UPLOAD_ROOT e redirecionado para tmp_path: o storage oficial nunca e tocado.
"""

import asyncio
import os

import pytest
from sqlalchemy import select, text

from .test_d3_admissao_migration import _migrate, _ref
from .test_d3_admissao import ALL, DOMAIN, _client
from .test_d2_rotina import (
    _create_ilpi_user, _create_residente, _headers, _new_id, _new_institution, _code,
)
from .test_a3_documentos_arquivo import PDF, _anexar, _doc
from src import main
from src.infrastructure import models as m

HEAD = "020_documentos_admin_anexar"
PRE_020_HEAD = "019_b1_intercorrencias_ocorrido"

DOCUMENTOS_URL = "/api/documentos/"
# Capacidade do administrativo apos a 020: cria, atualiza, le e ANEXA.
ADMIN_APOS_020 = {"documentos:ler", "documentos:criar", "documentos:atualizar", "documentos:anexar"}
# Permanecem fora, por decisao explicita da Control Tower.
ADMIN_NEGADAS = {"documentos:validar", "documentos:inativar"}


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def d1_db(request, tmp_path):
    # Fixado na 020, nao em `head`: o mesmo padrao de `a3_db`. Apontar para a
    # ponta movel faria este teste quebrar na proxima migration, como a 020
    # acabou de fazer com a suite da B1.
    ref = _ref(request, tmp_path)
    _migrate(ref, target=HEAD)
    return ref


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def pre020_db(request, tmp_path):
    # Banco parado exatamente antes da 020, para exercitar a propria transicao.
    ref = _ref(request, tmp_path)
    _migrate(ref, target=PRE_020_HEAD)
    return ref


@pytest.fixture(autouse=True)
def upload_root(tmp_path, monkeypatch):
    root = (tmp_path / "uploads-d1").resolve()
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main, "UPLOAD_ROOT", root)
    return root


async def _tenant(db, *, permissions=None, nome="D1"):
    instituicao = _new_institution(nome)
    user = await _create_ilpi_user(
        db, instituicao, permissions=ALL | DOMAIN if permissions is None else permissions)
    residente = await _create_residente(db, instituicao.id, nome=f"Residente {nome}")
    await db.commit()
    return instituicao, user, residente, _headers(user, ilpi_id=instituicao.id)


async def _listar(client, headers, **params):
    return await client.get(DOCUMENTOS_URL, headers=headers, params=params)


# ------------------------------------------------------------ DOC-FILTER ----

def test_sem_residente_id_preserva_listagem_atual(d1_db):
    async def cenario(client, db):
        _, _, residente_a, headers = await _tenant(db)
        residente_b = await _create_residente(db, residente_a.instituicao_id, nome="Outro")
        await db.commit()
        criados = {(await _doc(client, headers, residente_a.id, tipo="RG"))["id"],
                   (await _doc(client, headers, residente_b.id, tipo="CPF"))["id"]}

        resposta = await _listar(client, headers)
        assert resposta.status_code == 200, resposta.text
        assert {item["id"] for item in resposta.json()} == criados
    asyncio.run(_client(d1_db, cenario))


def test_filtro_por_residente_valido(d1_db):
    async def cenario(client, db):
        _, _, residente_a, headers = await _tenant(db)
        residente_b = await _create_residente(db, residente_a.instituicao_id, nome="Outro")
        await db.commit()
        do_a = await _doc(client, headers, residente_a.id, tipo="RG")
        do_b = await _doc(client, headers, residente_b.id, tipo="CPF")

        resposta = await _listar(client, headers, residente_id=residente_a.id)
        assert resposta.status_code == 200, resposta.text
        ids = [item["id"] for item in resposta.json()]
        assert ids == [do_a["id"]]
        # Documento de outro residente do MESMO tenant nao aparece.
        assert do_b["id"] not in ids
    asyncio.run(_client(d1_db, cenario))


def test_residente_valido_sem_documentos_devolve_lista_vazia(d1_db):
    async def cenario(client, db):
        _, _, residente_a, headers = await _tenant(db)
        sem_documentos = await _create_residente(db, residente_a.instituicao_id, nome="Sem docs")
        await db.commit()
        await _doc(client, headers, residente_a.id, tipo="RG")

        resposta = await _listar(client, headers, residente_id=sem_documentos.id)
        assert resposta.status_code == 200, resposta.text
        assert resposta.json() == []
    asyncio.run(_client(d1_db, cenario))


def test_residente_inexistente_e_cross_tenant_compartilham_404(d1_db):
    async def cenario(client, db):
        _, _, residente_a, headers = await _tenant(db)
        _, _, residente_b, _ = await _tenant(db, nome="D1 Outra ILPI")
        await _doc(client, headers, residente_a.id, tipo="RG")

        inexistente = await _listar(client, headers, residente_id=_new_id())
        cross = await _listar(client, headers, residente_id=residente_b.id)

        assert inexistente.status_code == 404, inexistente.text
        assert cross.status_code == 404, cross.text
        assert _code(inexistente) == "RESOURCE_NOT_FOUND"
        # Corpo identico: a resposta nao revela que o residente existe em outra ILPI.
        assert inexistente.json() == cross.json()
    asyncio.run(_client(d1_db, cenario))


def test_skip_e_limit_funcionam_com_o_filtro(d1_db):
    async def cenario(client, db):
        _, _, residente, headers = await _tenant(db)
        for indice in range(5):
            await _doc(client, headers, residente.id, tipo=f"Doc {indice}")

        completa = await _listar(client, headers, residente_id=residente.id)
        assert len(completa.json()) == 5

        pagina = await _listar(client, headers, residente_id=residente.id, skip=2, limit=2)
        assert pagina.status_code == 200, pagina.text
        assert len(pagina.json()) == 2
        esperados = [item["id"] for item in completa.json()][2:4]
        assert [item["id"] for item in pagina.json()] == esperados
    asyncio.run(_client(d1_db, cenario))


def test_sem_documentos_ler_segue_403_antes_de_validar_residente(d1_db):
    async def cenario(client, db):
        instituicao, _, residente, _ = await _tenant(db)
        # Mesma ILPI, zero permissoes: isola o efeito da permissao. Em outra ILPI
        # o 403 seria AUTH_CONTEXT_REQUIRED, que nao e o que este teste afirma.
        sem_permissao = await _create_ilpi_user(
            db, instituicao, permissions=set(), profile_key="d1_sem")
        await db.commit()
        headers = _headers(sem_permissao, ilpi_id=instituicao.id)

        # Mesmo com residente_id invalido, a permissao decide primeiro: 403, nao 404.
        for alvo in (residente.id, _new_id()):
            resposta = await _listar(client, headers, residente_id=alvo)
            assert resposta.status_code == 403, resposta.text
            assert _code(resposta) == "PERMISSION_DENIED"
    asyncio.run(_client(d1_db, cenario))


def test_demais_roteadores_da_factory_seguem_sem_o_parametro(d1_db):
    """A factory e compartilhada: so documentos expoe residente_id.

    Nos demais o parametro continua sendo IGNORADO, como antes da D1 — nao pode
    virar erro, que seria quebra silenciosa de contrato fora do escopo.
    """
    async def cenario(client, db):
        _, _, residente, headers = await _tenant(db)

        parametros = {p["name"] for p in
                      main.app.openapi()["paths"][DOCUMENTOS_URL]["get"].get("parameters", [])}
        assert "residente_id" in parametros

        for rota in ("/api/residentes/", "/api/familiares/", "/api/tarefas/", "/api/alertas/"):
            nomes = {p["name"] for p in
                     main.app.openapi()["paths"][rota]["get"].get("parameters", [])}
            assert "residente_id" not in nomes, f"{rota} nao deveria expor residente_id"

        # E o parametro desconhecido continua IGNORADO, nao rejeitado: em
        # /residentes/ o usuario tem residentes:ler, entao 200 prova que o
        # parametro extra nao virou 422.
        resposta = await client.get("/api/residentes/", headers=headers,
                                    params={"residente_id": residente.id})
        assert resposta.status_code == 200, resposta.text
        assert {item["id"] for item in resposta.json()} >= {residente.id}
    asyncio.run(_client(d1_db, cenario))


# ------------------------------------------------------ RBAC administrativo ----

def test_template_administrativo_recebe_anexar_e_nada_mais(d1_db):
    async def cenario(client, db):
        chaves = {row[0] for row in (await db.execute(text(
            "SELECT p.chave FROM permissoes p "
            "JOIN perfil_permissoes pp ON pp.permissao_id = p.id "
            "JOIN perfis perf ON perf.id = pp.perfil_id "
            "WHERE perf.chave = 'administrativo' AND perf.ilpi_id IS NULL"))).all()}
        documentos = {c for c in chaves if c.startswith("documentos:")}
        assert documentos == ADMIN_APOS_020
        assert not (ADMIN_NEGADAS & chaves)
    asyncio.run(_client(d1_db, cenario))


def test_responsavel_tecnico_nao_foi_tocado(d1_db):
    async def cenario(client, db):
        chaves = {row[0] for row in (await db.execute(text(
            "SELECT p.chave FROM permissoes p "
            "JOIN perfil_permissoes pp ON pp.permissao_id = p.id "
            "JOIN perfis perf ON perf.id = pp.perfil_id "
            "WHERE perf.chave = 'responsavel_tecnico' AND perf.ilpi_id IS NULL "
            "AND p.chave LIKE 'documentos:%'"))).all()}
        assert chaves == {"documentos:ler"}
    asyncio.run(_client(d1_db, cenario))


def test_catalogo_e_baseline_de_templates(d1_db):
    async def cenario(client, db):
        catalogo = (await db.execute(text("SELECT COUNT(*) FROM permissoes"))).scalar_one()
        templates = (await db.execute(text(
            "SELECT COUNT(*) FROM perfil_permissoes pp JOIN perfis p ON p.id = pp.perfil_id "
            "WHERE p.ilpi_id IS NULL"))).scalar_one()
        # A 020 concede vinculo; nao cria permissao.
        assert catalogo == 94
        assert templates == 173
    asyncio.run(_client(d1_db, cenario))


def test_clone_local_preexistente_recebe_anexar(d1_db):
    """Clone criado antes da 020 tambem e alcancado."""
    _migrate(d1_db, target=PRE_020_HEAD, command="downgrade")
    ilpi_id, perfil_id = _new_id(), _new_id()

    async def semear(client, db):
        await db.execute(text(
            "INSERT INTO instituicoes (id, razao_social, cnpj, situacao) VALUES (:i, 'ILPI D1', :c, 'ativa')"
        ), {"i": ilpi_id, "c": _new_id()[:14]})
        await db.execute(text(
            "INSERT INTO perfis (id, ilpi_id, nome, chave, descricao, escopo, situacao) "
            "VALUES (:p, :i, 'Administrativo', 'administrativo', 'clone local', 'ilpi', 'ativo')"
        ), {"p": perfil_id, "i": ilpi_id})
        await db.commit()
    asyncio.run(_client(d1_db, semear))

    _migrate(d1_db, target="head")

    async def conferir(client, db):
        chaves = {row[0] for row in (await db.execute(text(
            "SELECT p.chave FROM permissoes p JOIN perfil_permissoes pp ON pp.permissao_id = p.id "
            "WHERE pp.perfil_id = :p"), {"p": perfil_id})).all()}
        assert chaves == {"documentos:anexar"}
    asyncio.run(_client(d1_db, conferir))


def test_administrativo_cria_documento_e_anexa_arquivo(d1_db):
    async def cenario(client, db):
        instituicao, _, residente, _ = await _tenant(db)
        admin = await _create_ilpi_user(
            db, instituicao, permissions=ADMIN_APOS_020, profile_key="administrativo")
        await db.commit()
        headers = _headers(admin, ilpi_id=instituicao.id)

        documento = await _doc(client, headers, residente.id, tipo="RG")
        anexo = await _anexar(client, headers, documento["id"])
        assert anexo.status_code == 201, anexo.text
        assert anexo.json()["arquivo_presente"] is True

        # Autoria vem da sessao, nunca do payload.
        persistido = (await db.execute(
            select(m.Documento).where(m.Documento.id == documento["id"]))).scalar_one()
        assert persistido.anexado_por == admin.id
        assert persistido.anexado_em is not None
        assert persistido.arquivo_mime == "application/pdf"

        # Auditoria registrada, com metadados e sem conteudo.
        acoes = {row[0] for row in (await db.execute(text(
            "SELECT acao FROM auditoria WHERE registro_id = :r"), {"r": documento["id"]})).all()}
        assert "documentos.anexar" in acoes
    asyncio.run(_client(d1_db, cenario))


def test_administrativo_segue_sem_validar_e_sem_inativar(d1_db):
    async def cenario(client, db):
        instituicao, _, residente, criador = await _tenant(db)
        documento = await _doc(client, criador, residente.id, tipo="RG")

        admin = await _create_ilpi_user(
            db, instituicao, permissions=ADMIN_APOS_020, profile_key="administrativo")
        await db.commit()
        headers = _headers(admin, ilpi_id=instituicao.id)

        validar = await client.post(f"/api/documentos/{documento['id']}/validar", headers=headers, json={})
        assert validar.status_code == 403, validar.text
        assert _code(validar) == "PERMISSION_DENIED"

        # DELETE fisico segue fail-closed para todos.
        remover = await client.delete(f"/api/documentos/{documento['id']}", headers=headers)
        assert remover.status_code == 403, remover.text
    asyncio.run(_client(d1_db, cenario))


def test_anexo_cross_tenant_continua_bloqueado(d1_db):
    async def cenario(client, db):
        _, _, residente_a, headers_a = await _tenant(db)
        instituicao_b, _, residente_b, _ = await _tenant(db, nome="D1 ILPI B")
        documento_a = await _doc(client, headers_a, residente_a.id, tipo="RG")

        # O usuario da ILPI B PRECISA ter anexar: sem isso o teste provaria 403
        # por permissao, nao isolamento de tenant.
        usuario_b = await _create_ilpi_user(
            db, instituicao_b, permissions=ADMIN_APOS_020, profile_key="administrativo")
        await db.commit()
        headers_b = _headers(usuario_b, ilpi_id=instituicao_b.id)

        anexo = await _anexar(client, headers_b, documento_a["id"])
        assert anexo.status_code == 404, anexo.text
        assert _code(anexo) == "RESOURCE_NOT_FOUND"
        assert residente_b.id not in anexo.text
    asyncio.run(_client(d1_db, cenario))


# -------------------------------------------------------------- migration ----

def test_migration_upgrade_idempotente_e_downgrade(d1_db):
    # Reaplicar a 020 sobre a 020 nao deve quebrar nem duplicar vinculo.
    # (Alvo fixo: com a 021 a ponta movel deixou de ser a 020.)
    _migrate(d1_db, target=HEAD)

    async def apos_upgrade(client, db):
        assert (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == HEAD
        vinculos = (await db.execute(text(
            "SELECT COUNT(*) FROM perfil_permissoes pp "
            "JOIN perfis perf ON perf.id = pp.perfil_id "
            "JOIN permissoes p ON p.id = pp.permissao_id "
            "WHERE perf.chave = 'administrativo' AND p.chave = 'documentos:anexar'"))).scalar_one()
        assert vinculos == 1
    asyncio.run(_client(d1_db, apos_upgrade))

    _migrate(d1_db, target=PRE_020_HEAD, command="downgrade")

    async def apos_downgrade(client, db):
        assert (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == PRE_020_HEAD
        chaves = {row[0] for row in (await db.execute(text(
            "SELECT p.chave FROM permissoes p JOIN perfil_permissoes pp ON pp.permissao_id = p.id "
            "JOIN perfis perf ON perf.id = pp.perfil_id "
            "WHERE perf.chave = 'administrativo' AND perf.ilpi_id IS NULL"))).all()}
        # Sem esta limpeza, 018 e 015 recusariam os proprios downgrades.
        assert "documentos:anexar" not in chaves
        # O catalogo permanece: a 020 nunca criou permissao.
        assert (await db.execute(text(
            "SELECT COUNT(*) FROM permissoes WHERE chave = 'documentos:anexar'"))).scalar_one() == 1
    asyncio.run(_client(d1_db, apos_downgrade))


def test_pre_020_nao_tem_o_grant(pre020_db):
    """Prova que a capacidade e introduzida pela 020, nao herdada."""
    async def cenario(client, db):
        chaves = {row[0] for row in (await db.execute(text(
            "SELECT p.chave FROM permissoes p JOIN perfil_permissoes pp ON pp.permissao_id = p.id "
            "JOIN perfis perf ON perf.id = pp.perfil_id "
            "WHERE perf.chave = 'administrativo' AND perf.ilpi_id IS NULL "
            "AND p.chave LIKE 'documentos:%'"))).all()}
        assert chaves == {"documentos:ler", "documentos:criar", "documentos:atualizar"}
    asyncio.run(_client(pre020_db, cenario))

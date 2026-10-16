"""A3 (Issue #45): anexo seguro de arquivo em Documento.

Substitui ``POST /uploads/{entity_id}``, que gravava em STORAGE_PATH — o mesmo
diretorio de ``app.db`` — usando ``entity_id`` e ``file.filename`` crus, dois
vetores de path traversal. Cobre RBAC, tenant, conteudo real, limites,
unicidade do anexo, consistencia filesystem/DB, auditoria e migration 018.

UPLOAD_ROOT e redirecionado para tmp_path em toda operacao: nenhum teste
escreve no storage oficial.
"""

import asyncio
import hashlib
import os

import pytest
from sqlalchemy import func, inspect as sa_inspect, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from .test_d3_admissao_migration import _engine, _migrate, _ref
from .test_d3_admissao import ALL, DOMAIN, _client, _setup
from .test_d2_rotina import _code, _create_platform_user, _headers, _new_id
from src import main
from src.infrastructure import models as m

HEAD = "018_a3_documentos_arquivo"
PRE_018_HEAD = "017_h03_documentos_validar"

A3 = ALL | DOMAIN | {"documentos:anexar"}

# Conteudos minimos com assinatura real. O primeiro byte decide o MIME.
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
TEXTO = b"isto nao tem assinatura reconhecida\n"


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def a3_db(request, tmp_path):
    ref = _ref(request, tmp_path)
    _migrate(ref, target=HEAD)
    return ref


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def pre018_db(request, tmp_path):
    # Banco parado exatamente antes da 018, para exercitar a propria transicao.
    ref = _ref(request, tmp_path)
    _migrate(ref, target=PRE_018_HEAD)
    return ref


@pytest.fixture(autouse=True)
def upload_root(tmp_path, monkeypatch):
    """Isola o storage de anexos: o diretorio oficial nunca e tocado."""
    root = (tmp_path / "uploads-a3").resolve()
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main, "UPLOAD_ROOT", root)
    return root


async def _doc(client, h, resident_id, **kwargs):
    payload = {"residente_id": resident_id, "tipo": "Identificacao", "obrigatorio": True, **kwargs}
    r = await client.post("/api/documentos/", headers=h, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def _anexar(client, h, doc_id, *, conteudo=PDF, nome="rg.pdf", mime="application/pdf"):
    return await client.post(
        f"/api/documentos/{doc_id}/arquivo",
        headers=h,
        files={"file": (nome, conteudo, mime)},
    )


async def _reload(db, doc_id):
    return (await db.execute(select(m.Documento).where(m.Documento.id == doc_id))).scalar_one()


async def _audits(db, doc_id):
    return await db.scalar(
        select(func.count()).select_from(m.Auditoria).where(
            m.Auditoria.acao == "documentos.anexar", m.Auditoria.registro_id == doc_id
        )
    )


def _arquivos(root):
    return sorted(p for p in root.rglob("*") if p.is_file())


def _temporarios(root):
    return sorted(p for p in root.rglob(".tmp-*"))


# ---- Caminho feliz, metadados e auditoria ----

def test_anexo_autorizado_persiste_metadados_e_audita(a3_db, upload_root):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        r = await _anexar(client, h, doc["id"], conteudo=PDF, nome="rg.pdf")
        assert r.status_code == 201, r.text

        corpo = r.json()
        assert corpo["arquivo_presente"] is True
        assert corpo["arquivo_nome_original"] == "rg.pdf"
        assert corpo["arquivo_mime"] == "application/pdf"
        assert corpo["arquivo_tamanho"] == len(PDF)
        assert corpo["arquivo_hash"] == hashlib.sha256(PDF).hexdigest()
        assert corpo["anexado_por"] == user.id
        assert corpo["anexado_em"] is not None
        # A chave de storage nunca sai na resposta.
        assert "arquivo" not in corpo

        stored = await _reload(db, doc["id"])
        assert stored.arquivo == f"{tenant.id}/{doc['id']}/{stored.arquivo.split('/')[-1]}"
        assert stored.anexado_por == user.id
        assert await _audits(db, doc["id"]) == 1

        arquivos = _arquivos(upload_root)
        assert len(arquivos) == 1
        assert arquivos[0].read_bytes() == PDF
        assert not _temporarios(upload_root)
    asyncio.run(_client(a3_db, op))


def test_auditoria_nao_registra_conteudo_nem_caminho(a3_db, upload_root):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        assert (await _anexar(client, h, doc["id"])).status_code == 201

        registro = (await db.execute(
            select(m.Auditoria).where(m.Auditoria.acao == "documentos.anexar", m.Auditoria.registro_id == doc["id"])
        )).scalar_one()
        payload = (registro.valores_posteriores or "")
        assert "%PDF" not in payload
        assert str(upload_root) not in payload
        assert "arquivo_hash" in payload
    asyncio.run(_client(a3_db, op))


@pytest.mark.parametrize("conteudo,mime_esperado", [(PDF, "application/pdf"), (PNG, "image/png"), (JPEG, "image/jpeg")])
def test_tipos_permitidos_sao_detectados_pelo_conteudo(a3_db, conteudo, mime_esperado):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        # content_type do multipart mente deliberadamente; vale a assinatura.
        r = await _anexar(client, h, doc["id"], conteudo=conteudo, nome="x.bin", mime="application/octet-stream")
        assert r.status_code == 201, r.text
        assert r.json()["arquivo_mime"] == mime_esperado
    asyncio.run(_client(a3_db, op))


# ---- RBAC e tenant ----

def test_sem_documentos_anexar_recebe_403(a3_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3 - {"documentos:anexar"})
        doc = await _doc(client, h, resident.id)
        r = await _anexar(client, h, doc["id"])
        assert r.status_code == 403, r.text
        assert _code(r) == "PERMISSION_DENIED"
    asyncio.run(_client(a3_db, op))


def test_anexo_cross_tenant_responde_404(a3_db, upload_root):
    async def op(client, db):
        tenant_a, user_a, resident_a, _, ha = await _setup(db, permissions=A3)
        doc = await _doc(client, ha, resident_a.id)
        _, _, _, _, hb = await _setup(db, permissions=A3)
        r = await _anexar(client, hb, doc["id"])
        assert r.status_code == 404, r.text
        assert _code(r) == "RESOURCE_NOT_FOUND"
        assert not _arquivos(upload_root)
    asyncio.run(_client(a3_db, op))


def test_documento_inexistente_responde_404(a3_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        r = await _anexar(client, h, _new_id())
        assert r.status_code == 404, r.text
        assert _code(r) == "RESOURCE_NOT_FOUND"
    asyncio.run(_client(a3_db, op))


def test_platform_superuser_nao_anexa(a3_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        platform = await _create_platform_user(db)
        await db.commit()
        r = await _anexar(client, _headers(platform, scope="global"), doc["id"])
        assert r.status_code == 403, r.text
    asyncio.run(_client(a3_db, op))


# ---- Path traversal: a regressao que originou a Issue ----

@pytest.mark.parametrize("nome", ["../app.db", "../../app.db", "..\\..\\app.db", "/etc/passwd", "sub/dir/x.pdf"])
def test_filename_malicioso_nao_escapa_do_upload_root(a3_db, upload_root, nome):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        r = await _anexar(client, h, doc["id"], conteudo=PDF, nome=nome)
        assert r.status_code == 201, r.text

        # O nome vira rotulo sanitizado, nunca componente de caminho.
        assert "/" not in r.json()["arquivo_nome_original"]
        assert "\\" not in r.json()["arquivo_nome_original"]

        arquivos = _arquivos(upload_root)
        assert len(arquivos) == 1
        # Containment: o unico arquivo gravado esta sob UPLOAD_ROOT.
        assert upload_root in arquivos[0].parents
        # E o nome do arquivo em disco e o uuid gerado, nao o enviado.
        assert "app.db" not in arquivos[0].name
        assert "passwd" not in arquivos[0].name

        stored = await _reload(db, doc["id"])
        assert ".." not in stored.arquivo
        assert not os.path.isabs(stored.arquivo)
    asyncio.run(_client(a3_db, op))


def test_chave_de_storage_usa_tenant_documento_e_uuid(a3_db, upload_root):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        assert (await _anexar(client, h, doc["id"])).status_code == 201
        stored = await _reload(db, doc["id"])
        partes = stored.arquivo.split("/")
        assert partes[0] == tenant.id
        assert partes[1] == doc["id"]
        assert partes[2].endswith(".pdf") and len(partes) == 3
    asyncio.run(_client(a3_db, op))


# ---- Conteudo, extensao e limites ----

def test_extensao_e_mime_mentirosos_nao_bastam(a3_db, upload_root):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        r = await _anexar(client, h, doc["id"], conteudo=TEXTO, nome="documento.pdf", mime="application/pdf")
        assert r.status_code == 422, r.text
        assert _code(r) == "ARQUIVO_TIPO_NAO_PERMITIDO"
        assert (await _reload(db, doc["id"])).arquivo is None
        assert not _arquivos(upload_root)
    asyncio.run(_client(a3_db, op))


def test_arquivo_vazio_recusado(a3_db, upload_root):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        r = await _anexar(client, h, doc["id"], conteudo=b"", nome="vazio.pdf")
        assert r.status_code == 422, r.text
        assert _code(r) == "ARQUIVO_VAZIO"
        assert (await _reload(db, doc["id"])).arquivo is None
        assert not _arquivos(upload_root)
    asyncio.run(_client(a3_db, op))


def test_arquivo_acima_do_limite_recusado(a3_db, upload_root):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        grande = PDF + b"\x00" * (main.ARQUIVO_MAX_BYTES + 1)
        r = await _anexar(client, h, doc["id"], conteudo=grande, nome="grande.pdf")
        assert r.status_code == 413, r.text
        assert _code(r) == "ARQUIVO_MUITO_GRANDE"
        assert (await _reload(db, doc["id"])).arquivo is None
        assert not _arquivos(upload_root)
    asyncio.run(_client(a3_db, op))


def test_falha_nao_deixa_temporario(a3_db, upload_root):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        for conteudo, nome in ((TEXTO, "a.pdf"), (b"", "b.pdf"), (PDF + b"\x00" * (main.ARQUIVO_MAX_BYTES + 1), "c.pdf")):
            await _anexar(client, h, doc["id"], conteudo=conteudo, nome=nome)
        assert not _temporarios(upload_root)
        assert not _arquivos(upload_root)
    asyncio.run(_client(a3_db, op))


# ---- Unicidade e imutabilidade ----

def test_segundo_anexo_recusado(a3_db, upload_root):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        assert (await _anexar(client, h, doc["id"], conteudo=PDF)).status_code == 201
        primeiro = (await _reload(db, doc["id"])).arquivo

        r = await _anexar(client, h, doc["id"], conteudo=PNG, nome="outro.png")
        assert r.status_code == 409, r.text
        assert _code(r) == "DOCUMENTO_ARQUIVO_JA_ANEXADO"

        stored = await _reload(db, doc["id"])
        assert stored.arquivo == primeiro
        assert stored.arquivo_mime == "application/pdf"
        # Nada foi sobrescrito nem acrescentado em disco.
        arquivos = _arquivos(upload_root)
        assert len(arquivos) == 1 and arquivos[0].read_bytes() == PDF
        assert await _audits(db, doc["id"]) == 1
    asyncio.run(_client(a3_db, op))


def test_anexo_apos_validacao_recusado(a3_db, upload_root):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3 | {"documentos:validar"})
        doc = await _doc(client, h, resident.id)
        assert (await client.post(f"/api/documentos/{doc['id']}/validar", headers=h, json={})).status_code == 200

        r = await _anexar(client, h, doc["id"])
        assert r.status_code == 409, r.text
        assert _code(r) == "DOCUMENTO_JA_VALIDADO"
        assert (await _reload(db, doc["id"])).arquivo is None
        assert not _arquivos(upload_root)
    asyncio.run(_client(a3_db, op))


def test_dois_anexos_concorrentes_produzem_um_unico_arquivo(a3_db, upload_root):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        respostas = await asyncio.gather(
            _anexar(client, h, doc["id"], conteudo=PDF, nome="a.pdf"),
            _anexar(client, h, doc["id"], conteudo=PNG, nome="b.png"),
            return_exceptions=True,
        )
        codigos = [r.status_code for r in respostas if not isinstance(r, BaseException)]
        assert codigos.count(201) == 1, respostas
        # O invariante que importa: um anexo, um arquivo, uma auditoria.
        stored = await _reload(db, doc["id"])
        assert stored.arquivo is not None
        assert len(_arquivos(upload_root)) == 1
        assert not _temporarios(upload_root)
        assert await _audits(db, doc["id"]) == 1
    asyncio.run(_client(a3_db, op))


# ---- Consistencia filesystem <-> DB na janela de commit ----

def test_commit_ambiguo_preserva_arquivo_promovido(a3_db, upload_root, monkeypatch):
    """Excecao no commit NAO prova que o servidor deixou de efetivar.

    Apagar o arquivo nesse caso produziria registro commitado apontando para
    arquivo inexistente — e, como A3 aceita um unico anexo, sem caminho de
    correcao pela API. Orfao recuperavel e o mal menor.
    """
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)

        commit_real = AsyncSession.commit
        armado = {"on": True}

        async def commit_ambiguo(self):
            if armado["on"]:
                armado["on"] = False
                # Conexao cai durante o COMMIT: o resultado e indeterminado.
                raise OperationalError("COMMIT", {}, Exception("connection reset during commit"))
            return await commit_real(self)

        monkeypatch.setattr(AsyncSession, "commit", commit_ambiguo)
        try:
            # A excecao precisa continuar visivel: mascara-la esconderia do
            # operador que o estado ficou indeterminado.
            with pytest.raises(Exception) as excinfo:
                await _anexar(client, h, doc["id"], conteudo=PDF, nome="rg.pdf")
            assert "commit" in str(excinfo.value).lower()
        finally:
            monkeypatch.undo()

        finais = [p for p in _arquivos(upload_root) if not p.name.startswith(".tmp-")]
        assert len(finais) == 1, finais
        assert finais[0].read_bytes() == PDF
        assert not _temporarios(upload_root)
    asyncio.run(_client(a3_db, op))


def test_falha_no_replace_nao_deixa_arquivo_nem_temporario(a3_db, upload_root, monkeypatch):
    """Antes da tentativa de commit o cleanup normal continua valendo."""
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)

        def replace_falha(origem, destino):
            raise OSError("falha simulada na promocao atomica")

        monkeypatch.setattr(main.os, "replace", replace_falha)
        try:
            with pytest.raises(OSError):
                await _anexar(client, h, doc["id"])
        finally:
            monkeypatch.undo()

        assert not _arquivos(upload_root)
        assert not _temporarios(upload_root)
        assert (await _reload(db, doc["id"])).arquivo is None
    asyncio.run(_client(a3_db, op))


# ---- Download ----

def test_download_autorizado_devolve_conteudo_e_mime_do_backend(a3_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        assert (await _anexar(client, h, doc["id"], conteudo=PNG, nome="foto.png", mime="text/plain")).status_code == 201

        r = await client.get(f"/api/documentos/{doc['id']}/arquivo", headers=h)
        assert r.status_code == 200, r.text
        assert r.content == PNG
        assert r.headers["content-type"].startswith("image/png")
        assert "foto.png" in r.headers.get("content-disposition", "")
    asyncio.run(_client(a3_db, op))


def test_download_cross_tenant_responde_404(a3_db):
    async def op(client, db):
        tenant_a, _, resident_a, _, ha = await _setup(db, permissions=A3)
        doc = await _doc(client, ha, resident_a.id)
        assert (await _anexar(client, ha, doc["id"])).status_code == 201
        _, _, _, _, hb = await _setup(db, permissions=A3)
        r = await client.get(f"/api/documentos/{doc['id']}/arquivo", headers=hb)
        assert r.status_code == 404, r.text
        assert _code(r) == "RESOURCE_NOT_FOUND"
    asyncio.run(_client(a3_db, op))


def test_download_sem_anexo_responde_404_explicito(a3_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        r = await client.get(f"/api/documentos/{doc['id']}/arquivo", headers=h)
        assert r.status_code == 404, r.text
        assert _code(r) == "DOCUMENTO_ARQUIVO_AUSENTE"
    asyncio.run(_client(a3_db, op))


def test_download_de_documento_inexistente_responde_404(a3_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        r = await client.get(f"/api/documentos/{_new_id()}/arquivo", headers=h)
        assert r.status_code == 404, r.text
        assert _code(r) == "RESOURCE_NOT_FOUND"
    asyncio.run(_client(a3_db, op))


def test_download_sem_documentos_ler_recebe_403(a3_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        assert (await _anexar(client, h, doc["id"])).status_code == 201
        _, _, _, _, sem = await _setup(db, permissions=A3 - {"documentos:ler"})
        r = await client.get(f"/api/documentos/{doc['id']}/arquivo", headers=sem)
        assert r.status_code == 403, r.text
    asyncio.run(_client(a3_db, op))


def test_arquivo_sumido_do_disco_nao_vira_500(a3_db, upload_root):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        assert (await _anexar(client, h, doc["id"])).status_code == 201
        for arquivo in _arquivos(upload_root):
            arquivo.unlink()
        r = await client.get(f"/api/documentos/{doc['id']}/arquivo", headers=h)
        assert r.status_code == 404, r.text
        assert _code(r) == "DOCUMENTO_ARQUIVO_AUSENTE"
    asyncio.run(_client(a3_db, op))


# ---- Contrato: cliente nao define a chave de storage ----

def test_create_ignora_arquivo_enviado_pelo_cliente(a3_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        r = await client.post(
            "/api/documentos/",
            headers=h,
            json={"residente_id": resident.id, "tipo": "RG", "arquivo": "../../app.db"},
        )
        assert r.status_code == 201, r.text
        stored = await _reload(db, r.json()["id"])
        assert stored.arquivo is None
    asyncio.run(_client(a3_db, op))


def test_update_ignora_arquivo_enviado_pelo_cliente(a3_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        assert (await _anexar(client, h, doc["id"])).status_code == 201
        chave = (await _reload(db, doc["id"])).arquivo

        r = await client.put(
            f"/api/documentos/{doc['id']}",
            headers=h,
            json={"numero": "123", "arquivo": "../../app.db"},
        )
        assert r.status_code == 200, r.text
        stored = await _reload(db, doc["id"])
        assert stored.arquivo == chave
        assert stored.numero == "123"
    asyncio.run(_client(a3_db, op))


def test_rota_generica_de_upload_nao_existe_mais(a3_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        r = await client.post(
            f"/api/uploads/{tenant.id}",
            headers=h,
            files={"file": ("x.pdf", PDF, "application/pdf")},
        )
        assert r.status_code == 404, r.text
    asyncio.run(_client(a3_db, op))


# ---- Migration 018 ----

def test_018_cria_permissao_colunas_e_grant(pre018_db):
    async def antes(connection):
        assert (await connection.execute(text("SELECT count(*) FROM permissoes WHERE chave = 'documentos:anexar'"))).scalar_one() == 0

    async def depois(connection):
        assert (await connection.execute(text("SELECT count(*) FROM permissoes WHERE chave = 'documentos:anexar'"))).scalar_one() == 1
        template = (await connection.execute(text(
            "SELECT id FROM perfis WHERE chave = 'ilpi_admin' AND ilpi_id IS NULL"))).scalar_one()
        permissao = (await connection.execute(text(
            "SELECT id FROM permissoes WHERE chave = 'documentos:anexar'"))).scalar_one()
        assert (await connection.execute(text(
            "SELECT count(*) FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"
        ), {"p": template, "m": permissao})).scalar_one() == 1
        # platform_superuser nunca recebe grant clinico/documental.
        superuser = (await connection.execute(text(
            "SELECT id FROM perfis WHERE chave = 'platform_superuser' AND ilpi_id IS NULL"))).scalar_one()
        assert (await connection.execute(text(
            "SELECT count(*) FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"
        ), {"p": superuser, "m": permissao})).scalar_one() == 0
        for coluna in ("arquivo_nome_original", "arquivo_mime", "arquivo_tamanho", "arquivo_hash", "anexado_por", "anexado_em"):
            await connection.execute(text(f"SELECT {coluna} FROM documentos"))

    asyncio.run(_conferir(pre018_db, antes))
    _migrate(pre018_db, target=HEAD)
    asyncio.run(_conferir(pre018_db, depois))


def test_018_downgrade_remove_permissao_e_colunas(pre018_db):
    _migrate(pre018_db, target=HEAD)
    _migrate(pre018_db, target=PRE_018_HEAD, command="downgrade")

    async def depois(connection):
        assert (await connection.execute(text("SELECT count(*) FROM permissoes WHERE chave = 'documentos:anexar'"))).scalar_one() == 0
        assert (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == PRE_018_HEAD
        # Introspeccao em vez de SELECT que falha de proposito: no PostgreSQL o
        # primeiro erro aborta a transacao e derruba as consultas seguintes,
        # enquanto no SQLite cada statement e independente. Sondar por excecao
        # acoplaria o teste a semantica de um backend so.
        colunas = await connection.run_sync(
            lambda sync_conn: {c["name"] for c in sa_inspect(sync_conn).get_columns("documentos")}
        )
        assert colunas.isdisjoint({"arquivo_nome_original", "arquivo_mime", "arquivo_tamanho",
                                   "arquivo_hash", "anexado_por", "anexado_em"})
        # A coluna historica `arquivo` permanece: ela e anterior a 018.
        assert "arquivo" in colunas
    asyncio.run(_conferir(pre018_db, depois))


def test_018_recusa_downgrade_com_evidencia_de_anexo(a3_db, upload_root):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db, permissions=A3)
        doc = await _doc(client, h, resident.id)
        assert (await _anexar(client, h, doc["id"])).status_code == 201
    asyncio.run(_client(a3_db, op))

    resultado = _migrate(a3_db, target=PRE_018_HEAD, command="downgrade", success=False)
    assert "evidencia de anexo" in (resultado.stdout + resultado.stderr)

    async def intacto(connection):
        # Recusa preserva estado: revisao e evidencia continuam onde estavam.
        assert (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == HEAD
        assert (await connection.execute(text("SELECT count(*) FROM documentos WHERE anexado_por IS NOT NULL"))).scalar_one() == 1
    asyncio.run(_conferir(a3_db, intacto))


async def _conferir(ref, verificacao):
    engine = _engine(ref)
    try:
        async with engine.connect() as connection:
            await verificacao(connection)
    finally:
        await engine.dispose()

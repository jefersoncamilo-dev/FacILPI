"""#271 Portal da familia: liberar/bloquear, papel sem grant clinico, tenant e auditoria.

Banco SQLite descartavel em tmp_path; contas e senhas sinteticas geradas no teste.
"""

import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from .banco_modelo import migrar_de_modelo
from .sessao_teste import abrir_sessao
from .test_d2_rotina import _headers
from .test_d3_admissao import _client
from .test_d3_admissao_migration import _ref, _url
from .test_operacao_escala import _ilpi_com_area, _template, _usuario
from src.application.auth import verify_password
from src.application.security import GLOBAL_SCOPE, _permission_is_allowed
from src.infrastructure import models as m


@pytest.fixture
def banco(tmp_path):
    ref = _ref(SimpleNamespace(param="sqlite"), tmp_path)
    migrar_de_modelo(_url(ref), "head")
    return ref


async def _cenario(client, db):
    a, _, _, _ = await _ilpi_com_area(client, db)
    b, _, _, _ = await _ilpi_com_area(client, db, nome="Outra")
    ra = m.Residente(instituicao_id=a.id, nome="Dona Sintetica", situacao="Ativo", data_nascimento=date(1940, 1, 1))
    ra2 = m.Residente(instituicao_id=a.id, nome="Seu Outro", situacao="Ativo", data_nascimento=date(1941, 1, 1))
    rb = m.Residente(instituicao_id=b.id, nome="Residente B", situacao="Ativo", data_nascimento=date(1942, 1, 1))
    db.add_all([ra, ra2, rb])
    await db.flush()
    fa = m.Familiar(residente_id=ra.id, ilpi_id=a.id, nome="Filha Sintetica", email="filha@example.com")
    fb = m.Familiar(residente_id=rb.id, ilpi_id=b.id, nome="Familiar B", email="fb@example.com")
    db.add_all([fa, fb])
    await db.commit()
    adm, ha = await _usuario(db, a, await _template(db, "ilpi_admin"), "ilpi_admin", "Adm Sint")
    return SimpleNamespace(a=a, b=b, ra=ra.id, ra2=ra2.id, rb=rb.id, fa=fa.id, fb=fb.id, adm=adm, ha=ha)


async def _sessao_familiar(db, c):
    familiar = await db.scalar(select(m.Familiar).where(m.Familiar.id == c.fa))
    user = await db.get(m.User, familiar.usuario_id)
    await abrir_sessao(db, user)
    await db.commit()
    return user, _headers(user, ilpi_id=c.a.id)


def test_liberar_cria_conta_com_senha_unica_e_troca_obrigatoria(banco):
    async def op(client, db):
        c = await _cenario(client, db)
        _, hcuid = await _usuario(db, c.a, await _template(db, "cuidador"), "cuidador", "Cuid Sint")
        assert (await client.post(f"/api/familiares/{c.fa}/portal", headers=hcuid, json={"ativo": True})).status_code == 403
        assert (await client.post(f"/api/familiares/{c.fb}/portal", headers=c.ha, json={"ativo": True})).status_code == 404

        r = await client.post(f"/api/familiares/{c.fa}/portal", headers=c.ha, json={"ativo": True})
        assert r.status_code == 200, r.text
        senha = r.json()["senha_provisoria"]
        assert r.json()["portal_ativo"] is True and len(senha) >= 12
        familiar = await db.scalar(select(m.Familiar).where(m.Familiar.id == c.fa))
        await db.refresh(familiar)
        user = await db.get(m.User, familiar.usuario_id)
        await db.refresh(user)
        assert user.email == "filha@example.com" and user.exige_troca_senha is True
        assert verify_password(senha, user.password_hash)

        # Cada liberacao gera outra senha: nao existe senha padrao.
        r2 = await client.post(f"/api/familiares/{c.fa}/portal", headers=c.ha, json={"ativo": True})
        assert r2.json()["senha_provisoria"] != senha

        # Sessao com troca pendente nao le nem o portal.
        await abrir_sessao(db, user)
        await db.commit()
        r = await client.get("/api/portal/resumo", headers=_headers(user, ilpi_id=c.a.id))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "FIRST_PASSWORD_CHANGE_REQUIRED"

        auditoria = (await db.scalars(select(m.Auditoria.acao).where(m.Auditoria.registro_id == c.fa))).all()
        assert auditoria.count("portal_familia.liberado") == 2
    asyncio.run(_client(banco, op))


def test_email_de_outra_conta_nao_e_reaproveitado(banco):
    async def op(client, db):
        c = await _cenario(client, db)
        familiar = await db.scalar(select(m.Familiar).where(m.Familiar.id == c.fa))
        familiar.email = c.adm.email
        await db.commit()
        assert (await client.post(f"/api/familiares/{c.fa}/portal", headers=c.ha, json={"ativo": True})).status_code == 409
    asyncio.run(_client(banco, op))


def test_familiar_ve_so_o_proprio_residente_e_nada_clinico(banco):
    async def op(client, db):
        c = await _cenario(client, db)
        assert (await client.post(f"/api/familiares/{c.fa}/portal", headers=c.ha, json={"ativo": True})).status_code == 200
        user, hf = await _sessao_familiar(db, c)
        user.exige_troca_senha = False
        agora = datetime.now(timezone.utc)
        db.add_all([
            m.AgendaEvento(ilpi_id=c.a.id, residente_id=c.ra, motivo="Consulta da Dona", inicio_em=agora + timedelta(days=2), autor_id=c.adm.id),
            m.AgendaEvento(ilpi_id=c.a.id, residente_id=c.ra2, motivo="Consulta do Outro", inicio_em=agora + timedelta(days=2), autor_id=c.adm.id),
            m.Mensalidade(ilpi_id=c.a.id, residente_id=c.ra, competencia="2030-01", valor_centavos=350000, vencimento=date(2030, 1, 10), autor_id=c.adm.id),
            m.Mensalidade(ilpi_id=c.a.id, residente_id=c.ra2, competencia="2030-01", valor_centavos=999, vencimento=date(2030, 1, 10), autor_id=c.adm.id),
        ])
        await db.commit()
        assert (await client.post("/api/portal/recados", headers=c.ha, json={"residente_id": c.ra, "texto": "Almoçou bem hoje"})).status_code == 201
        assert (await client.post("/api/portal/recados", headers=c.ha, json={"residente_id": c.ra2, "texto": "Recado de outro"})).status_code == 201
        assert (await client.post("/api/portal/recados", headers=c.ha, json={"residente_id": c.rb, "texto": "x"})).status_code == 404

        r = await client.get("/api/portal/resumo", headers=hf)
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["residente_nome"] == "Dona Sintetica"
        assert [e["motivo"] for e in corpo["agenda"]] == ["Consulta da Dona"]
        assert [x["valor_centavos"] for x in corpo["mensalidades"]] == [350000]
        assert [x["texto"] for x in corpo["recados"]] == ["Almoçou bem hoje"] and corpo["recados_hoje"] == 1

        # Papel sem grant clinico e sem acesso ao resto da API, nem de leitura.
        for rota in (f"/api/residentes/{c.ra}", "/api/residentes/", f"/api/residentes/{c.ra}/prontuario", "/api/agenda/",
                     "/api/financeiro/mensalidades", f"/api/pia/{c.ra}", "/api/dashboard/resumo", "/api/meu-plantao/",
                     "/api/intercorrencias/", "/api/familiares/", f"/api/portal/recados/{c.ra}"):
            assert (await client.get(rota, headers=hf)).status_code == 403, rota
        assert (await client.post("/api/portal/recados", headers=hf, json={"residente_id": c.ra, "texto": "x"})).status_code == 403
        perms = (await client.get("/api/auth/permissoes", headers=hf)).json()["permissoes"]
        assert perms == ["portal_familia:ler"]
    asyncio.run(_client(banco, op))


def test_bloquear_corta_sessao_aberta(banco):
    async def op(client, db):
        c = await _cenario(client, db)
        assert (await client.post(f"/api/familiares/{c.fa}/portal", headers=c.ha, json={"ativo": True})).status_code == 200
        user, hf = await _sessao_familiar(db, c)
        user.exige_troca_senha = False
        await db.commit()
        assert (await client.get("/api/portal/resumo", headers=hf)).status_code == 200

        r = await client.post(f"/api/familiares/{c.fa}/portal", headers=c.ha, json={"ativo": False})
        assert r.status_code == 200 and r.json()["portal_ativo"] is False and r.json()["senha_provisoria"] is None
        assert (await client.get("/api/portal/resumo", headers=hf)).status_code in (401, 403)
        assert await db.scalar(select(m.Auditoria.id).where(m.Auditoria.acao == "portal_familia.bloqueado",
                                                            m.Auditoria.usuario_id == c.adm.id))
        lista = (await client.get("/api/familiares/", headers=c.ha, params={"residente_id": c.ra})).json()
        assert [f["portal_ativo"] for f in lista] == [False]
    asyncio.run(_client(banco, op))


def test_plataforma_sem_acesso_ao_portal():
    ctx = SimpleNamespace(perfil=SimpleNamespace(chave="platform_superuser"), scope=GLOBAL_SCOPE, ilpi_situacao=None)
    for chave in ("portal_familia:ler", "portal_familia:publicar"):
        assert _permission_is_allowed(ctx, SimpleNamespace(chave=chave, modulo="portal_familia")) is False


def test_migration_036_ida_e_volta(tmp_path):
    import sqlite3

    from .test_n2_saida_residente import _alembic

    db = tmp_path / "m036.db"
    assert _alembic(db, ("upgrade", "head")).returncode == 0
    with sqlite3.connect(db) as con:
        chaves = {r[0] for r in con.execute(
            "SELECT p.chave FROM perfil_permissoes pp JOIN permissoes p ON p.id = pp.permissao_id "
            "JOIN perfis f ON f.id = pp.perfil_id WHERE f.chave = 'familiar_portal'")}
        assert chaves == {"portal_familia:ler"}
    r = _alembic(db, ("downgrade", "035_complementares"))
    assert r.returncode == 0, r.stdout + r.stderr
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM permissoes WHERE chave LIKE 'portal_familia:%'").fetchone()[0] == 0
        assert "usuario_id" not in {r[1] for r in con.execute("PRAGMA table_info(familiares)")}

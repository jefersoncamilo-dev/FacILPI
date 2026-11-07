"""#275: GET /api/dashboard/intercorrencias-semanais — historico por semana.

Reaproveita a infraestrutura descartavel do teste do resumo (UX-02).
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.application.security import ILPI_CONTEXT_REQUIRED, PERMISSION_DENIED
from src.infrastructure import models as m
from tests.sessao_teste import abrir_sessao, token_de
from tests.test_ux02_dashboard_resumo import _id, _ilpi, _residentes, _usuario, _with_client, ux02_db  # noqa: F401

SP = ZoneInfo("America/Sao_Paulo")
URL = "/api/dashboard/intercorrencias-semanais"


def _segunda_atual() -> date:
    hoje = datetime.now(SP).date()
    return hoje - timedelta(days=hoje.weekday())


def _get(client, user, ilpi, **params):
    return client.get(
        URL, params=params,
        headers={"Authorization": f"Bearer {token_de(user)}", "X-Scope": "ilpi", "X-ILPI-ID": ilpi.id},
    )


def _evento(ilpi, residente, quando: datetime, situacao: str | None = "aberta") -> m.Intercorrencia:
    return m.Intercorrencia(id=_id(), ilpi_id=ilpi.id, residente_id=residente.id, tipo="queda",
                            situacao=situacao, ocorrido_em=quando)


def test_agrupa_por_semana_em_qualquer_situacao_e_preenche_vazias(ux02_db):
    async def scenario(client, db):
        ilpi = await _ilpi(db, "ILPI 275")
        user = await _usuario(db, ilpi, {"intercorrencias:ler"})
        [r] = await _residentes(db, ilpi, 1)
        s = _segunda_atual()
        segunda = datetime(s.year, s.month, s.day, 12, tzinfo=SP)
        db.add_all([
            _evento(ilpi, r, segunda),
            _evento(ilpi, r, segunda, "encerrada"),
            _evento(ilpi, r, segunda, "Aberta"),
            _evento(ilpi, r, segunda - timedelta(weeks=2)),
            _evento(ilpi, r, segunda - timedelta(weeks=8)),  # fora da janela de 8
            _evento(ilpi, r, segunda + timedelta(weeks=1)),  # futuro nao conta
        ])
        await db.commit()

        body = (await _get(client, user, ilpi, semanas=8)).json()

        assert body["fuso"] == "America/Sao_Paulo"
        assert len(body["semanas"]) == 8
        assert body["semanas"][-1] == {"inicio": s.isoformat(), "total": 3}
        assert [x["total"] for x in body["semanas"]] == [0, 0, 0, 0, 0, 1, 0, 3]

        doze = (await _get(client, user, ilpi)).json()["semanas"]
        assert len(doze) == 12
        assert sum(x["total"] for x in doze) == 5

    asyncio.run(_with_client(ux02_db, scenario))


def test_virada_da_semana_segue_o_fuso_da_ilpi(ux02_db):
    async def scenario(client, db):
        ilpi = await _ilpi(db, "ILPI 275 fuso")
        user = await _usuario(db, ilpi, {"intercorrencias:ler"})
        [r] = await _residentes(db, ilpi, 1)
        s = _segunda_atual()
        meia_noite = datetime(s.year, s.month, s.day, tzinfo=SP).astimezone(timezone.utc)
        # 1 min antes da meia-noite local: em UTC ja e segunda, mas na ILPI ainda e domingo.
        db.add_all([_evento(ilpi, r, meia_noite - timedelta(minutes=1)), _evento(ilpi, r, meia_noite)])
        await db.commit()

        totais = [x["total"] for x in (await _get(client, user, ilpi, semanas=8)).json()["semanas"]]

        assert totais[-2:] == [1, 1]

    asyncio.run(_with_client(ux02_db, scenario))


def test_outra_ilpi_nao_entra(ux02_db):
    async def scenario(client, db):
        ilpi = await _ilpi(db, "ILPI 275 A")
        outra = await _ilpi(db, "ILPI 275 B")
        user = await _usuario(db, ilpi, {"intercorrencias:ler"})
        [r] = await _residentes(db, outra, 1)
        db.add(_evento(outra, r, datetime.now(timezone.utc)))
        await db.commit()

        body = (await _get(client, user, ilpi)).json()

        assert sum(x["total"] for x in body["semanas"]) == 0

    asyncio.run(_with_client(ux02_db, scenario))


def test_contexto_global_de_superusuario_e_recusado(ux02_db):
    async def scenario(client, db):
        user = m.User(id=_id(), nome="Plataforma", email=f"t275-plat-{_id()}@example.com",
                      password_hash="fixture", ativo=True, is_superuser=True)
        perfil = (await db.execute(select(m.Perfil).where(
            m.Perfil.chave == "platform_superuser", m.Perfil.ilpi_id.is_(None)))).scalar_one()
        db.add(user)
        await db.flush()
        db.add(m.UsuarioIlpiPerfil(id=_id(), usuario_id=user.id, perfil_id=perfil.id, ilpi_id=None, situacao="ativo",
                                   data_inicial=datetime.now(timezone.utc) - timedelta(minutes=1)))
        await db.flush()
        await abrir_sessao(db, user)
        await db.commit()

        resposta = await client.get(URL, headers={"Authorization": f"Bearer {token_de(user)}", "X-Scope": "global"})

        assert resposta.status_code == 403, resposta.text
        assert resposta.json()["detail"]["code"] == ILPI_CONTEXT_REQUIRED

    asyncio.run(_with_client(ux02_db, scenario))


def test_exige_permissao_sessao_e_janela_valida(ux02_db):
    async def scenario(client, db):
        ilpi = await _ilpi(db, "ILPI 275 RBAC")
        sem = await _usuario(db, ilpi, {"residentes:ler"})
        com = await _usuario(db, ilpi, {"intercorrencias:ler"})
        await db.commit()

        negado = await _get(client, sem, ilpi)
        assert negado.status_code == 403
        assert negado.json()["detail"]["code"] == PERMISSION_DENIED
        assert (await client.get(URL)).status_code == 401
        assert (await _get(client, com, ilpi, semanas=5)).status_code == 422

    asyncio.run(_with_client(ux02_db, scenario))

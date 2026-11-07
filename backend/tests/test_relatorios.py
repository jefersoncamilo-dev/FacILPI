"""Relatorio resumido: tenant da sessao, secoes por permissao. Banco descartavel."""

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from .banco_modelo import migrar_de_modelo
from .test_d3_admissao import _client
from .test_d3_admissao_migration import _ref, _url
from .test_operacao_escala import _ilpi_com_area, _template, _usuario
from src.infrastructure import models as m

P = {"de": "2030-01-01", "ate": "2030-01-31"}


@pytest.fixture
def banco(tmp_path):
    ref = _ref(SimpleNamespace(param="sqlite"), tmp_path)
    migrar_de_modelo(_url(ref), "head")
    return ref


def test_tenant_secoes_e_periodo(banco):
    async def op(client, db):
        ilpi, _, _, _ = await _ilpi_com_area(client, db)
        outra, _, _, _ = await _ilpi_com_area(client, db, nome="Outra")
        rs = {}
        for inst in (ilpi, outra):
            r = m.Residente(instituicao_id=inst.id, nome="Residente Sintetico", situacao="Ativo", data_nascimento=date(1940, 1, 1))
            db.add(r)
            rs[inst.id] = r
        await db.flush()
        no_periodo = datetime(2030, 1, 10, 12, tzinfo=timezone.utc)
        fora = datetime(2030, 2, 1, 2, 30, tzinfo=timezone.utc)  # ainda 31/01 em Sao Paulo
        muito_fora = datetime(2030, 2, 1, 12, tzinfo=timezone.utc)
        for quando in (no_periodo, fora, muito_fora):
            db.add(m.Intercorrencia(ilpi_id=ilpi.id, residente_id=rs[ilpi.id].id, tipo="queda", gravidade="leve", ocorrido_em=quando))
        db.add(m.Intercorrencia(ilpi_id=outra.id, residente_id=rs[outra.id].id, tipo="queda", gravidade="grave", ocorrido_em=no_periodo))
        await db.commit()

        _, hrt = await _usuario(db, ilpi, await _template(db, "responsavel_tecnico"), "responsavel_tecnico", "RT Sintetica")
        c = await client.get("/api/relatorios/resumo", headers=hrt, params={**P, "ilpi_id": outra.id})
        assert c.status_code == 200, c.text
        corpo = c.json()
        assert corpo["intercorrencias_por_gravidade"] == [{"chave": "leve", "total": 2}]
        assert corpo["residentes_por_situacao"] == [{"chave": "Ativo", "total": 1}]

        # Cuidador nao le dose: a secao nao vem.
        _, hc = await _usuario(db, ilpi, await _template(db, "cuidador"), "cuidador", "Ana Sintetica")
        cu = await client.get("/api/relatorios/resumo", headers=hc, params=P)
        assert cu.status_code == 200 and cu.json()["administracoes_por_resultado"] is None

        # Sem nenhuma fonte: 403.
        _, hn = await _usuario(db, ilpi, {"escala:ler"}, "so_escala", "Sem Fonte")
        assert (await client.get("/api/relatorios/resumo", headers=hn, params=P)).status_code == 403
        assert (await client.get("/api/relatorios/resumo", headers=hrt, params={"de": "2030-02-01", "ate": "2030-01-01"})).status_code == 422
    asyncio.run(_client(banco, op))

"""UX-NAV-5 (#302): mapa da rotina do turno — tenant, RBAC e situações das células.

Somente bancos descartaveis (SQLite em tmp_path; PostgreSQL via D3_TEST_POSTGRES_URL).
"""

import asyncio
from datetime import timedelta
from zoneinfo import ZoneInfo

from .test_alertas_gestor import _agora
from .test_alertas_operacionais import _institucional
from .test_d2_rotina import _create_ilpi_user, _headers, _new_id, _new_institution
from .test_d3_admissao import _client
from .test_operacao_escala import _ok
from .test_passagem_plantao import _cenario, passagem_db  # noqa: F401 (fixture)
from src.infrastructure import models as m

URL = "/api/plantao/mapa"


def _run(ref, operation):
    asyncio.run(_client(ref, operation))


def _turno_de(instante):
    local = instante.astimezone(ZoneInfo("America/Sao_Paulo"))
    if local.hour < 7:
        return (local.date() - timedelta(days=1)).isoformat(), "noite"
    return local.date().isoformat(), "manha" if local.hour < 13 else "tarde" if local.hour < 19 else "noite"


def test_mapa_mostra_situacoes_do_tenant_e_respeita_rbac(passagem_db):
    async def op(client, db):
        ilpi, hg, _, x = await _cenario(client, db)
        _, h_enf, enf = await _institucional(db, ilpi, "enfermagem")
        dia, turno = _turno_de(x["ocorrencia"].previsto_em)
        params = {"dia": dia, "turno": turno}

        mapa = await _ok(await client.get(URL, headers=h_enf, params=params))
        nomes = {r["nome"]: r for r in mapa["residentes"]}
        assert {"Hilda Sintetica", "Rita Sintetica", "Joao Sintetico"} <= set(nomes)
        assert nomes["Rita Sintetica"]["ala"] == "Ala B" and nomes["Joao Sintetico"]["ala"] is None
        celula = next(i for i in mapa["itens"] if i["registro_id"] == x["ocorrencia"].id)
        assert celula["situacao"] == "atrasado" and celula["residente_id"] == x["rita"].id

        # Situação vem do registro existente: execução vigente = concluído; recusa = ressalva.
        oc = x["ocorrencia"]
        execucao = m.ExecucaoCuidado(id=_new_id(), ilpi_id=ilpi.id, residente_id=oc.residente_id, programacao_id=oc.programacao_id,
                                     ocorrencia_id=oc.id, resultado="recusada", justificativa="Recusou", ocorrido_em=_agora(),
                                     executor_id=enf.id)
        db.add(execucao)
        await db.commit()
        mapa = await _ok(await client.get(URL, headers=h_enf, params=params))
        assert next(i for i in mapa["itens"] if i["registro_id"] == oc.id)["situacao"] == "ressalva"
        execucao.estornado_em, execucao.estornado_por, execucao.motivo_estorno = _agora(), enf.id, "Engano"
        db.add(m.ExecucaoCuidado(id=_new_id(), ilpi_id=ilpi.id, residente_id=oc.residente_id, programacao_id=oc.programacao_id,
                                 ocorrencia_id=oc.id, resultado="executada", ocorrido_em=_agora(), executor_id=enf.id,
                                 substitui_id=execucao.id))
        await db.commit()
        mapa = await _ok(await client.get(URL, headers=h_enf, params=params))
        assert next(i for i in mapa["itens"] if i["registro_id"] == oc.id)["situacao"] == "concluido"

        # Outro tenant não vê nenhum residente nem item desta ILPI.
        outra = _new_institution("Outra ILPI Sintetica")
        alheio = await _create_ilpi_user(db, outra, profile_key="alheio", nome="Alheio Sintetico",
                                         permissions={"plantao:ler", "residentes:ler", "administracoes:ler"})
        await db.commit()
        mapa = await _ok(await client.get(URL, headers=_headers(alheio, ilpi_id=outra.id), params=params))
        assert mapa["residentes"] == [] and mapa["itens"] == []
        # Pedir o X-ILPI-ID de outra ILPI sem vínculo não abre nada.
        assert (await client.get(URL, headers=_headers(alheio, ilpi_id=ilpi.id), params=params)).status_code in (401, 403, 404)

        # RBAC: sem plantao:ler, ou sem residentes:ler, a tela é negada; sem medicação, doses somem.
        for chave, perms in (("sem_plantao", {"residentes:ler"}), ("sem_residentes", {"plantao:ler"})):
            u = await _create_ilpi_user(db, ilpi, profile_key=chave, nome=f"{chave} sintetico", permissions=perms)
            await db.commit()
            assert (await client.get(URL, headers=_headers(u, ilpi_id=ilpi.id), params=params)).status_code == 403
        u = await _create_ilpi_user(db, ilpi, profile_key="sem_med", nome="Sem Med Sintetico", permissions={"plantao:ler", "residentes:ler"})
        await db.commit()
        mapa = await _ok(await client.get(URL, headers=_headers(u, ilpi_id=ilpi.id), params=params))
        assert mapa["ve_medicacao"] is False and all(i["origem"] == "cuidado" for i in mapa["itens"])

        assert (await client.get(URL, headers=h_enf, params={"turno": "madrugada"})).status_code == 422
    _run(passagem_db, op)

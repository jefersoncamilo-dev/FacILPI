"""#126: Meu Plantao como destino operacional — agregador por tenant, RBAC e responsabilidade.

Somente bancos descartaveis (SQLite em tmp_path; PostgreSQL via D3_TEST_POSTGRES_URL).
"""

import asyncio
from datetime import timedelta




from .test_alertas_gestor import _agora
from .test_alertas_operacionais import _institucional
from .test_d2_rotina import _create_ilpi_user, _headers, _new_id
from .test_d3_admissao import _client
from .test_escala_planejada import _funcionario_id
from .test_operacao_escala import _ok
from .test_passagem_plantao import URL as PASSAGENS, _cenario, passagem_db  # noqa: F401 (fixture)
from src.infrastructure import models as m

URL = "/api/meu-plantao/"


def _run(ref, operation):
    asyncio.run(_client(ref, operation))


def test_sem_plantao_nada_novo_aparece(passagem_db):
    async def op(client, db):
        ilpi, hg, ala_b, _ = await _cenario(client, db)
        _, h_ana, ana = await _institucional(db, ilpi, "cuidador")
        f_ana = await _funcionario_id(db, ana)
        # Escala de hoje e de amanha: so a de hoje pode ser iniciada, entao so ela aparece.
        hoje = await _ok(await client.post("/api/escala/previsto", headers=hg, json={
            "funcionario_id": f_ana, "area_id": ala_b["id"], "inicio_previsto": (_agora() - timedelta(hours=1)).isoformat(),
            "fim_previsto": (_agora() + timedelta(hours=11)).isoformat()}), 201)
        await _ok(await client.post("/api/escala/previsto", headers=hg, json={
            "funcionario_id": f_ana, "area_id": ala_b["id"], "inicio_previsto": (_agora() + timedelta(hours=30)).isoformat(),
            "fim_previsto": (_agora() + timedelta(hours=36)).isoformat()}), 201)
        antes = await _ok(await client.get("/api/plantao/", headers=h_ana))
        visao = await _ok(await client.get(URL, headers=h_ana))
        assert visao["plantao"] is None and visao["areas"] == []
        assert [e["id"] for e in visao["escalas_pendentes"]] == [hoje["id"]]
        for bloco in ("residentes", "prioridades", "atividades", "passagens_a_receber"):
            assert visao[bloco] is None, bloco
        # A projecao de sempre continua igual para quem nao esta de plantao.
        assert await _ok(await client.get("/api/plantao/", headers=h_ana)) == antes
    _run(passagem_db, op)


def test_com_plantao_recorta_pela_area_e_pelo_rbac(passagem_db):
    async def op(client, db):
        ilpi, hg, ala_b, x = await _cenario(client, db)
        _, h_ana, _ = await _institucional(db, ilpi, "cuidador")
        _, h_bruno, _ = await _institucional(db, ilpi, "enfermagem")
        # Plantao iniciado AGORA: o cuidado atrasado (15 min antes) foi herdado e tem de aparecer.
        plantao = await _ok(await client.post("/api/plantoes/iniciar", headers=h_ana, json={"area_ids": [ala_b["id"]]}), 201)
        # Intercorrencia leve de Rita aberta ha 30 h: vira alerta "atencao" (prolongada) e Rita segue em atencao.
        tosse = m.Intercorrencia(id=_new_id(), residente_id=x["rita"].id, ilpi_id=ilpi.id, tipo="Tosse persistente",
                                 gravidade="leve", situacao="aberta", ocorrido_em=_agora() - timedelta(hours=30))
        db.add(tosse)
        await db.commit()
        # Passagem do turno anterior (Bruno, sem area) aguardando.
        await _ok(await client.post(PASSAGENS + "/", headers=h_bruno, json={"observacoes": [{"categoria": "outro", "texto": "Plantão tranquilo"}]}), 201)

        visao = await _ok(await client.get(URL, headers=h_ana))
        assert visao["plantao"]["id"] == plantao["id"] and [a["nome"] for a in visao["areas"]] == ["Ala B"]
        residentes = {r["nome"]: r for r in visao["residentes"]}
        assert set(residentes) == {"Hilda Sintetica", "Rita Sintetica"}, "Joao nao esta na Ala B"
        assert residentes["Hilda Sintetica"]["em_atencao"] and residentes["Hilda Sintetica"]["local"] == "Ala B · Quarto 12 · Leito A"
        # Motivo sem repeticao: a queda grave ja e alerta; nao volta como "intercorrencia aberta".
        assert residentes["Hilda Sintetica"]["motivos"].count("Intercorrência aberta: Queda") == 0
        rita = residentes["Rita Sintetica"]
        assert rita["em_atencao"], rita
        assert sum("Tosse persistente" in motivo for motivo in rita["motivos"]) == 1, "motivo presente e sem repeticao"
        assert visao["residentes"][0]["em_atencao"], "em atencao primeiro"
        assert {p["residente_id"] for p in visao["prioridades"]} <= {x["hilda"].id, x["rita"].id}
        assert f"intercorrencia_grave_aberta:{x['grave'].id}" in {p["id"] for p in visao["prioridades"]}
        assert x["fora"].id not in {p["referencia_id"] for p in visao["prioridades"]}
        assert [a["registro_id"] for a in visao["atividades"]["atrasadas"]] == [x["ocorrencia"].id]
        assert visao["passagens_a_receber"] == 1

        # Assumir aparece em Meu Plantao (mesmo estado da central).
        await _ok(await client.post("/api/central-alertas/assumir", headers=h_ana,
                                    json={"alerta_id": f"intercorrencia_grave_aberta:{x['grave'].id}"}))
        visao = await _ok(await client.get(URL, headers=h_ana))
        grave = next(p for p in visao["prioridades"] if p["referencia_id"] == x["grave"].id)
        assert grave["estado"]["por_mim"] is True

        # Responsabilidade nao concede acesso: sem residentes/alertas/plantao:ler, os blocos ficam nulos.
        restrito = await _create_ilpi_user(db, ilpi, profile_key="so_turno", nome="Paulo Sintetico",
                                           permissions={"plantao:registrar", "escala:ler"})
        await db.commit()
        h_r = _headers(restrito, ilpi_id=ilpi.id)
        await _ok(await client.post("/api/plantoes/iniciar", headers=h_r, json={"area_ids": [ala_b["id"]]}), 201)
        visao = await _ok(await client.get(URL, headers=h_r))
        assert [a["nome"] for a in visao["areas"]] == ["Ala B"]
        for bloco in ("residentes", "prioridades", "atividades", "passagens_a_receber"):
            assert visao[bloco] is None, bloco
    _run(passagem_db, op)

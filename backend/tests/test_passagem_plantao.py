"""#125: passagem de plantao — parte automatica do servidor, observacoes curtas, recebimento.

Somente bancos descartaveis (SQLite em tmp_path; PostgreSQL via D3_TEST_POSTGRES_URL).
"""

import asyncio
import os
from datetime import timedelta

import pytest
from sqlalchemy import select, text, update

from .test_alertas_gestor import _agora
from .test_alertas_operacionais import _institucional
from .test_d2_rotina import _create_funcionario, _create_ilpi_user, _headers, _new_id, _prog_payload, _setup_pais_vigente
from .test_d3_admissao import _client
from .test_d3_admissao_migration import _migrate, _ref
from .test_operacao_escala import GESTOR, _ilpi_com_area, _ok
from src.infrastructure import models as m

HEAD = "027_passagem_plantao"
URL = "/api/passagens"


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def passagem_db(request, tmp_path):
    ref = _ref(request, tmp_path)
    _migrate(ref, target=HEAD)
    return ref


def _run(ref, operation):
    asyncio.run(_client(ref, operation))


async def _residente(db, ilpi_id, nome):
    r = m.Residente(id=_new_id(), instituicao_id=ilpi_id, nome=nome, situacao="Ativo",
                    data_nascimento=_agora().date().replace(year=1940))
    db.add(r)
    await db.flush()
    return r


async def _cenario(client, db):
    """Ala B com Hilda (intercorrencias, sem PAIS) e Rita (cuidado atrasado); Joao fora da area."""
    ilpi, gestor, hg, ala_b = await _ilpi_com_area(client, db)
    hilda, rita, joao = [await _residente(db, ilpi.id, n) for n in ("Hilda Sintetica", "Rita Sintetica", "Joao Sintetico")]
    await db.commit()
    for quarto_leito, residente in (("A", hilda), ("B", rita)):
        leito = await _ok(await client.post("/api/quartos_leitos/", headers=hg, json={"unidade": "Ala B", "quarto": "12", "leito": quarto_leito}), 201)
        await _ok(await client.post(f"/api/quartos_leitos/{leito['id']}/alocar", headers=hg, json={"residente_id": residente.id}))
        await _ok(await client.post(f"/api/escala/areas/{ala_b['id']}/leitos", headers=hg, json={"quarto_leito_id": leito["id"]}), 201)
    grave = m.Intercorrencia(id=_new_id(), residente_id=hilda.id, ilpi_id=ilpi.id, tipo="Queda", gravidade="grave",
                             situacao="aberta", ocorrido_em=_agora() - timedelta(minutes=30))
    leve = m.Intercorrencia(id=_new_id(), residente_id=hilda.id, ilpi_id=ilpi.id, tipo="Tosse", gravidade="leve",
                            situacao="aberta", ocorrido_em=_agora() - timedelta(minutes=20))
    fora = m.Intercorrencia(id=_new_id(), residente_id=joao.id, ilpi_id=ilpi.id, tipo="Febre", gravidade="grave",
                            situacao="aberta", ocorrido_em=_agora() - timedelta(minutes=10))
    db.add_all([grave, leve, fora])
    await db.commit()
    # Rita: PAIS vigente + programacao com uma ocorrencia ja atrasada (atividade nao concluida).
    gestor_pais = await _create_ilpi_user(db, ilpi, profile_key="pais", nome="Coordenadora PAIS", permissions={
        "residentes:ler", "planos_cuidados:ler", "planos_cuidados:criar", "planos_cuidados:atualizar",
        "planos_cuidados:revisar", "planos_cuidados:aprovar", "planos_cuidados:encerrar", "programacoes:ler",
        "programacoes:criar", "programacoes:atualizar", "programacoes:inativar", "ocorrencias:ler"})
    await db.commit()
    hp = _headers(gestor_pais, ilpi_id=ilpi.id)
    revisor = await _create_funcionario(db, ilpi)
    await db.commit()
    pais_id, intervencao_id = await _setup_pais_vigente(client, hp, rita.id, revisor.id)
    prog = await _ok(await client.post("/api/programacoes-cuidado/", headers=hp, json=_prog_payload(pais_id, intervencao_id, inicio_horas=-3)), 201)
    ocorrencia = (await db.scalars(select(m.OcorrenciaCuidado).where(
        m.OcorrenciaCuidado.programacao_id == prog["id"]).order_by(m.OcorrenciaCuidado.previsto_em))).first()
    await db.execute(update(m.OcorrenciaCuidado).where(m.OcorrenciaCuidado.id == ocorrencia.id)
                     .values(previsto_em=_agora() - timedelta(minutes=15)))
    await db.commit()
    return ilpi, hg, ala_b, dict(hilda=hilda, rita=rita, joao=joao, grave=grave, leve=leve, fora=fora, ocorrencia=ocorrencia)


def test_passar_e_receber_plantao(passagem_db):
    async def op(client, db):
        ilpi, hg, ala_b, x = await _cenario(client, db)
        _, h_ana, _ = await _institucional(db, ilpi, "cuidador")
        _, h_ju, _ = await _institucional(db, ilpi, "enfermagem")
        # Ana inicia o plantao AGORA na Ala B: o cuidado atrasado de antes (herdado) tambem passa adiante.
        await _ok(await client.post("/api/plantoes/iniciar", headers=h_ana, json={"area_ids": [ala_b["id"]]}), 201)

        previa = await _ok(await client.get(f"{URL}/previa", headers=h_ana))
        assert previa["area_nome"] == "Ala B", "sem area informada, vale a unica area pela qual Ana responde"
        itens = {(i["origem"], i["referencia_id"]) for i in previa["itens"]}
        assert ("alerta", x["grave"].id) in itens and ("intercorrencia", x["leve"].id) in itens
        assert ("atividade", x["ocorrencia"].id) in itens
        assert not {i for i in itens if i[1] == x["fora"].id}, "Joao nao esta na Ala B"
        assert not [i for i in previa["itens"] if i.get("regra") in ("cuidados_sem_registro", "doses_sem_registro")]
        assert ("intercorrencia", x["grave"].id) not in itens, "intercorrencia que ja e alerta nao se repete"

        assert (await client.post(URL + "/", headers=h_ana, json={"observacoes": [{"categoria": "outro", "texto": "x" * 281}]})).status_code == 422
        assert (await client.post(URL + "/", headers=h_ana, json={"observacoes": [{"categoria": "invalida", "texto": "Oi"}]})).status_code == 422
        [entregue] = await _ok(await client.post(URL + "/", headers=h_ana, json={
            "observacoes": [{"categoria": "comportamento", "residente_id": x["hilda"].id, "texto": "Agitada no fim da tarde"}],
            "encerrar_plantao": True}), 201)
        assert entregue["situacao"] == "entregue" and entregue["entregue_por_mim"] is True
        obs = [i for i in entregue["itens"] if i["origem"] == "observacao"]
        assert [(o["categoria"], o["texto"], o["residente_nome"]) for o in obs] == [("comportamento", "Agitada no fim da tarde", "Hilda Sintetica")]
        assert (await _ok(await client.get("/api/plantoes/atual", headers=h_ana)))["plantao"] is None, "encerrou o plantao"

        # A gravidade da queda e corrigida (o alerta muda de regra/some), mas a intercorrencia segue aberta.
        await db.execute(update(m.Intercorrencia).where(m.Intercorrencia.id == x["grave"].id).values(gravidade="leve"))
        await db.commit()
        [pendente] = await _ok(await client.get(URL + "/", headers=h_ju))
        situacao = {(i["origem"], i["referencia_id"]): i["situacao_atual"] for i in pendente["itens"]}
        assert situacao[("alerta", x["grave"].id)] == "aberto", "a fonte continua aberta"

        # A fonte resolve a queda depois da passagem: quem recebe ve a situacao ATUAL.
        await db.execute(update(m.Intercorrencia).where(m.Intercorrencia.id == x["grave"].id)
                         .values(situacao="encerrada", desfecho="Resolvido em teste"))
        await db.commit()
        [pendente] = await _ok(await client.get(URL + "/", headers=h_ju))
        situacao = {(i["origem"], i["referencia_id"]): i["situacao_atual"] for i in pendente["itens"]}
        assert situacao[("alerta", x["grave"].id)] == "resolvido"
        assert situacao[("intercorrencia", x["leve"].id)] == "aberto"
        assert situacao[("atividade", x["ocorrencia"].id)] == "aberto"

        assert (await client.post(f"{URL}/{entregue['id']}/receber", headers=h_ana)).status_code == 409
        recebida = await _ok(await client.post(f"{URL}/{entregue['id']}/receber", headers=h_ju))
        assert (recebida["situacao"], recebida["recebida_por_nome"]) == ("recebida", "enfermagem sintetico")
        assert (await client.post(f"{URL}/{entregue['id']}/receber", headers=h_ju)).status_code == 409
        assert await _ok(await client.get(URL + "/", headers=h_ju)) == []
        acoes = set((await db.scalars(select(m.Auditoria.acao).where(m.Auditoria.registro_id == entregue["id"]))).all())
        assert acoes == {"passagens_plantao.entregar", "passagens_plantao.receber"}
    _run(passagem_db, op)


def test_itens_respeitam_a_leitura_de_quem_consulta_e_o_tenant(passagem_db):
    async def op(client, db):
        ilpi, hg, ala_b, x = await _cenario(client, db)
        _, h_ana, _ = await _institucional(db, ilpi, "cuidador")
        # A area informada precisa ser uma pela qual Ana responde agora.
        assert (await client.post(URL + "/", headers=h_ana, json={"area_id": ala_b["id"]})).status_code == 403
        await _ok(await client.post("/api/plantoes/iniciar", headers=h_ana, json={"area_ids": [ala_b["id"]]}), 201)
        [entregue] = await _ok(await client.post(URL + "/", headers=h_ana, json={
            "area_id": ala_b["id"], "observacoes": [{"categoria": "assistencial", "texto": "Trocar curativo às 22h"}]}), 201)
        total = len(entregue["itens"])
        # So le passagens: ve as observacoes; o resto so aparece como contagem sem acesso.
        leitor = await _create_ilpi_user(db, ilpi, profile_key="so_passagem", permissions={"passagem_plantao:ler"})
        await db.commit()
        [visto] = await _ok(await client.get(URL + "/", headers=_headers(leitor, ilpi_id=ilpi.id)))
        assert [i["origem"] for i in visto["itens"]] == ["observacao"]
        assert visto["itens_sem_acesso"] == total - 1
        sem = await _create_ilpi_user(db, ilpi, profile_key="sem_passagem", permissions={"residentes:ler"})
        await db.commit()
        assert (await client.get(URL + "/", headers=_headers(sem, ilpi_id=ilpi.id))).status_code == 403
        assert (await client.post(f"{URL}/{entregue['id']}/receber", headers=_headers(leitor, ilpi_id=ilpi.id))).status_code == 403

        # Outra ILPI: a passagem nao existe para ela.
        ilpi_b, _, h_b, _ = await _ilpi_com_area(client, db, "ILPI B")
        _, h_b_cuid, _ = await _institucional(db, ilpi_b, "cuidador")
        assert await _ok(await client.get(URL + "/", headers=h_b_cuid)) == []
        assert (await client.get(f"{URL}/{entregue['id']}", headers=h_b_cuid)).status_code == 404
        assert (await client.post(f"{URL}/{entregue['id']}/receber", headers=h_b_cuid)).status_code == 404
        assert (await client.post(URL + "/", headers=h_b_cuid, json={
            "observacoes": [{"categoria": "outro", "residente_id": x["hilda"].id, "texto": "Residente de outra ILPI"}]})).status_code == 404
        assert (await client.get(f"{URL}/previa", headers=h_b_cuid, params={"area_id": ala_b["id"]})).status_code == 404
    _run(passagem_db, op)


def test_varias_areas_titulo_longo_ausencias_e_recebimento_concorrente(passagem_db):
    async def op(client, db):
        ilpi, hg, ala_b, x = await _cenario(client, db)
        # Ala C com Joao; Carla responde pelas duas areas.
        ala_c = await _ok(await client.post("/api/escala/areas", headers=hg, json={"nome": "Ala C", "tipo": "ala"}), 201)
        leito = await _ok(await client.post("/api/quartos_leitos/", headers=hg, json={"unidade": "Ala C", "quarto": "30", "leito": "A"}), 201)
        await _ok(await client.post(f"/api/quartos_leitos/{leito['id']}/alocar", headers=hg, json={"residente_id": x["joao"].id}))
        await _ok(await client.post(f"/api/escala/areas/{ala_c['id']}/leitos", headers=hg, json={"quarto_leito_id": leito["id"]}), 201)
        chaves_enf, _, _ = await _institucional(db, ilpi, "enfermagem")
        carla = await _create_ilpi_user(db, ilpi, permissions=chaves_enf | {"ausencias:ler"}, profile_key="enf_ausencias", nome="Carla Sintetica")
        await db.commit()
        h_carla = _headers(carla, ilpi_id=ilpi.id)
        # Ausencias: Hilda hospitalizada ha 10 dias (vira alerta, nao se repete); Rita saiu ontem (item de ausencia).
        longa = m.Ausencia(id=_new_id(), instituicao_id=ilpi.id, residente_id=x["hilda"].id, tipo="hospitalizacao",
                           data_inicio=_agora() - timedelta(days=10), motivo="Internacao sintetica", usuario_id=carla.id)
        curta = m.Ausencia(id=_new_id(), instituicao_id=ilpi.id, residente_id=x["rita"].id, tipo="saida_temporaria",
                           data_inicio=_agora() - timedelta(days=1), motivo="Passeio sintetico", usuario_id=carla.id)
        db.add_all([longa, curta])
        # Descricao de cuidado maior que o titulo persistido (255): a passagem trunca, nao quebra.
        prog_intervencao = await db.scalar(select(m.ProgramacaoCuidado.intervencao_id).where(
            m.ProgramacaoCuidado.id == x["ocorrencia"].programacao_id))
        await db.execute(update(m.PaisIntervencao).where(m.PaisIntervencao.id == prog_intervencao)
                         .values(descricao="Mudanca de decubito com protecao de proeminencias " * 8))
        await db.commit()
        await _ok(await client.post("/api/plantoes/iniciar", headers=h_carla, json={"area_ids": [ala_b["id"], ala_c["id"]]}), 201)

        previa = await _ok(await client.get(f"{URL}/previa", headers=h_carla))
        assert (previa["area_id"], previa["area_nome"]) == (None, "Ala B, Ala C"), "uniao das areas, nao a ILPI inteira"
        itens = {(i["origem"], i.get("regra"), i["referencia_id"]) for i in previa["itens"]}
        assert ("alerta", "intercorrencia_grave_aberta", x["fora"].id) in itens, "Joao esta na Ala C"
        assert ("alerta", "ausencia_prolongada", longa.id) in itens
        assert ("ausencia", None, longa.id) not in itens, "ausencia que ja e alerta nao se repete"
        assert ("ausencia", None, curta.id) in itens

        # Area de outra pessoa: so a coordenacao passa por ela.
        _, h_ana, _ = await _institucional(db, ilpi, "cuidador")
        assert (await client.get(f"{URL}/previa", headers=h_ana, params={"area_id": ala_c["id"]})).status_code == 403
        coord = await _create_ilpi_user(db, ilpi, permissions={"passagem_plantao:registrar", "escala:gerenciar"}, profile_key="coord_passagem")
        so_passagem = await _create_ilpi_user(db, ilpi, permissions={"passagem_plantao:registrar"}, profile_key="so_registra_passagem")
        await db.commit()
        assert (await _ok(await client.get(f"{URL}/previa", headers=_headers(coord, ilpi_id=ilpi.id),
                                           params={"area_id": ala_c["id"]})))["area_nome"] == "Ala C"
        # Encerrar plantao junto exige plantao:registrar.
        assert (await client.post(URL + "/", headers=_headers(so_passagem, ilpi_id=ilpi.id),
                                  json={"encerrar_plantao": True})).status_code == 403

        entregues = await _ok(await client.post(URL + "/", headers=h_carla, json={
            "observacoes": [{"categoria": "estrutura_materiais", "texto": "Faltam luvas M"},
                            {"categoria": "comportamento", "residente_id": x["joao"].id, "texto": "Joao ansioso"}]}), 201)
        # Uma passagem por area: cada proximo turno confirma a sua.
        por_area = {e["area_nome"]: e for e in entregues}
        assert sorted(por_area) == ["Ala B", "Ala C"] and all(e["area_id"] for e in entregues)
        refs = {nome: {i["referencia_id"] for i in e["itens"]} for nome, e in por_area.items()}
        assert x["fora"].id in refs["Ala C"] and x["fora"].id not in refs["Ala B"]
        assert x["grave"].id in refs["Ala B"] and x["grave"].id not in refs["Ala C"]
        textos = {nome: {i["texto"] for i in e["itens"] if i["origem"] == "observacao"} for nome, e in por_area.items()}
        assert textos == {"Ala B": {"Faltam luvas M"}, "Ala C": {"Faltam luvas M", "Joao ansioso"}}
        entregue = por_area["Ala B"]
        [cuidado] = [i for i in entregue["itens"] if i["origem"] == "atividade" and i["referencia_id"] == x["ocorrencia"].id]
        assert len(cuidado["titulo"]) == 255 and cuidado["titulo"].startswith("Cuidado sem registro: Mudanca")

        # Quem recebe sem residentes:ler: ve os itens das origens que le, sem nomes; nada quebra.
        sem_nomes = await _create_ilpi_user(db, ilpi, profile_key="recebe_sem_residentes", permissions={
            "passagem_plantao:ler", "passagem_plantao:registrar", "intercorrencias:ler", "plantao:ler", "alertas:ler"})
        rafa = await _create_ilpi_user(db, ilpi, permissions=chaves_enf, profile_key="enf_rafa", nome="Rafa Sintetico")
        await db.commit()
        h_sem, h_rafa = _headers(sem_nomes, ilpi_id=ilpi.id), _headers(rafa, ilpi_id=ilpi.id)
        vistos = await _ok(await client.get(URL + "/", headers=h_sem))
        assert len(vistos) == 2
        itens_vistos = [i for v in vistos for i in v["itens"]]
        assert itens_vistos and all(i["residente_nome"] is None for i in itens_vistos)
        assert {i["origem"] for i in itens_vistos} <= {"intercorrencia", "atividade", "alerta", "observacao"}

        # Duas pessoas confirmam ao mesmo tempo: uma recebe, a outra 409 (nunca 500 nem sobrescrita).
        respostas = await asyncio.gather(
            client.post(f"{URL}/{entregue['id']}/receber", headers=h_sem),
            client.post(f"{URL}/{entregue['id']}/receber", headers=h_rafa))
        assert sorted(r.status_code for r in respostas) == [200, 409], [r.text for r in respostas]
        vencedor = next(r for r in respostas if r.status_code == 200).json()["recebida_por_nome"]
        assert (await _ok(await client.get(f"{URL}/{entregue['id']}", headers=h_rafa)))["recebida_por_nome"] == vencedor
        recebimentos = (await db.scalars(select(m.Auditoria.acao).where(
            m.Auditoria.registro_id == entregue["id"], m.Auditoria.acao == "passagens_plantao.receber"))).all()
        assert len(recebimentos) == 1
    _run(passagem_db, op)


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def pre027_db(request, tmp_path):
    ref = _ref(request, tmp_path)
    _migrate(ref, target="026_alerta_estados")
    return ref


def test_027_concede_e_recusa_downgrade_com_historico(pre027_db):
    _migrate(pre027_db, target=HEAD)

    async def depois(client, db):
        linhas = (await db.execute(text(
            "SELECT perf.chave, p.chave FROM perfil_permissoes pp JOIN permissoes p ON p.id = pp.permissao_id "
            "JOIN perfis perf ON perf.id = pp.perfil_id WHERE perf.ilpi_id IS NULL AND p.modulo = 'passagem_plantao'"))).all()
        por_perfil = {}
        for perfil, chave in linhas:
            por_perfil.setdefault(perfil, set()).add(chave)
        ambas = {"passagem_plantao:ler", "passagem_plantao:registrar"}
        assert por_perfil == {"ilpi_admin": ambas, "cuidador": ambas, "enfermagem": ambas, "responsavel_tecnico": ambas,
                              "medico": {"passagem_plantao:ler"}}
        ilpi, _, _, _ = await _ilpi_com_area(client, db)
        _, h, _ = await _institucional(db, ilpi, "cuidador")
        await _ok(await client.post(URL + "/", headers=h, json={"observacoes": [{"categoria": "outro", "texto": "Tudo tranquilo"}]}), 201)
    _run(pre027_db, depois)
    falha = _migrate(pre027_db, target="026_alerta_estados", command="downgrade", success=False)
    assert "passagens_plantao tem historico" in falha.stdout + falha.stderr


def test_atividade_de_dose_na_passagem_exige_permissao_de_medicacao():
    from src.application.passagem import _pode_ver
    dose, cuidado = {"origem": "atividade", "regra": "medicacao"}, {"origem": "atividade", "regra": "cuidado"}
    assert _pode_ver(cuidado, {"plantao:ler"})
    assert not _pode_ver(dose, {"plantao:ler"}), "#131: plantao:ler sozinho nao ve dose"
    assert _pode_ver(dose, {"plantao:ler", "administracoes:ler"})

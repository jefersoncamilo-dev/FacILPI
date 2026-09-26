"""#107: central de alertas do gestor — projecao derivada, RBAC, tenant, sem escrita.

Cada regra dispara com dados sinteticos e SOME quando o problema e resolvido na
fonte oficial (validacao de documento, avanco da admissao, PAIS em vigencia,
execucao/administracao registrada, alocacao de leito...). Nada e gravado pelo GET.

Somente bancos descartaveis (SQLite em tmp_path; PostgreSQL via D3_TEST_POSTGRES_URL).
"""

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import asyncio
import pytest
from sqlalchemy import func, select, update

from .test_c5_medicacao_migration import KEYS as C5_KEYS
from .test_d2_rotina import (
    D2_ALL, PAIS6, _create_funcionario, _create_ilpi_user, _headers, _new_id, _new_institution,
    _prog_payload, _setup_pais_vigente,
)
from .test_d3_admissao import ALL as ADMISSOES, _client
from .test_d3_admissao_migration import _migrate, _ref
from src.infrastructure import models as m

HEAD = "022_alertas_gestor"
URL = "/api/central-alertas/"
FONTES = {
    "residentes:ler", "documentos:ler", "documentos:validar", "avaliacoes:ler", "grau_dependencia:ler",
    "quartos_leitos:ler", "quartos_leitos:criar", "quartos_leitos:atualizar", "ausencias:ler",
    "intercorrencias:ler", "funcionarios:ler",
}
GESTOR = {"alertas:ler"} | FONTES | ADMISSOES | PAIS6 | D2_ALL | C5_KEYS


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def alertas_db(request, tmp_path):
    ref = _ref(request, tmp_path)
    _migrate(ref, target=HEAD)
    return ref


def _run(ref, operation):
    asyncio.run(_client(ref, operation))


def _agora():
    return datetime.now(timezone.utc)


def _hoje():
    # A ILPI de teste usa o fuso padrao da instituicao.
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()


async def _gestor(db, nome="ILPI Alertas", permissions=None):
    ilpi = _new_institution(nome)
    user = await _create_ilpi_user(db, ilpi, permissions=GESTOR if permissions is None else permissions)
    await db.commit()
    return ilpi, user, _headers(user, ilpi_id=ilpi.id)


async def _residente(db, ilpi_id, nome, situacao="Ativo"):
    res = m.Residente(id=_new_id(), instituicao_id=ilpi_id, nome=nome, situacao=situacao,
                      data_nascimento=datetime(1940, 5, 1).date())
    db.add(res)
    await db.flush()
    return res


async def _alertas(client, h):
    r = await client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _por_regra(payload, regra):
    return [a for a in payload["alertas"] if a["regra"] == regra]


def _um(payload, regra, referencia):
    achados = [a for a in _por_regra(payload, regra) if a["referencia_id"] == referencia]
    assert len(achados) == 1, (regra, referencia, payload["alertas"])
    return achados[0]


def test_sem_permissao_contexto_e_rota_legada(alertas_db):
    async def op(client, db):
        assert (await client.get(URL)).status_code in (401, 403)
        ilpi, _, h_sem = await _gestor(db, "ILPI sem alertas", permissions=FONTES)
        assert (await client.get(URL, headers=h_sem)).status_code == 403
        _, gestor, h = await _gestor(db)
        assert (await client.get(URL, headers=_headers(gestor, scope="global"))).status_code == 403
        # O CRUD legado da 001 continua fail_closed, mesmo para quem tem alertas:ler.
        legado = await client.get("/api/alertas/", headers=h)
        assert legado.status_code == 403
        assert legado.json()["detail"]["code"] == "PERMISSION_CATALOG_PENDING"
        vazio = await _alertas(client, h)
        assert vazio["alertas"] == [] and vazio["contagem"] == {"critico": 0, "atencao": 0, "aviso": 0}
    _run(alertas_db, op)


def test_admissao_e_documentos_somem_quando_resolvidos(alertas_db):
    async def op(client, db):
        ilpi, gestor, h = await _gestor(db)
        res = await _residente(db, ilpi.id, "Antonia Sintetica", situacao="Em admissao")
        admissao = m.Admissao(id=_new_id(), ilpi_id=ilpi.id, residente_id=res.id, situacao="triagem",
                              autor_id=gestor.id, iniciada_em=_agora() - timedelta(days=10), avaliacoes_requeridas=[])
        pendente = m.Documento(id=_new_id(), residente_id=res.id, instituicao_id=ilpi.id, tipo="RG",
                               obrigatorio=True, situacao="pendente")
        vencido = m.Documento(id=_new_id(), residente_id=res.id, instituicao_id=ilpi.id, tipo="Laudo",
                              obrigatorio=False, situacao="validado", validade=_hoje() - timedelta(days=10))
        vencendo = m.Documento(id=_new_id(), residente_id=res.id, instituicao_id=ilpi.id, tipo="Vacina",
                               obrigatorio=False, situacao="validado", validade=_hoje() + timedelta(days=10))
        distante = m.Documento(id=_new_id(), residente_id=res.id, instituicao_id=ilpi.id, tipo="CNH",
                               obrigatorio=False, situacao="validado", validade=_hoje() + timedelta(days=90))
        db.add_all([admissao, pendente, vencido, vencendo, distante])
        await db.commit()

        antes = await _alertas(client, h)
        parada = _um(antes, "admissao_parada", admissao.id)
        assert parada["gravidade"] == "atencao" and parada["categoria"] == "admissao_documentos"
        assert parada["titulo"] == "Admissão parada em Triagem" and parada["residente_nome"] == "Antonia Sintetica"
        assert _um(antes, "documento_aguardando_validacao", pendente.id)["gravidade"] == "atencao"
        assert _um(antes, "documento_vencido", vencido.id)["gravidade"] == "atencao"
        assert _um(antes, "documento_vencendo", vencendo.id)["gravidade"] == "aviso"
        assert not [a for a in antes["alertas"] if a["referencia_id"] == distante.id]

        # Resolucao na fonte: avanco explicito, validacao humana, documento renovado.
        r = await client.post(f"/api/admissoes/{admissao.id}/avancar", headers=h,
                              json={"lock_version": 0, "etapa_destino": "documentacao"})
        assert r.status_code == 200, r.text
        r = await client.post(f"/api/documentos/{pendente.id}/validar", headers=h, json={})
        assert r.status_code == 200, r.text
        await db.execute(update(m.Documento).where(m.Documento.id.in_([vencido.id, vencendo.id]))
                         .values(validade=_hoje() + timedelta(days=365)))
        await db.commit()

        depois = await _alertas(client, h)
        assert depois["alertas"] == [], depois["alertas"]
    _run(alertas_db, op)


def test_avaliacao_grau_e_pais(alertas_db):
    async def op(client, db):
        ilpi, gestor, h = await _gestor(db)
        ativo = await _residente(db, ilpi.id, "Benedito Sintetico")
        em_admissao = await _residente(db, ilpi.id, "Cecilia Sintetica", situacao="Em admissao")
        revisor = await _create_funcionario(db, ilpi)
        katz = m.Avaliacao(id=_new_id(), residente_id=ativo.id, ilpi_id=ilpi.id, tipo="Katz", instrumento="Katz",
                           data=_agora() - timedelta(days=200), validade=_hoje() - timedelta(days=5))
        parado = m.PlanoCuidados(id=_new_id(), residente_id=em_admissao.id, ilpi_id=ilpi.id, versao=1,
                                 data_inicial=_hoje(), situacao="rascunho",
                                 created_at=_agora() - timedelta(days=12), updated_at=_agora() - timedelta(days=12))
        db.add_all([katz, parado])
        await db.commit()

        antes = await _alertas(client, h)
        assert _um(antes, "avaliacao_vencida", katz.id)["titulo"] == "Avaliação vencida: Katz · Katz"
        assert _um(antes, "grau_ausente", ativo.id)["residente_nome"] == "Benedito Sintetico"
        assert _um(antes, "pais_ausente", ativo.id)["gravidade"] == "critico"
        assert _um(antes, "pais_parado", parado.id)["titulo"] == "PAIS parado em Rascunho"
        # Residente em admissao nao cobra grau nem PAIS: a admissao ja cobra.
        assert not [a for a in antes["alertas"] if a["regra"] in ("grau_ausente", "pais_ausente")
                    and a["residente_id"] == em_admissao.id]

        db.add_all([
            m.Avaliacao(id=_new_id(), residente_id=ativo.id, ilpi_id=ilpi.id, tipo="Katz", instrumento="Katz",
                        data=_agora(), validade=_hoje() + timedelta(days=180)),
            m.GrauDependencia(id=_new_id(), ilpi_id=ilpi.id, residente_id=ativo.id, classificacao="Grau II",
                              origem="manual", justificativa="Confirmado em teste", confirmado_por=gestor.id,
                              validade=_hoje() - timedelta(days=1)),
        ])
        await db.commit()
        pais_id, _ = await _setup_pais_vigente(client, h, ativo.id, revisor.id)
        meio = await _alertas(client, h)
        assert not _por_regra(meio, "avaliacao_vencida") and not _por_regra(meio, "grau_ausente")
        assert not _por_regra(meio, "pais_ausente")
        assert _um(meio, "grau_vencido", (await db.scalar(select(m.GrauDependencia.id).where(
            m.GrauDependencia.residente_id == ativo.id))))["gravidade"] == "atencao"

        await db.execute(update(m.PlanoCuidados).where(m.PlanoCuidados.id == pais_id)
                         .values(data_final=_hoje() - timedelta(days=1)))
        await db.commit()
        assert _um(await _alertas(client, h), "pais_vencido", pais_id)["gravidade"] == "atencao"
    _run(alertas_db, op)


def test_plantao_cuidados_doses_e_intercorrencias(alertas_db):
    async def op(client, db):
        ilpi, gestor, h = await _gestor(db)
        res = await _residente(db, ilpi.id, "Dirceu Sintetico")
        revisor = await _create_funcionario(db, ilpi)
        grave = m.Intercorrencia(id=_new_id(), residente_id=res.id, ilpi_id=ilpi.id, tipo="Queda",
                                 gravidade="grave", situacao="aberta", ocorrido_em=_agora() - timedelta(hours=1))
        antiga = m.Intercorrencia(id=_new_id(), residente_id=res.id, ilpi_id=ilpi.id, tipo="Febre",
                                  gravidade="leve", situacao="aberta", ocorrido_em=_agora() - timedelta(hours=30))
        recente = m.Intercorrencia(id=_new_id(), residente_id=res.id, ilpi_id=ilpi.id, tipo="Tosse",
                                   gravidade="leve", situacao="aberta", ocorrido_em=_agora() - timedelta(hours=2))
        db.add_all([grave, antiga, recente])
        await db.commit()

        # Cuidado: PAIS vigente -> programacao; uma ocorrencia passa do horario.
        pais_id, intervencao_id = await _setup_pais_vigente(client, h, res.id, revisor.id)
        r = await client.post("/api/programacoes-cuidado/", headers=h, json=_prog_payload(pais_id, intervencao_id, inicio_horas=-3))
        assert r.status_code == 201, r.text
        ocorrencia = (await db.scalars(select(m.OcorrenciaCuidado).where(
            m.OcorrenciaCuidado.programacao_id == r.json()["id"]).order_by(m.OcorrenciaCuidado.previsto_em))).first()
        # Fora da janela de 24 h: nao entra no alerta.
        velha = (await db.scalars(select(m.OcorrenciaCuidado).where(
            m.OcorrenciaCuidado.programacao_id == r.json()["id"]).order_by(m.OcorrenciaCuidado.previsto_em.desc()))).first()
        await db.execute(update(m.OcorrenciaCuidado).where(m.OcorrenciaCuidado.id == ocorrencia.id)
                         .values(previsto_em=_agora() - timedelta(hours=2)))
        await db.execute(update(m.OcorrenciaCuidado).where(m.OcorrenciaCuidado.id == velha.id)
                         .values(previsto_em=_agora() - timedelta(hours=30)))
        await db.commit()  # libera a escrita antes das proximas requisicoes (SQLite)

        # Dose: prescricao ativa; uma dose passa do horario.
        med = await client.post("/api/medicamentos/", headers=h, json={"nome": "Medicamento Sintetico", "unidade": "comprimido"})
        assert med.status_code == 201, med.text
        inicio = _agora() - timedelta(hours=3)
        pre = await client.post("/api/prescricoes/", headers=h, json={
            "residente_id": res.id, "medicamento_id": med.json()["id"], "prescritor_nome": "Dra Externa",
            "prescritor_categoria": "medico", "dose": "1", "unidade": "comprimido", "via": "oral",
            "inicio": inicio.date().isoformat()})
        assert pre.status_code == 201, pre.text
        ativa = await client.post(f"/api/prescricoes/{pre.json()['id']}/ativar", headers=h, json={
            "horarios": ["12:01"], "timezone": "UTC", "vigencia_inicio": inicio.isoformat()})
        assert ativa.status_code == 200, ativa.text
        dose = (await db.scalars(select(m.DosePrevista).where(m.DosePrevista.prescricao_id == pre.json()["id"])
                                 .order_by(m.DosePrevista.previsto_em))).first()
        await db.execute(update(m.DosePrevista).where(m.DosePrevista.id == dose.id)
                         .values(previsto_em=_agora() - timedelta(hours=1)))
        await db.commit()

        # A materializacao pode ja trazer horarios passados (depende da hora do
        # teste): o esperado sai do banco, com a mesma janela da regra.
        agora_dt = _agora()
        janela = (agora_dt - timedelta(hours=24), agora_dt)
        pendentes = (await db.scalars(select(m.OcorrenciaCuidado.id).where(
            m.OcorrenciaCuidado.residente_id == res.id, m.OcorrenciaCuidado.previsto_em >= janela[0],
            m.OcorrenciaCuidado.previsto_em < janela[1]))).all()
        doses_passadas = (await db.scalars(select(m.DosePrevista.id).where(
            m.DosePrevista.residente_id == res.id, m.DosePrevista.previsto_em >= janela[0],
            m.DosePrevista.previsto_em < janela[1]))).all()
        assert ocorrencia.id in pendentes and velha.id not in pendentes and dose.id in doses_passadas

        antes = await _alertas(client, h)
        cuidados = _um(antes, "cuidados_sem_registro", res.id)
        n = len(pendentes)
        assert cuidados["titulo"] == f"{n} {'cuidado' if n == 1 else 'cuidados'} sem registro"
        assert cuidados["gravidade"] == "atencao"
        doses = _um(antes, "doses_sem_registro", res.id)
        n = len(doses_passadas)
        assert doses["titulo"] == f"{n} {'dose de medicação' if n == 1 else 'doses de medicação'} sem registro"
        assert doses["gravidade"] == "critico"
        assert _um(antes, "intercorrencia_grave_aberta", grave.id)["gravidade"] == "critico"
        assert _um(antes, "intercorrencia_aberta_prolongada", antiga.id)["gravidade"] == "atencao"
        assert not [a for a in antes["alertas"] if a["referencia_id"] == recente.id]
        assert antes["alertas"][0]["gravidade"] == "critico"
        assert antes["contagem"]["critico"] == len([a for a in antes["alertas"] if a["gravidade"] == "critico"])

        # Resolucao na fonte: execucao e administracao registradas, intercorrencias encerradas.
        agora = _agora().isoformat()
        for oid in pendentes:
            r = await client.post("/api/execucoes-cuidado/", headers=h, json={
                "ocorrencia_id": oid, "resultado": "executada", "ocorrido_em": agora})
            assert r.status_code == 201, r.text
        for did in doses_passadas:
            r = await client.post("/api/administracoes/", headers=h, json={
                "dose_prevista_id": did, "resultado": "administrada", "ocorrido_em": agora, "quantidade_realizada": "1"})
            assert r.status_code == 201, r.text
        await db.execute(update(m.Intercorrencia).where(m.Intercorrencia.id.in_([grave.id, antiga.id]))
                         .values(situacao="encerrada", desfecho="Resolvido em teste"))
        await db.commit()
        depois = await _alertas(client, h)
        assert not [a for a in depois["alertas"] if a["categoria"] == "plantao"], depois["alertas"]
    _run(alertas_db, op)


def test_ocupacao_e_equipe(alertas_db):
    async def op(client, db):
        ilpi, gestor, h = await _gestor(db)
        sem_leito = await _residente(db, ilpi.id, "Elza Sintetica")
        hospitalizado = await _residente(db, ilpi.id, "Francisco Sintetico", situacao="Em admissao")
        ausencia = m.Ausencia(id=_new_id(), instituicao_id=ilpi.id, residente_id=hospitalizado.id, tipo="hospitalizacao",
                              data_inicio=_agora() - timedelta(days=10), motivo="Pneumonia", usuario_id=gestor.id)
        recente = await _residente(db, ilpi.id, "Geralda Sintetica", situacao="Em admissao")
        curta = m.Ausencia(id=_new_id(), instituicao_id=ilpi.id, residente_id=recente.id, tipo="saida_temporaria",
                           data_inicio=_agora() - timedelta(days=2), motivo="Visita", usuario_id=gestor.id)
        velho = m.User(id=_new_id(), nome="Tiago Sintetico", email=f"tiago-{_new_id()}@example.com",
                       password_hash="fixture-password-hash", ativo=True, exige_troca_senha=True,
                       created_at=_agora() - timedelta(days=10), updated_at=_agora() - timedelta(days=10))
        novo = m.User(id=_new_id(), nome="Luciana Sintetica", email=f"luciana-{_new_id()}@example.com",
                      password_hash="fixture-password-hash", ativo=True, exige_troca_senha=True)
        db.add_all([ausencia, curta, velho, novo])
        await db.flush()
        func_velho = m.Funcionario(id=_new_id(), ilpi_id=ilpi.id, usuario_id=velho.id, nome=velho.nome, situacao="ativo")
        db.add_all([func_velho, m.Funcionario(id=_new_id(), ilpi_id=ilpi.id, usuario_id=novo.id, nome=novo.nome, situacao="ativo")])
        await db.commit()

        antes = await _alertas(client, h)
        assert _um(antes, "residente_sem_leito", sem_leito.id)["gravidade"] == "atencao"
        prolongada = _um(antes, "ausencia_prolongada", ausencia.id)
        assert prolongada["titulo"] == "Hospitalização sem retorno há mais de 7 dias" and prolongada["detalhe"] == "Pneumonia"
        assert not _por_regra(antes, "ausencia_prolongada")[1:]
        assert _um(antes, "acesso_nao_utilizado", func_velho.id)["titulo"] == "Acesso ainda não utilizado: Tiago Sintetico"
        assert len(_por_regra(antes, "acesso_nao_utilizado")) == 1

        leito = await client.post("/api/quartos_leitos/", headers=h, json={"quarto": "101", "leito": "A"})
        assert leito.status_code == 201, leito.text
        r = await client.post(f"/api/quartos_leitos/{leito.json()['id']}/alocar", headers=h, json={"residente_id": sem_leito.id})
        assert r.status_code == 200, r.text
        await db.execute(update(m.Ausencia).where(m.Ausencia.id == ausencia.id).values(data_fim=_agora()))
        await db.execute(update(m.User).where(m.User.id == velho.id).values(exige_troca_senha=False))
        await db.commit()
        # O residente ativo segue sem grau/PAIS (outra categoria, corretamente).
        restantes = (await _alertas(client, h))["alertas"]
        assert not [a for a in restantes if a["categoria"] == "ocupacao_equipe"], restantes
        assert {a["regra"] for a in restantes} == {"grau_ausente", "pais_ausente"}
    _run(alertas_db, op)


def test_tenant_permissao_de_origem_e_sem_escrita(alertas_db):
    async def op(client, db):
        ilpi_a, gestor_a, h_a = await _gestor(db, "ILPI A")
        ilpi_b, _, h_b = await _gestor(db, "ILPI B")
        res_a = await _residente(db, ilpi_a.id, "Residente A", situacao="Em admissao")
        res_b = await _residente(db, ilpi_b.id, "Residente B", situacao="Em admissao")
        grave_a = m.Intercorrencia(id=_new_id(), residente_id=res_a.id, ilpi_id=ilpi_a.id, tipo="Queda",
                                   gravidade="grave", situacao="aberta", ocorrido_em=_agora())
        grave_b = m.Intercorrencia(id=_new_id(), residente_id=res_b.id, ilpi_id=ilpi_b.id, tipo="Engasgo",
                                   gravidade="grave", situacao="aberta", ocorrido_em=_agora())
        db.add_all([grave_a, grave_b])
        await db.commit()

        a = await _alertas(client, h_a)
        assert {x["referencia_id"] for x in a["alertas"]} == {grave_a.id}
        # Header de outra ILPI nao abre a ILPI B: o contexto vem do vinculo da sessao.
        cruzado = await client.get(URL, headers=_headers(gestor_a, ilpi_id=ilpi_b.id))
        assert cruzado.status_code == 403 and grave_b.id not in cruzado.text
        b = await _alertas(client, h_b)
        assert {x["referencia_id"] for x in b["alertas"]} == {grave_b.id}

        # Com alertas:ler mas sem intercorrencias:ler, a regra nao existe.
        limitado = await _create_ilpi_user(db, ilpi_a, permissions={"alertas:ler", "residentes:ler"}, profile_key="limitado")
        await db.commit()
        sem_origem = await _alertas(client, _headers(limitado, ilpi_id=ilpi_a.id))
        assert sem_origem["alertas"] == [] and sem_origem["contagem"]["critico"] == 0
        # Sem residentes:ler, o nome nao sai (a regra sai, pois le intercorrencias).
        so_inter = await _create_ilpi_user(db, ilpi_a, permissions={"alertas:ler", "intercorrencias:ler"}, profile_key="so_inter")
        await db.commit()
        cego = await _alertas(client, _headers(so_inter, ilpi_id=ilpi_a.id))
        assert [x["residente_nome"] for x in cego["alertas"]] == [None]

        async def contagens():
            tabelas = (m.Auditoria, m.Intercorrencia, m.Residente, m.Documento, m.Admissao, m.PlanoCuidados)
            return [await db.scalar(select(func.count()).select_from(t)) for t in tabelas]
        antes = await contagens()
        for _ in range(2):
            await _alertas(client, h_a)
        assert await contagens() == antes
    _run(alertas_db, op)

"""#117: central de alertas para os perfis operacionais (Camada Operacional, Fase 1).

Cobre o contrato novo do item — RBAC por origem para cada perfil institucional
da 015 (com ``alertas:ler`` da 023), localizacao operacional minima sem
``quartos_leitos:ler``, ``natureza``, ``desde``/``prazo``, ordenacao
deterministica, id estavel e isolamento entre ILPIs.

Os perfis usam exatamente as permissoes que o template tem em head (lidas do
banco), como um clone criado por atribuicao S.1 — inclusive o ``ilpi_admin``
real, para que um gestor sintetico com permissoes a mais nao esconda perda de
regra do Administrador da ILPI.

Somente bancos descartaveis (SQLite em tmp_path; PostgreSQL via D3_TEST_POSTGRES_URL).
"""

import hashlib
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from .test_alertas_gestor import (  # noqa: F401 - fixture alertas_db
    _agora, _alertas, _gestor, _hoje, _por_regra, _residente, _run, _um, alertas_db,
)
from .test_d2_rotina import (
    _create_funcionario, _create_ilpi_user, _headers, _new_id, _new_institution, _prog_payload, _setup_pais_vigente,
)
from src.infrastructure import models as m

FUSO = ZoneInfo("America/Sao_Paulo")
OPERACIONAIS = ("cuidador", "enfermagem", "medico", "responsavel_tecnico", "administrativo")
PERFIS_REAIS = ("ilpi_admin",) + OPERACIONAIS

# Contrato de visibilidade: alertas:ler + leitura do modulo de origem.
ORIGEM = {
    "admissao_parada": {"admissoes:ler"},
    "documento_aguardando_validacao": {"documentos:ler"},
    "documento_vencido": {"documentos:ler"},
    "documento_vencendo": {"documentos:ler"},
    "avaliacao_vencida": {"avaliacoes:ler"},
    "grau_ausente": {"grau_dependencia:ler", "residentes:ler"},
    "grau_vencido": {"grau_dependencia:ler", "residentes:ler"},
    "pais_ausente": {"planos_cuidados:ler", "residentes:ler"},
    "pais_parado": {"planos_cuidados:ler"},
    "pais_vencido": {"planos_cuidados:ler"},
    # Mesma origem do Meu Plantao: plantao:ler projeta cuidados e doses pendentes.
    "cuidados_sem_registro": {"plantao:ler"},
    "doses_sem_registro": {"plantao:ler"},
    "intercorrencia_grave_aberta": {"intercorrencias:ler"},
    "intercorrencia_aberta_prolongada": {"intercorrencias:ler"},
    "residente_sem_leito": {"quartos_leitos:ler", "residentes:ler"},
    "ausencia_prolongada": {"ausencias:ler"},
    "acesso_nao_utilizado": {"funcionarios:ler"},
}
NATUREZA = {
    "doses_sem_registro": "alerta", "cuidados_sem_registro": "alerta", "intercorrencia_grave_aberta": "alerta",
    "intercorrencia_aberta_prolongada": "alerta", "ausencia_prolongada": "alerta",
}


def _fim_do_dia(dia):
    return datetime.combine(dia + timedelta(days=1), time.min, tzinfo=FUSO).astimezone(timezone.utc)


def _dt(valor):
    return datetime.fromisoformat(valor) if valor else None


async def _institucional(db, ilpi, chave):
    """Usuario com exatamente as permissoes do template institucional em head."""
    chaves = set((await db.scalars(
        select(m.Permissao.chave).join(m.PerfilPermissao, m.PerfilPermissao.permissao_id == m.Permissao.id)
        .join(m.Perfil, m.Perfil.id == m.PerfilPermissao.perfil_id)
        .where(m.Perfil.chave == chave, m.Perfil.ilpi_id.is_(None)))).all())
    assert "alertas:ler" in chaves, f"023 nao concedeu alertas:ler ao template {chave}"
    user = await _create_ilpi_user(db, ilpi, permissions=chaves, profile_key=chave, nome=f"{chave} sintetico")
    await db.commit()
    return chaves, _headers(user, ilpi_id=ilpi.id), user


async def _dose_atrasada(client, db, h, residente_id):
    med = await client.post("/api/medicamentos/", headers=h, json={"nome": "Medicamento Sintetico", "unidade": "comprimido"})
    assert med.status_code == 201, med.text
    inicio = _agora() - timedelta(hours=3)
    pre = await client.post("/api/prescricoes/", headers=h, json={
        "residente_id": residente_id, "medicamento_id": med.json()["id"], "prescritor_nome": "Dra Externa",
        "prescritor_categoria": "medico", "dose": "1", "unidade": "comprimido", "via": "oral",
        "inicio": inicio.date().isoformat()})
    assert pre.status_code == 201, pre.text
    ativa = await client.post(f"/api/prescricoes/{pre.json()['id']}/ativar", headers=h, json={
        "horarios": ["12:01"], "timezone": "UTC", "vigencia_inicio": inicio.isoformat()})
    assert ativa.status_code == 200, ativa.text
    dose = (await db.scalars(select(m.DosePrevista).where(m.DosePrevista.prescricao_id == pre.json()["id"])
                             .order_by(m.DosePrevista.previsto_em))).first()
    dose.previsto_em = _agora() - timedelta(hours=1)
    await db.commit()


async def _cenario(client, db):
    """Uma ILPI com pelo menos um item de cada origem relevante."""
    ilpi, gestor, h = await _gestor(db)
    hilda = await _residente(db, ilpi.id, "Hilda Sintetica")
    joao = await _residente(db, ilpi.id, "Joao Sintetico")
    maria = await _residente(db, ilpi.id, "Maria Sintetica", situacao="Em admissao")
    await db.commit()
    leito = await client.post("/api/quartos_leitos/", headers=h, json={"unidade": "Ala B", "quarto": "12", "leito": "A"})
    assert leito.status_code == 201, leito.text
    r = await client.post(f"/api/quartos_leitos/{leito.json()['id']}/alocar", headers=h, json={"residente_id": hilda.id})
    assert r.status_code == 200, r.text

    velho = m.User(id=_new_id(), nome="Tiago Sintetico", email=f"tiago-{_new_id()}@example.com",
                   password_hash="fixture-password-hash", ativo=True, exige_troca_senha=True,
                   created_at=_agora() - timedelta(days=10), updated_at=_agora() - timedelta(days=10))
    db.add(velho)
    await db.flush()
    itens = dict(
        admissao=m.Admissao(id=_new_id(), ilpi_id=ilpi.id, residente_id=maria.id, situacao="triagem",
                            autor_id=gestor.id, iniciada_em=_agora() - timedelta(days=10), avaliacoes_requeridas=[]),
        pendente=m.Documento(id=_new_id(), residente_id=maria.id, instituicao_id=ilpi.id, tipo="RG", obrigatorio=True,
                             situacao="pendente", created_at=_agora() - timedelta(days=10)),
        vencido=m.Documento(id=_new_id(), residente_id=hilda.id, instituicao_id=ilpi.id, tipo="Laudo", obrigatorio=False,
                            situacao="validado", validade=_hoje() - timedelta(days=10)),
        vencendo=m.Documento(id=_new_id(), residente_id=hilda.id, instituicao_id=ilpi.id, tipo="Vacina",
                             obrigatorio=False, situacao="validado", validade=_hoje() + timedelta(days=10)),
        katz=m.Avaliacao(id=_new_id(), residente_id=hilda.id, ilpi_id=ilpi.id, tipo="Katz", instrumento="Katz",
                         data=_agora() - timedelta(days=200), validade=_hoje() - timedelta(days=5)),
        grave=m.Intercorrencia(id=_new_id(), residente_id=hilda.id, ilpi_id=ilpi.id, tipo="Queda", gravidade="grave",
                               situacao="aberta", ocorrido_em=_agora() - timedelta(hours=1)),
        antiga=m.Intercorrencia(id=_new_id(), residente_id=joao.id, ilpi_id=ilpi.id, tipo="Febre", gravidade="leve",
                                situacao="aberta", ocorrido_em=_agora() - timedelta(hours=30)),
        ausencia=m.Ausencia(id=_new_id(), instituicao_id=ilpi.id, residente_id=maria.id, tipo="hospitalizacao",
                            data_inicio=_agora() - timedelta(days=10), motivo="Pneumonia", usuario_id=gestor.id),
        acesso=m.Funcionario(id=_new_id(), ilpi_id=ilpi.id, usuario_id=velho.id, nome=velho.nome, situacao="ativo"),
    )
    db.add_all(itens.values())
    await db.commit()
    await _dose_atrasada(client, db, h, hilda.id)

    # Grau vencido (Joao), PAIS parado (Maria, em admissao), PAIS vigente vencido com cuidado atrasado (Rita).
    grau = m.GrauDependencia(id=_new_id(), ilpi_id=ilpi.id, residente_id=joao.id, classificacao="Grau II", origem="manual",
                             justificativa="Confirmado em teste", confirmado_por=gestor.id,
                             validade=_hoje() - timedelta(days=3))
    parado = m.PlanoCuidados(id=_new_id(), residente_id=maria.id, ilpi_id=ilpi.id, versao=1, data_inicial=_hoje(),
                             situacao="rascunho", created_at=_agora() - timedelta(days=12),
                             updated_at=_agora() - timedelta(days=12))
    rita = await _residente(db, ilpi.id, "Rita Sintetica")
    revisor = await _create_funcionario(db, ilpi)
    db.add_all([grau, parado])
    await db.commit()
    pais_id, intervencao_id = await _setup_pais_vigente(client, h, rita.id, revisor.id)
    r = await client.post("/api/programacoes-cuidado/", headers=h, json=_prog_payload(pais_id, intervencao_id, inicio_horas=-3))
    assert r.status_code == 201, r.text
    ocorrencia = (await db.scalars(select(m.OcorrenciaCuidado).where(
        m.OcorrenciaCuidado.programacao_id == r.json()["id"]).order_by(m.OcorrenciaCuidado.previsto_em))).first()
    await db.execute(update(m.OcorrenciaCuidado).where(m.OcorrenciaCuidado.id == ocorrencia.id)
                     .values(previsto_em=_agora() - timedelta(hours=2)))
    await db.execute(update(m.PlanoCuidados).where(m.PlanoCuidados.id == pais_id).values(data_final=_hoje() - timedelta(days=1)))
    await db.commit()
    return ilpi, h, dict(itens, hilda=hilda, joao=joao, maria=maria, rita=rita, grau=grau, parado=parado, pais=pais_id)


def test_perfis_operacionais_veem_so_origens_autorizadas(alertas_db):
    async def op(client, db):
        ilpi, h_gestor, x = await _cenario(client, db)
        todas = {a["regra"] for a in (await _alertas(client, h_gestor))["alertas"]}
        assert set(ORIGEM) <= todas, set(ORIGEM) - todas

        vistas = {}
        for chave in PERFIS_REAIS:
            permissoes, h, _ = await _institucional(db, ilpi, chave)
            payload = await _alertas(client, h)
            regras = {a["regra"] for a in payload["alertas"]}
            esperadas = {regra for regra, exige in ORIGEM.items() if exige <= permissoes}
            assert regras & set(ORIGEM) == esperadas, (chave, regras, esperadas)
            vistas[chave] = regras

        # O Administrador da ILPI real continua recebendo o que recebia (inclusive doses, critico).
        assert {"doses_sem_registro", "cuidados_sem_registro", "admissao_parada", "pais_ausente"} <= vistas["ilpi_admin"]
        # Cuidador: sem admissao, documentos, acessos, leitos e ausencias.
        for proibida in ("admissao_parada", "documento_aguardando_validacao", "documento_vencido",
                         "acesso_nao_utilizado", "residente_sem_leito", "ausencia_prolongada", "avaliacao_vencida"):
            assert proibida not in vistas["cuidador"], proibida
        assert {"pais_ausente", "cuidados_sem_registro", "intercorrencia_grave_aberta"} <= vistas["cuidador"]
        # Enfermagem: avaliacoes, intercorrencias, doses e PAIS conforme a matriz.
        assert {"avaliacao_vencida", "intercorrencia_grave_aberta", "doses_sem_registro", "pais_ausente"} <= vistas["enfermagem"]
        assert not vistas["enfermagem"] & {"admissao_parada", "documento_vencido", "acesso_nao_utilizado"}
        # Administrativo: so documentos.
        assert vistas["administrativo"] & set(ORIGEM) == {"documento_aguardando_validacao", "documento_vencido", "documento_vencendo"}
    _run(alertas_db, op)


def test_localizacao_minima_sem_quartos_leitos(alertas_db):
    async def op(client, db):
        ilpi, h_gestor, x = await _cenario(client, db)
        permissoes, h, _ = await _institucional(db, ilpi, "cuidador")
        assert "quartos_leitos:ler" not in permissoes
        # A localizacao nao concede o modulo.
        assert (await client.get("/api/quartos_leitos/", headers=h)).status_code == 403

        payload = await _alertas(client, h)
        hilda = _um(payload, "pais_ausente", x["hilda"].id)
        assert (hilda["unidade"], hilda["quarto"], hilda["leito"]) == ("Ala B", "12", "A")
        assert hilda["local"] == "Ala B · Quarto 12 · Leito A"
        joao = _um(payload, "pais_ausente", x["joao"].id)
        assert (joao["unidade"], joao["quarto"], joao["leito"], joao["local"]) == (None, None, None, None)

        # Sem residentes:ler nao ha nome nem localizacao (mesmo gate conservador).
        so_inter = await _create_ilpi_user(db, ilpi, permissions={"alertas:ler", "intercorrencias:ler"}, profile_key="so_inter")
        await db.commit()
        cego = _um(await _alertas(client, _headers(so_inter, ilpi_id=ilpi.id)), "intercorrencia_grave_aberta", x["grave"].id)
        assert cego["residente_nome"] is None and cego["local"] is None

        # Leito sem unidade: local so com quarto e leito.
        leito = await client.post("/api/quartos_leitos/", headers=h_gestor, json={"quarto": "7", "leito": "B"})
        assert leito.status_code == 201, leito.text
        r = await client.post(f"/api/quartos_leitos/{leito.json()['id']}/alocar", headers=h_gestor,
                              json={"residente_id": x["joao"].id})
        assert r.status_code == 200, r.text
        assert _um(await _alertas(client, h), "pais_ausente", x["joao"].id)["local"] == "Quarto 7 · Leito B"
    _run(alertas_db, op)


def test_natureza_desde_prazo_e_contagem(alertas_db):
    async def op(client, db):
        ilpi, h, x = await _cenario(client, db)
        payload = await _alertas(client, h)
        for a in payload["alertas"]:
            assert a["natureza"] == NATUREZA.get(a["regra"], "pendencia"), a

        vencido = _um(payload, "documento_vencido", x["vencido"].id)
        assert _dt(vencido["prazo"]) == _fim_do_dia(x["vencido"].validade) == _dt(vencido["desde"])
        vencendo = _um(payload, "documento_vencendo", x["vencendo"].id)
        assert _dt(vencendo["prazo"]) == _fim_do_dia(x["vencendo"].validade) and vencendo["desde"] is None
        katz = _um(payload, "avaliacao_vencida", x["katz"].id)
        assert _dt(katz["prazo"]) == _fim_do_dia(x["katz"].validade) == _dt(katz["desde"])
        grave = _um(payload, "intercorrencia_grave_aberta", x["grave"].id)
        assert abs(_dt(grave["desde"]) - x["grave"].ocorrido_em.replace(tzinfo=timezone.utc)) < timedelta(seconds=1)
        assert grave["prazo"] is None
        parada = _um(payload, "admissao_parada", x["admissao"].id)
        assert _dt(parada["desde"]) is not None and parada["prazo"] is None
        for sem_origem in ("grau_ausente", "pais_ausente"):
            item = _um(payload, sem_origem, x["hilda"].id)
            assert item["desde"] is None and item["prazo"] is None, item
        dose = _um(payload, "doses_sem_registro", x["hilda"].id)
        assert dose["prazo"] is not None and dose["prazo"] == dose["desde"]

        contagem, itens = payload["contagem"], payload["alertas"]
        assert contagem["total"] == len(itens)
        for chave in ("critico", "atencao", "aviso"):
            assert contagem[chave] == len([a for a in itens if a["gravidade"] == chave])
        for chave in ("alerta", "pendencia"):
            assert contagem[chave] == len([a for a in itens if a["natureza"] == chave]) > 0
        assert contagem["informativo"] == contagem["atividade"] == 0
        assert contagem["alerta"] + contagem["pendencia"] == contagem["total"]
    _run(alertas_db, op)


def _chave_contrato(item, agora):
    prazo, desde = _dt(item["prazo"]), _dt(item["desde"])
    if prazo is not None and prazo <= agora:
        faixa, t = 0, prazo
    elif desde is not None:
        faixa, t = 0, desde
    elif prazo is not None:
        faixa, t = 1, prazo
    else:
        faixa, t = 2, datetime.max.replace(tzinfo=timezone.utc)
    return ({"critico": 0, "atencao": 1, "aviso": 2}[item["gravidade"]],
            {"alerta": 0, "pendencia": 1}[item["natureza"]], faixa, t, item["id"])


def test_ordem_deterministica_e_id_estavel(alertas_db):
    async def op(client, db):
        ilpi, h, x = await _cenario(client, db)
        primeira = await _alertas(client, h)
        segunda = await _alertas(client, h)
        ids = [a["id"] for a in primeira["alertas"]]
        assert ids == [a["id"] for a in segunda["alertas"]], "recalcular nao muda id nem ordem"
        assert len(set(ids)) == len(ids)
        agora = _dt(primeira["gerado_em"])
        esperado = [a["id"] for a in sorted(primeira["alertas"], key=lambda a: _chave_contrato(a, agora))]
        assert ids == esperado

        # Alerta antes de pendencia na mesma gravidade, mesmo com a pendencia mais antiga.
        prolongada = ids.index(_um(primeira, "intercorrencia_aberta_prolongada", x["antiga"].id)["id"])
        documento = ids.index(_um(primeira, "documento_aguardando_validacao", x["pendente"].id)["id"])
        assert prolongada < documento
        # Com origem antes de so-prazo-futuro (mesma gravidade e natureza).
        acesso = ids.index(_um(primeira, "acesso_nao_utilizado", x["acesso"].id)["id"])
        vencendo = ids.index(_um(primeira, "documento_vencendo", x["vencendo"].id)["id"])
        assert acesso < vencendo

        # Formato do id: regra:referencia[:contexto]; texto livre vira hash.
        assert _um(primeira, "admissao_parada", x["admissao"].id)["id"] == f"admissao_parada:{x['admissao'].id}:triagem"
        grave = _um(primeira, "intercorrencia_grave_aberta", x["grave"].id)
        assert grave["id"] == f"intercorrencia_grave_aberta:{x['grave'].id}"
        hash_katz = hashlib.sha1("Katz\x1fKatz".encode("utf-8")).hexdigest()[:12]
        katz_id = f"avaliacao_vencida:{x['hilda'].id}:{hash_katz}"
        assert _um(primeira, "avaliacao_vencida", x["katz"].id)["id"] == katz_id

        # Nova avaliacao do mesmo grupo, tambem vencida: a situacao e a mesma, o id nao muda.
        nova = m.Avaliacao(id=_new_id(), residente_id=x["hilda"].id, ilpi_id=ilpi.id, tipo="Katz", instrumento="Katz",
                           data=_agora() - timedelta(days=1), validade=_hoje() - timedelta(days=2))
        db.add(nova)
        await db.commit()
        depois = await _alertas(client, h)
        item = _um(depois, "avaliacao_vencida", nova.id)
        assert item["id"] == katz_id and _dt(item["prazo"]) == _fim_do_dia(nova.validade)
    _run(alertas_db, op)


def test_perfil_operacional_isolado_por_ilpi(alertas_db):
    async def op(client, db):
        ilpi_a, _, x = await _cenario(client, db)
        ilpi_b = _new_institution("ILPI B operacional")
        _, h_b, _ = await _institucional(db, ilpi_b, "enfermagem")
        res_b = await _residente(db, ilpi_b.id, "Residente B")
        grave_b = m.Intercorrencia(id=_new_id(), residente_id=res_b.id, ilpi_id=ilpi_b.id, tipo="Engasgo",
                                   gravidade="grave", situacao="aberta", ocorrido_em=_agora())
        db.add(grave_b)
        await db.commit()

        _, h_a, enf_a = await _institucional(db, ilpi_a, "enfermagem")
        a = await _alertas(client, h_a)
        assert grave_b.id not in {i["referencia_id"] for i in a["alertas"]}
        assert x["grave"].id in {i["referencia_id"] for i in a["alertas"]}
        b = await _alertas(client, h_b)
        assert {i["referencia_id"] for i in b["alertas"] if i["regra"] == "intercorrencia_grave_aberta"} == {grave_b.id}
        # Header de outra ILPI nao abre a ILPI B: o contexto vem do vinculo da sessao.
        cruzado = await client.get("/api/central-alertas/", headers=_headers(enf_a, ilpi_id=ilpi_b.id))
        assert cruzado.status_code == 403 and grave_b.id not in cruzado.text
    _run(alertas_db, op)

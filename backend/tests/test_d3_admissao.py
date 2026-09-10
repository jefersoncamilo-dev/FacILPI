"""D.3: HTTP lifecycle, evidencias derivadas, RBAC, tenant e CAS real."""

import asyncio
import json
import os
from datetime import date

import httpx
import pytest
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .test_d3_admissao_migration import _engine, _migrate, _ref
from .test_d2_rotina import (
    _create_ilpi_user, _create_platform_user, _create_funcionario, _create_residente,
    _new_institution, _new_id, _headers, _grant, _setup_pais_vigente, PAIS6,
)
from src import main
from src.application import auth, admissoes
from src.infrastructure import models as m

ALL = {f"admissoes:{a}" for a in ("ler", "criar", "atualizar", "avancar", "reabrir", "concluir", "cancelar")}
DOMAIN = PAIS6 | {"residentes:ler", "residentes:criar", "documentos:ler", "documentos:criar", "documentos:atualizar",
                 "avaliacoes:criar", "quartos_leitos:criar", "quartos_leitos:atualizar"}
URL = "/api/admissoes/"


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def d3_db(request, tmp_path):
    ref = _ref(request, tmp_path)
    _migrate(ref)
    return ref


async def _client(ref, operation):
    engine = _engine(ref)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async def get_db():
        async with factory() as db:
            yield db
    main.app.dependency_overrides[main.get_db] = get_db
    auth._rate_store.clear()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver", follow_redirects=True) as client:
            async with factory() as db:
                await operation(client, db)
    finally:
        main.app.dependency_overrides.clear()
        await engine.dispose()


async def _setup(db, permissions=None):
    tenant = _new_institution("D3")
    user = await _create_ilpi_user(db, tenant, permissions=ALL | DOMAIN if permissions is None else permissions)
    resident = await _create_residente(db, tenant.id)
    employee = await _create_funcionario(db, tenant)
    await db.commit()
    return tenant, user, resident, employee, _headers(user, ilpi_id=tenant.id)


async def _create(client, h, resident, **kwargs):
    r = await client.post(URL, headers=h, json={"residente_id": resident.id, **kwargs})
    assert r.status_code == 201, r.text
    return r.json()


async def _action(client, h, obj, action, expected=200, **payload):
    r = await client.post(f"{URL}{obj['id']}/{action}", headers=h, json={"lock_version": obj["lock_version"], **payload})
    assert r.status_code == expected, r.text
    return r.json()


async def _until(client, h, obj, target):
    while obj["situacao"] != target:
        index = admissoes.ETAPAS.index(obj["situacao"])
        obj = await _action(client, h, obj, "avancar", etapa_destino=admissoes.ETAPAS[index + 1])
    return obj


async def _ready(client, db, *, documents=True):
    tenant, user, resident, employee, h = await _setup(db)
    obj = await _create(client, h, resident)
    if documents:
        r = await client.post("/api/documentos/", headers=h, json={"residente_id": resident.id, "tipo": "Identificacao", "obrigatorio": True})
        assert r.status_code == 201, r.text
        r = await client.put(f"/api/documentos/{r.json()['id']}", headers=h, json={"situacao": "validado"})
        assert r.status_code == 200, r.text
    obj = await _until(client, h, obj, "contrato")
    obj = await _action(client, h, obj, "contrato", motivo="Marco confirmado presencialmente")
    r = await client.post("/api/quartos_leitos/", headers=h, json={"quarto": "D3", "leito": "01"})
    assert r.status_code == 201, r.text
    bed_id = r.json()["id"]
    r = await client.post(f"/api/quartos_leitos/{bed_id}/alocar", headers=h, json={"residente_id": resident.id})
    assert r.status_code == 200, r.text
    pais_id, _ = await _setup_pais_vigente(client, h, resident.id, employee.id)
    obj = await _until(client, h, obj, "pais")
    return tenant, user, resident, employee, h, obj, bed_id, pais_id


def test_auth_rbac_payload_hostil_e_metodos(d3_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        obj = await _create(client, h, resident)
        none = await _create_ilpi_user(db, tenant, permissions=set(), profile_key="d3_none")
        reader = await _create_ilpi_user(db, tenant, permissions={"admissoes:ler"}, profile_key="d3_reader")
        await db.commit()
        calls = [("get", URL, None), ("get", URL + obj["id"], None),
                 ("get", URL + obj["id"] + "/historico", None), ("get", URL + obj["id"] + "/pendencias", None),
                 ("post", URL, {"residente_id": resident.id})]
        for action in ("avancar", "concluir", "reabrir", "cancelar", "desistir", "responsavel", "contrato", "requisitos-avaliacoes"):
            calls.append(("post", URL + obj["id"] + "/" + action,
                          {"lock_version": 0, "motivo": "M", "etapa_destino": "triagem"}))
        for method, url, payload in calls:
            kwargs = {"json": payload} if payload else {}
            assert (await client.request(method, url, **kwargs)).status_code == 401
            assert (await client.request(method, url, headers=_headers(none, ilpi_id=tenant.id), **kwargs)).status_code == 403
        assert (await client.get(URL, headers=_headers(reader, ilpi_id=tenant.id))).status_code == 200
        assert (await client.post(URL, headers=_headers(reader, ilpi_id=tenant.id), json={"residente_id": resident.id})).status_code == 403
        for key in ("ilpi_id", "instituicao_id", "autor_id", "responsavel_id", "situacao"):
            r = await client.post(URL, headers=h, json={"residente_id": resident.id, key: _new_id()})
            assert r.status_code == 422, r.text
            r = await client.post(URL + obj["id"] + "/avancar", headers=h,
                                  json={"lock_version": 0, "etapa_destino": "triagem", key: _new_id()})
            assert r.status_code == 422, r.text
        for method in ("put", "patch", "delete"):
            assert (await client.request(method, URL + obj["id"], headers=h, json={"situacao": "concluida"})).status_code == 405
        assert (await client.get(URL + obj["id"], headers=h)).json()["lock_version"] == 0
    asyncio.run(_client(d3_db, op))


def test_tenant_cadeia_e_responsavel(d3_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        other, _, res_b, emp_b, hb = await _setup(db)
        obj = await _create(client, h, resident, responsavel_funcionario_id=employee.id)
        ob = await _create(client, hb, res_b)
        for suffix in ("", "/historico", "/pendencias"):
            r = await client.get(URL + ob["id"] + suffix, headers=h)
            assert r.status_code == 404 and r.json()["detail"]["code"] == "RESOURCE_NOT_FOUND"
        for action, payload in (("avancar", {"etapa_destino": "triagem"}), ("concluir", {}), ("cancelar", {"motivo": "M"}),
                                ("desistir", {"motivo": "M"}), ("reabrir", {"motivo": "M"}),
                                ("responsavel", {"motivo": "M", "responsavel_funcionario_id": employee.id}),
                                ("contrato", {"motivo": "M"}), ("requisitos-avaliacoes", {"motivo": "M", "avaliacoes_requeridas": []})):
            await _action(client, h, ob, action, expected=404, **payload)
        assert (await client.post(URL, headers=h, json={"residente_id": res_b.id})).status_code == 404
        assert (await client.get(URL, headers=h, params={"residente_id": res_b.id})).status_code == 404
        assert {a["id"] for a in (await client.get(URL, headers=h)).json()} == {obj["id"]}
        await _action(client, h, obj, "responsavel", expected=404, motivo="Troca", responsavel_funcionario_id=emp_b.id)
        emp_b.situacao = "inativo"
        employee.situacao = "inativo"
        await db.commit()
        await _action(client, h, obj, "responsavel", expected=422, motivo="Troca", responsavel_funcionario_id=employee.id)
        obj = await _action(client, h, obj, "responsavel", motivo="Sem designacao", responsavel_funcionario_id=None)
        assert obj["responsavel_funcionario_id"] is None
        # Documento de outro residente, inclusive no mesmo tenant, nunca vira contrato.
        doc = m.Documento(id=_new_id(), residente_id=res_b.id, instituicao_id=other.id, tipo="Contrato")
        db.add(doc)
        await db.commit()
        obj = await _until(client, h, obj, "contrato")
        await _action(client, h, obj, "contrato", expected=404, motivo="M", documento_id=doc.id)
        assert (await client.get(URL + obj["id"] + "/pendencias", headers=h)).json()["documentos"] == []
    asyncio.run(_client(d3_db, op))


def test_pre_cadastro_vinculo_duplicidade_cpf_e_estado(d3_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        payload = {"nome": "Pessoa D3", "data_nascimento": "1940-01-01", "cpf": "529.982.247-25"}
        r = await client.post("/api/residentes/", headers=h, json=payload)
        assert r.status_code == 201, r.text
        assert (await client.post("/api/residentes/", headers=h, json=payload)).status_code == 409
        assert (await client.post(URL, headers=h, json={"residente_id": r.json()["id"]})).status_code == 201
        obj = await _create(client, h, resident)
        assert obj["situacao"] == "pre_cadastro" and obj["autor_id"] == user.id and obj["ilpi_id"] == tenant.id
        assert (await client.post(URL, headers=h, json={"residente_id": resident.id})).status_code == 409
        assert (await client.post(URL, headers=h, json={"residente_id": _new_id()})).status_code == 404
        active = await _create_residente(db, tenant.id)
        active.situacao = "Ativo"
        await db.commit()
        assert (await client.post(URL, headers=h, json={"residente_id": active.id})).status_code == 409
        count = await db.scalar(select(func.count()).select_from(m.Residente))
        assert count == 3  # somente o CRUD de Residentes cria pessoas
    asyncio.run(_client(d3_db, op))


def test_documentos_validacao_humana_sem_validade_automatica(d3_db):
    async def op(client, db):
        tenant, _, resident, _, h = await _setup(db)
        obj = await _create(client, h, resident)
        doc = m.Documento(id=_new_id(), instituicao_id=tenant.id, residente_id=resident.id, tipo="D3")
        db.add(doc)
        await db.commit()
        for required in (False, True):
            for state in ("pendente", "recebido", "rejeitado", "validado", "legado_desconhecido"):
                for expiry in (None, date(2000, 1, 1), date(2100, 1, 1)):
                    for file in (None, "registro.pdf"):
                        doc.obrigatorio, doc.situacao, doc.validade, doc.arquivo = required, state, expiry, file
                        await db.commit()
                        r = await client.get(URL + obj["id"] + "/pendencias", headers=h)
                        assert r.status_code == 200, r.text
                        projection = r.json()
                        pending = [p for p in projection["pendencias"] if p["codigo"] == "documentacao_pendente"]
                        # Contrato oficial: so validado cumpre; validade/arquivo nunca decidem.
                        assert bool(pending) == (required and state != "validado"), (required, state, expiry, file, pending)
                        assert all("vencido" not in p.get("motivo", "") for p in pending)
                        assert projection["documentos"][0]["situacao"] == state
                        assert projection["documentos"][0]["cumprido"] == (state == "validado")
                        assert "vencido" not in projection["documentos"][0]
                        assert projection["lock_version"] == 0
        # Sem documento obrigatorio, nenhuma pendencia documental e inventada.
        outro = await _create_residente(db, tenant.id)
        await db.commit()
        livre = await _create(client, h, outro)
        pendencias = (await client.get(URL + livre["id"] + "/pendencias", headers=h)).json()["pendencias"]
        assert not [p for p in pendencias if p["codigo"] == "documentacao_pendente"]
        await db.refresh(doc)
        assert (doc.situacao, doc.validade, doc.arquivo) == ("legado_desconhecido", date(2100, 1, 1), "registro.pdf")
        assert await db.scalar(select(func.count()).select_from(m.AdmissaoHistorico)) == 2
    asyncio.run(_client(d3_db, op))


def test_fluxo_explicito_pulos_e_marco_contrato(d3_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        obj = await _create(client, h, resident)
        await _action(client, h, obj, "avancar", expected=409, etapa_destino="pais")
        await _action(client, h, obj, "concluir", expected=409)
        await _action(client, h, obj, "contrato", expected=409, motivo="M")
        obj = await _until(client, h, obj, "documentacao")
        doc = m.Documento(id=_new_id(), instituicao_id=tenant.id, residente_id=resident.id, tipo="Contrato", obrigatorio=True, situacao="pendente")
        db.add(doc)
        await db.commit()
        await _action(client, h, obj, "avancar", expected=422, etapa_destino="avaliacoes")
        doc.situacao = "validado"
        await db.commit()
        obj = await _until(client, h, obj, "contrato")
        await _action(client, h, obj, "avancar", expected=422, etapa_destino="quarto_leito")
        obj = await _action(client, h, obj, "contrato", motivo="Validacao humana do marco", documento_id=doc.id)
        assert obj["contrato_documento_id"] == doc.id
        obj = await _until(client, h, obj, "quarto_leito")
        await _action(client, h, obj, "avancar", expected=422, etapa_destino="pais")
        assert await db.scalar(select(func.count()).select_from(m.Avaliacao)) == 0
        assert await db.scalar(select(func.count()).select_from(m.PlanoCuidados)) == 0
        assert await db.scalar(select(func.count()).select_from(m.QuartoLeito)) == 0
    asyncio.run(_client(d3_db, op))


def test_avaliacoes_requisitos_explicitos_sem_automacao(d3_db):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        obj = await _create(client, h, resident)
        projection = (await client.get(URL + obj["id"] + "/pendencias", headers=h)).json()
        assert projection["avaliacoes_requeridas"] == []
        req = {"tipo": "Social", "instrumento": "Entrevista", "origem": "Definicao individual confirmada pela ILPI"}
        obj = await _action(client, h, obj, "requisitos-avaliacoes", motivo="Definicao explicita", avaliacoes_requeridas=[req])
        obj = await _until(client, h, obj, "avaliacoes")
        await _action(client, h, obj, "avancar", expected=422, etapa_destino="contrato")
        another = await _create_residente(db, tenant.id)
        evaluation = m.Avaliacao(id=_new_id(), residente_id=another.id, ilpi_id=tenant.id, tipo="Social", instrumento="Entrevista", respostas="nao copiar")
        db.add(evaluation)
        await db.commit()
        await _action(client, h, obj, "avancar", expected=422, etapa_destino="contrato")
        evaluation.residente_id, evaluation.validade = resident.id, date(2000, 1, 1)
        await db.commit()
        await _action(client, h, obj, "avancar", expected=422, etapa_destino="contrato")
        evaluation.validade = None
        await db.commit()
        projection = (await client.get(URL + obj["id"] + "/pendencias", headers=h)).json()
        assert projection["avaliacoes_requeridas"][0]["avaliacao_ids"] == [evaluation.id]
        assert "respostas" not in projection["avaliacoes"][0]
        obj = await _action(client, h, obj, "avancar", etapa_destino="contrato")
        assert "respostas" not in obj and "grau_dependencia" not in obj
        assert await db.scalar(select(func.count()).select_from(m.GrauDependencia)) == 0
        assert await db.scalar(select(func.count()).select_from(m.PlanoCuidados)) == 0
    asyncio.run(_client(d3_db, op))


def test_conclusao_revalida_fontes_e_registra_auditoria(d3_db):
    async def op(client, db):
        tenant, user, resident, employee, h, obj, bed_id, pais_id = await _ready(client, db)
        # Estado mudou em outro modulo depois da etapa: conclusao precisa revalidar.
        doc = await db.scalar(select(m.Documento).where(m.Documento.residente_id == resident.id))
        doc.situacao = "rejeitado"
        await db.commit()
        body = await _action(client, h, obj, "concluir", expected=422)
        assert body["detail"]["pendencias"][0]["codigo"] == "documentacao_pendente"
        doc.situacao = "validado"
        await db.commit()
        # Validade passada nao bloqueia nesta fase: sem pendencia documental.
        doc.validade = date(2000, 1, 1)
        await db.commit()
        pendencias = (await client.get(URL + obj["id"] + "/pendencias", headers=h)).json()["pendencias"]
        assert not [p for p in pendencias if p["codigo"] == "documentacao_pendente"]
        doc.validade = None
        await db.commit()
        for model, id, field, value in ((m.QuartoLeito, bed_id, "residente_atual_id", None),
                                       (m.PlanoCuidados, pais_id, "situacao", "aprovado"),
                                       (m.Residente, resident.id, "nome", "")):
            row = await db.get(model, id)
            old = getattr(row, field)
            setattr(row, field, value)
            await db.commit()
            await _action(client, h, obj, "concluir", expected=422)
            setattr(row, field, old)
            await db.commit()
        await _action(client, h, obj, "avancar", expected=409, etapa_destino="concluida")
        completed = await _action(client, h, obj, "concluir")
        assert completed["situacao"] == "concluida" and completed["concluida_em"]
        history = (await client.get(URL + obj["id"] + "/historico", headers=h)).json()
        assert [r["lock_version"] for r in history] == list(range(completed["lock_version"] + 1))
        assert all(row["autor_id"] == user.id and row["ilpi_id"] == tenant.id for row in history)
        assert history[-1]["acao"] == "concluir" and history[-1]["etapa_origem"] == "pais"
        audits = (await db.scalars(select(m.Auditoria).where(m.Auditoria.registro_id == obj["id"]))).all()
        assert len(audits) == len(history)
        audit = next(a for a in audits if a.acao == "admissao.concluir")
        after = json.loads(audit.valores_posteriores)
        assert after["verificacao"]["pendencias"] == [] and after["verificacao"]["pais_ids"] == [pais_id]
        assert audit.usuario_id == user.id and audit.ilpi_id == tenant.id
        await db.refresh(resident)
        assert resident.situacao == "Em admissao" and resident.data_admissao is None
        for table in (m.Tarefa, m.ProgramacaoCuidado, m.Intercorrencia, m.Alerta, m.Familiar, m.Avaliacao):
            assert await db.scalar(select(func.count()).select_from(table)) == 0
    asyncio.run(_client(d3_db, op))


@pytest.mark.parametrize("action,state,stamp", [("cancelar", "cancelada", "cancelada_em"), ("desistir", "desistencia", "desistencia_em")])
def test_saidas_reabertura_preservam_evidencias(d3_db, action, state, stamp):
    async def op(client, db):
        tenant, user, resident, employee, h, obj, bed_id, pais_id = await _ready(client, db)
        for reason in (None, "", "   "):
            payload = {"lock_version": obj["lock_version"]}
            if reason is not None:
                payload["motivo"] = reason
            assert (await client.post(URL + obj["id"] + "/" + action, headers=h, json=payload)).status_code == 422
        terminal = await _action(client, h, obj, action, motivo="Decisao humana")
        assert terminal["situacao"] == state and terminal[stamp]
        await _action(client, h, terminal, "concluir", expected=409)
        await _action(client, h, terminal, "reabrir", expected=422, motivo=" ")
        reopened = await _action(client, h, terminal, "reabrir", motivo="Retomada autorizada")
        assert reopened["situacao"] == "pre_cadastro" and reopened[stamp] == terminal[stamp]
        assert reopened["contrato_registrado_em"] == terminal["contrato_registrado_em"]
        await _action(client, h, reopened, "reabrir", expected=409, motivo="Ja aberto")
        assert (await db.get(m.QuartoLeito, bed_id)).residente_atual_id == resident.id
        assert (await db.get(m.PlanoCuidados, pais_id)).situacao == "vigente"
        await db.refresh(resident)
        assert resident.situacao == "Em admissao"
        history = (await client.get(URL + obj["id"] + "/historico", headers=h)).json()
        assert history[-2]["acao"] == action and history[-1]["motivo"] == "Retomada autorizada"
        assert await db.scalar(select(func.count()).select_from(m.Documento)) == 1
    asyncio.run(_client(d3_db, op))


def test_platform_profissao_e_templates_sem_grants(d3_db):
    async def op(client, db):
        tenant, _, resident, _, h = await _setup(db)
        platform = await _create_platform_user(db)
        template = await db.scalar(select(m.Perfil).where(m.Perfil.chave == "platform_superuser", m.Perfil.ilpi_id.is_(None)))
        await _grant(db, template.id, ALL)  # mesmo catalogo adulterado nao supera barreira clinica
        professional = await _create_ilpi_user(db, tenant, permissions=set(), profile_key="d3_professional")
        employee = await db.scalar(select(m.Funcionario).where(m.Funcionario.usuario_id == professional.id))
        employee.profissao, employee.cargo = "Medico", "Responsavel tecnico"
        await db.commit()
        obj = await _create(client, h, resident)
        assert (await client.get(URL, headers=_headers(platform, scope="global"))).status_code == 403
        assert (await client.get(URL, headers=_headers(platform, ilpi_id=tenant.id))).status_code == 403
        assert (await client.get(URL, headers=_headers(professional, ilpi_id=tenant.id))).status_code == 403
        for key in ("ilpi_admin", "administrativo", "responsavel_tecnico", "cuidador", "enfermagem", "medico"):
            keys = set((await db.scalars(select(m.Permissao.chave).join(m.PerfilPermissao).join(m.Perfil)
                                        .where(m.Perfil.chave == key, m.Perfil.ilpi_id.is_(None)))).all())
            assert not keys & ALL
        # Atribuicao explicita, nao profissao, passa a permitir leitura.
        profile_id = await db.scalar(select(m.UsuarioIlpiPerfil.perfil_id).where(m.UsuarioIlpiPerfil.usuario_id == professional.id))
        await _grant(db, profile_id, {"admissoes:ler"})
        await db.commit()
        assert (await client.get(URL + obj["id"], headers=_headers(professional, ilpi_id=tenant.id))).status_code == 200
    asyncio.run(_client(d3_db, op))


def test_autoria_por_acao_e_reabertura_sem_duplicar_processo(d3_db):
    async def op(client, db):
        tenant, creator, resident, employee, h = await _setup(db)
        operator = await _create_ilpi_user(db, tenant, permissions=ALL, profile_key="d3_operator")
        await db.commit()
        ho = _headers(operator, ilpi_id=tenant.id)
        obj = await _create(client, h, resident)
        terminal = await _action(client, ho, obj, "cancelar", motivo="Decisao do operador")
        new = await _create(client, h, resident)
        await _action(client, ho, terminal, "reabrir", expected=409, motivo="Ja existe outro processo")
        await _action(client, h, new, "desistir", motivo="Preservar processo original")
        reopened = await _action(client, ho, terminal, "reabrir", motivo="Retomada do original")
        assert reopened["autor_id"] == creator.id
        history = (await client.get(URL + obj["id"] + "/historico", headers=h)).json()
        assert [row["autor_id"] for row in history] == [creator.id, operator.id, operator.id]
        audits = (await db.scalars(select(m.Auditoria).where(m.Auditoria.registro_id == obj["id"], m.Auditoria.acao != "admissao.criar"))).all()
        assert len(audits) == 2 and all(a.usuario_id == operator.id for a in audits)
        assert await db.scalar(select(func.count()).select_from(m.Residente)) == 1
    asyncio.run(_client(d3_db, op))


@pytest.mark.parametrize("race", ["avancar", "concluir", "reabrir", "cancelar_concluir", "criar"])
def test_concorrencia_real_cas(d3_db, race):
    async def op(client, db):
        if race in ("concluir", "cancelar_concluir", "reabrir"):
            tenant, user, resident, employee, h, obj, bed_id, pais_id = await _ready(client, db, documents=False)
            if race == "reabrir":
                obj = await _action(client, h, obj, "concluir")
        else:
            tenant, user, resident, employee, h = await _setup(db)
            obj = None if race == "criar" else await _create(client, h, resident)
        if race == "criar":
            calls = [client.post(URL, headers=h, json={"residente_id": resident.id}) for _ in range(2)]
        else:
            action = "concluir" if race == "cancelar_concluir" else race
            payload = {"lock_version": obj["lock_version"]}
            if race == "avancar":
                payload["etapa_destino"] = "triagem"
            if race == "reabrir":
                payload["motivo"] = "Retomada"
            calls = [client.post(URL + obj["id"] + "/" + action, headers=h, json=payload),
                     client.post(URL + obj["id"] + "/" + ("cancelar" if race == "cancelar_concluir" else action),
                                 headers=h, json={"lock_version": obj["lock_version"], "motivo": "Cancelamento"} if race == "cancelar_concluir" else payload)]
        responses = await asyncio.gather(*calls)
        assert sorted(r.status_code for r in responses) == [201 if race == "criar" else 200, 409], [r.text for r in responses]
        winner = next(r.json() for r in responses if r.status_code < 300)
        history = (await client.get(URL + winner["id"] + "/historico", headers=h)).json()
        assert len(history) == winner["lock_version"] + 1
        if obj:
            assert winner["lock_version"] == obj["lock_version"] + 1
            await _action(client, h, obj, "cancelar", expected=409, motivo="Payload obsoleto")
    asyncio.run(_client(d3_db, op))


def test_conclusao_serializa_alteracao_de_evidencia(d3_db, monkeypatch):
    async def op(client, db):
        tenant, user, resident, employee, h, obj, bed_id, pais_id = await _ready(client, db)
        read, release, changing = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original = AsyncSession.scalars
        async def pause(session, statement, *args, **kwargs):
            result = await original(session, statement, *args, **kwargs)
            if "FROM documentos" in str(statement) and "FOR UPDATE" in str(statement):
                read.set()
                await asyncio.wait_for(release.wait(), timeout=10)
            return result
        monkeypatch.setattr(AsyncSession, "scalars", pause)
        async def change():
            changing.set()
            await db.execute(update(m.Documento).where(m.Documento.residente_id == resident.id).values(situacao="rejeitado"))
            await db.commit()
        finish = asyncio.create_task(_action(client, h, obj, "concluir"))
        await asyncio.wait_for(read.wait(), timeout=10)
        change_task = asyncio.create_task(change())
        try:
            await changing.wait()
            await asyncio.sleep(0.15)
            assert not change_task.done(), "Evidencia deve permanecer travada durante conclusao"
        finally:
            release.set()
        completed, _ = await asyncio.wait_for(asyncio.gather(finish, change_task), timeout=15)
        assert completed["situacao"] == "concluida"
        # Projecao continua derivada: depois do commit a fonte pode mudar.
        pending = (await client.get(URL + obj["id"] + "/pendencias", headers=h)).json()["pendencias"]
        assert any(p["codigo"] == "documentacao_pendente" for p in pending)
    asyncio.run(_client(d3_db, op))

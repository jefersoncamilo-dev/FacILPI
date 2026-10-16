"""C5 HTTP/DB contract. The parent runner must set safe env before imports.

The router must expose src.application.medicacao.utcnow; only that clinical
clock is frozen, never JWT/security time. Every HTTP request gets its own DB
session through the existing _with_client helper, including concurrent writes.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from importlib import import_module

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from . import test_fase5a3b_sinais_vitais_rbac_tenant as h
from .test_c5_medicacao_migration import KEYS, _migrate, c5_migration_db

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
MED = "/api/medicamentos/"
PRE = "/api/prescricoes/"
DOSE = "/api/doses-previstas/"
ADM = "/api/administracoes/"


@pytest.fixture
def c5_db(c5_migration_db):
    _migrate(c5_migration_db)
    return c5_migration_db


@pytest.fixture
def clock(monkeypatch):
    module = import_module("src.application.medicacao")
    value = [NOW]
    monkeypatch.setattr(module, "utcnow", lambda: value[0])
    return value


async def _setup(db, permissions=None):
    ilpi = h._new_institution("ILPI C5")
    user = await h._create_ilpi_user(
        db, ilpi, permissions=KEYS if permissions is None else permissions,
        profile_key="c5_explicit", nome="Digitador C5",
    )
    resident = await h._create_residente(db, ilpi.id)
    await db.commit()
    return ilpi, user, resident, h._auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)


def _prescription(resident, medicine, **fields):
    return {
        "residente_id": resident.id, "medicamento_id": medicine["id"],
        "prescritor_nome": "Dra Externa", "prescritor_categoria": "medico",
        "dose": "1", "unidade": "comprimido", "via": "oral",
        "inicio": "2026-09-08", **fields,
    }


def _schedule(**fields):
    return {"horarios": ["12:01"], "timezone": "UTC", "vigencia_inicio": NOW.isoformat(), **fields}


def _outcome(dose, **fields):
    return {"dose_prevista_id": dose["id"], "resultado": "administrada",
            "ocorrido_em": (NOW + timedelta(minutes=2)).isoformat(), "quantidade_realizada": "1", **fields}


async def _post(client, path, headers, payload, status=201):
    response = await client.post(path, headers=headers, json=payload)
    assert response.status_code == status, response.text
    return response.json()


async def _chain(client, db, *, active=True, prescription=None, schedule=None):
    ilpi, user, resident, headers = await _setup(db)
    medicine = await _post(client, MED, headers, {"nome": "Medicamento C5", "unidade": "comprimido"})
    row = await _post(client, PRE, headers, _prescription(resident, medicine, **(prescription or {})))
    doses = []
    if active:
        row = await _post(client, PRE + row["id"] + "/ativar", headers, _schedule(**(schedule or {})), 200)
        result = await client.get(DOSE, headers=headers, params={"prescricao_id": row["id"]})
        assert result.status_code == 200, result.text
        doses = sorted(result.json(), key=lambda d: d["previsto_em"])
        assert doses
    return ilpi, user, resident, headers, medicine, row, doses


def _operations(resident, medicine, row, dose, admin):
    payload = _prescription(resident, medicine)
    return [
        ("medicamentos:ler", "GET", MED, None),
        ("medicamentos:ler", "GET", MED + medicine["id"], None),
        ("medicamentos:criar", "POST", MED, {"nome": "Outro medicamento"}),
        ("medicamentos:atualizar", "PATCH", MED + medicine["id"], {"nome": "Nome corrigido"}),
        ("prescricoes:ler", "GET", PRE, None),
        ("prescricoes:ler", "GET", PRE + row["id"], None),
        ("prescricoes:criar", "POST", PRE, payload),
        ("prescricoes:atualizar", "POST", PRE + row["id"] + "/ativar", _schedule()),
        ("prescricoes:atualizar", "POST", PRE + row["id"] + "/reconciliar", None),
        ("prescricoes:atualizar", "POST", PRE + row["id"] + "/suspender", {"motivo": "Suspensao"}),
        ("prescricoes:atualizar", "POST", PRE + row["id"] + "/encerrar", {"motivo": "Encerramento"}),
        ("prescricoes:atualizar", "POST", PRE + row["id"] + "/substituir",
         {"motivo": "Nova versao", "prescricao": payload, "programacao": _schedule()}),
        ("doses_previstas:ler", "GET", DOSE, None),
        ("doses_previstas:ler", "GET", DOSE + dose["id"], None),
        ("administracoes:ler", "GET", ADM, None),
        ("administracoes:ler", "GET", ADM + admin["id"], None),
        ("administracoes:criar", "POST", ADM, _outcome(dose)),
        ("administracoes:corrigir", "POST", ADM + admin["id"] + "/estornar", {"motivo": "Correcao"}),
    ]


@pytest.mark.parametrize("mode", ["anonymous", "no_permission", "platform", "platform_hostile_grants", "password_change"])
def test_auth_permissions_platform(c5_db, clock, mode):
    async def scenario(client, db):
        _, user, resident, headers = await _setup(db, permissions=set())
        if mode == "anonymous":
            headers = {}
        elif mode.startswith("platform"):
            user = await h._create_platform_user(db)
            if mode == "platform_hostile_grants":
                profile = (await db.execute(select(h.m.Perfil).where(h.m.Perfil.chave == "platform_superuser"))).scalar_one()
                await h._grant_permissions(db, profile.id, KEYS)
            await db.commit()
            headers = h._auth_headers(user, scope="global")
        elif mode == "password_change":
            user.exige_troca_senha = True
            await db.commit()
        dummy = {"id": h._new_id()}
        for _, method, path, payload in _operations(resident, dummy, dummy, dummy, dummy):
            response = await client.request(method, path, headers=headers, json=payload)
            assert response.status_code in ({401, 403} if mode == "anonymous" else {403}), response.text
    asyncio.run(h._with_client(c5_db, scenario))


@pytest.mark.parametrize("permission", sorted(KEYS))
def test_explicit_permissions_are_independent(c5_db, clock, permission):
    async def scenario(client, db):
        ilpi, _, resident, owner, medicine, row, doses = await _chain(client, db)
        clock[0] = NOW + timedelta(minutes=2)
        admin = await _post(client, ADM, owner, _outcome(doses[0]))
        user = await h._create_ilpi_user(db, ilpi, permissions={permission}, profile_key="c5_single")
        await db.commit()
        headers = h._auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        for needed, method, path, payload in _operations(resident, medicine, row, doses[0], admin):
            response = await client.request(method, path, headers=headers, json=payload)
            if needed != permission:
                assert response.status_code == 403, (permission, path, response.text)
            else:
                # Existing/transitioned rows may conflict, but authorization must pass.
                assert response.status_code in {200, 201, 409}, (permission, path, response.text)
    asyncio.run(h._with_client(c5_db, scenario))


def test_tenant_isolation_entire_chain(c5_db, clock):
    async def scenario(client, db):
        _, _, resident, headers, medicine, row, doses = await _chain(client, db)
        other, _, other_resident, foreign, other_med, other_row, other_doses = await _chain(client, db)
        clock[0] = NOW + timedelta(minutes=2)
        own_admin = await _post(client, ADM, headers, _outcome(doses[0]))
        other_admin = await _post(client, ADM, foreign, _outcome(other_doses[0]))
        for base, own_ids in ((MED, {medicine["id"]}), (PRE, {row["id"]}),
                              (DOSE, {d["id"] for d in doses}), (ADM, {own_admin["id"]})):
            response = await client.get(base, headers=headers, params={"ilpi_id": other.id})
            assert response.status_code == 200
            assert {r["id"] for r in response.json()} == own_ids
        for _, method, path, payload in _operations(other_resident, other_med, other_row, other_doses[0], other_admin):
            if method == "GET" and path.endswith("/") or path == MED:
                continue
            response = await client.request(method, path, headers=headers, json=payload)
            assert response.status_code == 404, (path, response.text)
        for fields in ({"residente_id": other_resident.id}, {"medicamento_id": other_med["id"]}):
            response = await client.post(PRE, headers=headers, json=_prescription(resident, medicine, **fields))
            assert response.status_code == 404
        for base, filters in ((PRE, {"residente_id": other_resident.id}),
                              (DOSE, {"residente_id": other_resident.id}),
                              (DOSE, {"prescricao_id": other_row["id"]}),
                              (ADM, {"residente_id": other_resident.id}),
                              (ADM, {"prescricao_id": other_row["id"]})):
            assert (await client.get(base, headers=headers, params=filters)).status_code == 404
        assert (await client.get(ADM + other_admin["id"], headers=foreign)).json() == other_admin
    asyncio.run(h._with_client(c5_db, scenario))


@pytest.mark.parametrize("field", ["ilpi_id", "instituicao_id", "autor", "autor_id", "executor", "executor_id", "prn", "intervalo"])
def test_strict_payloads_reject_spoofing(c5_db, clock, field):
    async def scenario(client, db):
        _, _, resident, headers, medicine, row, doses = await _chain(client, db)
        clock[0] = NOW + timedelta(minutes=2)
        admin = await _post(client, ADM, headers, _outcome(doses[0]))
        for _, method, path, payload in _operations(resident, medicine, row, doses[0], admin):
            if method == "GET" or payload is None:
                continue
            response = await client.request(method, path, headers=headers, json={**payload, field: "hostile"})
            assert response.status_code == 422, (path, field, response.text)
        response = await client.post(ADM + admin["id"] + "/estornar", headers=headers, json={
            "motivo": "Correcao", "substituto": {"resultado": "recusada", "justificativa": "Recusa",
            "ocorrido_em": clock[0].isoformat(), field: "hostile"},
        })
        assert response.status_code == 422
    asyncio.run(h._with_client(c5_db, scenario))


@pytest.mark.parametrize("fields", [
    {"dose": "0"}, {"dose": "-1"}, {"dose": "NaN"}, {"dose": "1 comprimido"},
    {"prescritor_nome": " "}, {"prescritor_categoria": " "}, {"unidade": " "}, {"via": " "},
    {"prescritor_conselho": "CRM"}, {"prescritor_numero": "123"}, {"prescritor_uf": "SP"},
    {"prescritor_conselho": "CRM", "prescritor_numero": "123"},
    {"termino": "2026-09-07"}, {"frequencia": "PRN"}, {"frequencia": "SOS"},
    {"frequencia": "se necessario"}, {"frequencia": "8/8h"},
])
def test_invalid_prescription(c5_db, clock, fields):
    async def scenario(client, db):
        _, _, resident, headers = await _setup(db)
        medicine = await _post(client, MED, headers, {"nome": "Medicamento"})
        response = await client.post(PRE, headers=headers, json=_prescription(resident, medicine, **fields))
        assert response.status_code == 422, response.text
        assert (await db.execute(select(func.count()).select_from(h.m.Prescricao))).scalar_one() == 0
    asyncio.run(h._with_client(c5_db, scenario))


def test_snapshot_author_prescriber_and_inactive_medicine(c5_db, clock):
    async def scenario(client, db):
        ilpi, user, resident, headers, medicine, row, _ = await _chain(client, db, active=False, prescription={
            "prescritor_conselho": "CRM", "prescritor_numero": "12345", "prescritor_uf": "SP",
        })
        assert row["situacao"] == "rascunho" and row["autor_id"] == user.id
        assert row["prescritor_nome"] == "Dra Externa" != user.nome
        assert row["medicamento_snapshot"]["nome"] == medicine["nome"]
        assert medicine["autor_id"] == user.id and medicine["ilpi_id"] == ilpi.id
        result = await client.patch(MED + medicine["id"], headers=headers, json={"nome": "Nome alterado", "situacao": "inativo"})
        assert result.status_code == 200
        assert (await client.get(PRE + row["id"], headers=headers)).json() == row
        assert (await client.post(PRE, headers=headers, json=_prescription(resident, medicine))).status_code == 409
        assert (await client.post(PRE + row["id"] + "/ativar", headers=headers, json=_schedule())).status_code == 409
        assert (await client.patch(MED + medicine["id"], headers=headers, json={"situacao": "ativo"})).status_code == 200
        for base, identifier in ((MED, medicine["id"]), (PRE, row["id"])):
            for method in ("PUT", "DELETE"):
                assert (await client.request(method, base + identifier, headers=headers)).status_code == 405
    asyncio.run(h._with_client(c5_db, scenario))


@pytest.mark.parametrize("fields", [
    {"horarios": []}, {"horarios": ["12:01", "12:01"]}, {"horarios": ["24:00"]},
    {"horarios": ["8:00"]}, {"horarios": ["12:01:00"]}, {"timezone": "Not/AZone"},
    {"vigencia_inicio": "2026-09-08T12:00:00"}, {"vigencia_fim": "2026-09-09T12:00:00"},
    {"vigencia_inicio": "2026-09-07T12:00:00Z"}, {"vigencia_fim": "2026-09-08T11:00:00Z"},
    {"prn": True}, {"intervalo": 8},
])
def test_invalid_activation_is_atomic(c5_db, clock, fields):
    async def scenario(client, db):
        _, _, _, headers, _, row, _ = await _chain(client, db, active=False)
        result = await client.post(PRE + row["id"] + "/ativar", headers=headers, json=_schedule(**fields))
        assert result.status_code == 422, result.text
        assert (await client.get(PRE + row["id"], headers=headers)).json() == row
        for model in (h.m.ProgramacaoMedicacao, h.m.DosePrevista):
            assert (await db.execute(select(func.count()).select_from(model))).scalar_one() == 0
    asyncio.run(h._with_client(c5_db, scenario))


@pytest.mark.parametrize("limited", [False, True])
def test_seven_day_horizon_clipped_end_and_reconciliation(c5_db, clock, limited):
    async def scenario(client, db):
        end = NOW + timedelta(days=2, minutes=2)
        _, user, _, headers, _, row, doses = await _chain(
            client, db, prescription={"termino": "2026-09-10"} if limited else None,
            schedule={"vigencia_fim": end.isoformat()} if limited else None,
        )
        assert row["ativado_por"] == user.id
        assert row["programacao"]["autor_id"] == user.id
        expected = [NOW + timedelta(days=d, minutes=1) for d in range(3 if limited else 7)]
        assert [datetime.fromisoformat(d["previsto_em"].replace("Z", "+00:00")) for d in doses] == expected
        assert all(d["pendente"] is True for d in doses)
        for _ in range(2):
            response = await client.post(PRE + row["id"] + "/reconciliar", headers=headers)
            assert response.status_code == 200, response.text
            current = (await client.get(DOSE, headers=headers, params={"prescricao_id": row["id"]})).json()
            assert {d["id"] for d in current} == {d["id"] for d in doses}
        clock[0] = NOW + timedelta(days=1)
        assert (await client.post(PRE + row["id"] + "/reconciliar", headers=headers)).status_code == 200
        current = (await client.get(DOSE, headers=headers, params={"prescricao_id": row["id"]})).json()
        assert len(current) == (3 if limited else 8)
        assert {d["id"] for d in doses} <= {d["id"] for d in current}
        assert len({d["previsto_em"] for d in current}) == len(current)
        assert (await client.post(PRE + row["id"] + "/ativar", headers=headers, json=_schedule())).status_code == 409
    asyncio.run(h._with_client(c5_db, scenario))


@pytest.mark.parametrize("result", ["administrada", "recusada", "omitida"])
def test_outcomes_executor_pending_and_duplicate(c5_db, clock, result):
    async def scenario(client, db):
        _, user, resident, headers, _, row, doses = await _chain(client, db)
        clock[0] = NOW + timedelta(minutes=2)
        payload = _outcome(doses[0], resultado=result)
        if result != "administrada":
            payload.pop("quantidade_realizada")
            payload["justificativa"] = "Motivo registrado"
        admin = await _post(client, ADM, headers, payload)
        assert admin["executor_id"] == user.id and admin["resultado"] == result
        assert admin["residente_id"] == resident.id and admin["prescricao_id"] == row["id"]
        assert (await client.get(ADM + admin["id"], headers=headers)).json() == admin
        detail = await client.get(DOSE + doses[0]["id"], headers=headers)
        assert detail.status_code == 200 and detail.json()["pendente"] is False
        pending = (await client.get(DOSE, headers=headers, params={"pendentes": "true", "residente_id": resident.id})).json()
        assert doses[0]["id"] not in {d["id"] for d in pending}
        assert (await client.post(ADM, headers=headers, json=payload)).status_code == 409
        for method in ("PUT", "PATCH", "DELETE"):
            assert (await client.request(method, ADM + admin["id"], headers=headers, json=payload)).status_code == 405
    asyncio.run(h._with_client(c5_db, scenario))


@pytest.mark.parametrize("fields", [
    {"quantidade_realizada": None}, {"quantidade_realizada": "0"}, {"quantidade_realizada": "-1"},
    {"quantidade_realizada": "NaN"}, {"resultado": "recusada", "justificativa": " "},
    {"resultado": "omitida", "justificativa": None}, {"resultado": "pendente"},
    {"ocorrido_em": "2026-09-08T12:02:00"},
    {"ocorrido_em": "2026-09-08T12:03:00Z"},
    {"ocorrido_em": "2026-09-08T11:59:00Z"},
])
def test_invalid_outcome_does_not_resolve_dose(c5_db, clock, fields):
    async def scenario(client, db):
        _, _, _, headers, _, _, doses = await _chain(client, db)
        clock[0] = NOW + timedelta(minutes=2)
        response = await client.post(ADM, headers=headers, json=_outcome(doses[0], **fields))
        assert response.status_code == 422, response.text
        assert (await db.execute(select(func.count()).select_from(h.m.Administracao))).scalar_one() == 0
        assert (await client.get(DOSE + doses[0]["id"], headers=headers)).json()["pendente"] is True
    asyncio.run(h._with_client(c5_db, scenario))


def test_ocorrido_antes_do_previsto_permitido(c5_db, clock):
    async def scenario(client, db):
        clock[0] = NOW
        _, _, _, headers, _, _, doses = await _chain(client, db)
        clock[0] = NOW + timedelta(minutes=2)
        early = (NOW + timedelta(seconds=30)).isoformat()
        # administrada antes do previsto é permitida (previsto 12:01, ocorrido 12:00:30)
        response = await client.post(ADM, headers=headers, json=_outcome(doses[0], ocorrido_em=early))
        assert response.status_code == 201, response.text
        assert response.json()["resultado"] == "administrada"
        assert (await client.get(DOSE + doses[0]["id"], headers=headers)).json()["pendente"] is False
        # recusada antes do previsto também é permitida em dose fresca
        clock[0] = NOW
        _, _, _, headers2, _, _, doses2 = await _chain(client, db)
        clock[0] = NOW + timedelta(minutes=2)
        early2 = (NOW + timedelta(seconds=30)).isoformat()
        payload2 = {"dose_prevista_id": doses2[0]["id"], "resultado": "recusada", "justificativa": "Recusa precoce", "ocorrido_em": early2}
        response2 = await client.post(ADM, headers=headers2, json=payload2)
        assert response2.status_code == 201, response2.text
        assert response2.json()["resultado"] == "recusada"
        # antes da ativação continua bloqueado (ocorrido 11:59 < ativação 12:00)
        clock[0] = NOW
        _, _, _, headers3, _, _, doses3 = await _chain(client, db)
        clock[0] = NOW + timedelta(minutes=2)
        before_activation = (NOW - timedelta(minutes=1)).isoformat()
        assert (await client.post(ADM, headers=headers3, json=_outcome(doses3[0], ocorrido_em=before_activation))).status_code == 422
    asyncio.run(h._with_client(c5_db, scenario))


@pytest.mark.parametrize("replacement", [False, True])
def test_correction_preserves_clinical_history(c5_db, clock, replacement):
    async def scenario(client, db):
        ilpi, _, _, headers, _, _, doses = await _chain(client, db)
        clock[0] = NOW + timedelta(minutes=2)
        original = await _post(client, ADM, headers, _outcome(doses[0], observacao="Original"))
        editor = await h._create_ilpi_user(db, ilpi, permissions=KEYS, profile_key="c5_editor")
        await db.commit()
        edit_headers = h._auth_headers(editor, scope="ilpi", ilpi_id=ilpi.id)
        payload = {"motivo": "Erro de registro"}
        if replacement:
            payload["substituto"] = {"resultado": "recusada", "justificativa": "Recusa confirmada", "ocorrido_em": clock[0].isoformat()}
        response = await client.post(ADM + original["id"] + "/estornar", headers=edit_headers, json=payload)
        assert response.status_code == 200, response.text
        stored = (await client.get(ADM + original["id"], headers=headers)).json()
        for key in ("executor_id", "resultado", "ocorrido_em", "quantidade_realizada", "justificativa", "observacao", "registrado_em"):
            assert stored[key] == original[key]
        assert stored["estornado_por"] == editor.id and stored["estornado_em"]
        assert stored["motivo_estorno"] == payload["motivo"]
        history = (await client.get(ADM, headers=headers)).json()
        assert len(history) == (2 if replacement else 1)
        if replacement:
            new = next(r for r in history if r["id"] != original["id"])
            assert new["substitui_id"] == original["id"] and new["executor_id"] == editor.id
            assert new["resultado"] == "recusada" and new["dose_prevista_id"] == doses[0]["id"]
        assert (await client.get(DOSE + doses[0]["id"], headers=headers)).json()["pendente"] is (not replacement)
        assert (await client.post(ADM + original["id"] + "/estornar", headers=edit_headers, json=payload)).status_code == 409
    asyncio.run(h._with_client(c5_db, scenario))


@pytest.mark.parametrize("action,state", [("suspender", "suspensa"), ("encerrar", "encerrada")])
def test_stop_cancels_only_unresolved_without_automation(c5_db, clock, action, state):
    async def scenario(client, db):
        _, user, _, headers, _, row, doses = await _chain(client, db)
        user_id = user.id
        models = (h.m.Tarefa, h.m.Alerta, h.m.Intercorrencia, h.m.PlanoCuidados)
        before = [(await db.execute(select(func.count()).select_from(model))).scalar_one() for model in models]
        await db.rollback()
        clock[0] = NOW + timedelta(minutes=2)
        admin = await _post(client, ADM, headers, _outcome(doses[0]))
        response = await client.post(PRE + row["id"] + "/" + action, headers=headers, json={"motivo": "Ordem clinica"})
        assert response.status_code == 200 and response.json()["situacao"] == state
        current = (await client.get(DOSE, headers=headers)).json()
        for dose in current:
            if dose["id"] == doses[0]["id"]:
                assert dose["situacao"] == "prevista" and dose["pendente"] is False
            else:
                assert dose["situacao"] == "cancelada" and dose["pendente"] is False
                assert dose["cancelado_por"] == user_id and dose["motivo_cancelamento"]
        assert (await client.get(ADM + admin["id"], headers=headers)).json() == admin
        clock[0] = NOW + timedelta(days=1, minutes=2)
        assert (await client.post(ADM, headers=headers, json=_outcome(doses[1], ocorrido_em=clock[0].isoformat()))).status_code == 409
        after = [(await db.execute(select(func.count()).select_from(model))).scalar_one() for model in models]
        assert before == after
    asyncio.run(h._with_client(c5_db, scenario))


def test_expired_prescription_blocks_backdated_administration(c5_db, clock):
    async def scenario(client, db):
        _, _, _, headers, _, _, doses = await _chain(client, db, prescription={"termino": "2026-09-08"},
            schedule={"vigencia_fim": "2026-09-08T12:03:00Z"})
        clock[0] = NOW + timedelta(days=1)
        response = await client.post(ADM, headers=headers, json=_outcome(doses[0]))
        assert response.status_code == 409, response.text
    asyncio.run(h._with_client(c5_db, scenario))


def test_new_version_preserves_previous_and_forbids_forks(c5_db, clock):
    async def scenario(client, db):
        _, user, resident, headers, medicine, old, doses = await _chain(client, db)
        payload = {"motivo": "Ajuste de dose", "prescricao": _prescription(resident, medicine, dose="2", prescritor_nome="Dr Segundo"),
                   "programacao": _schedule(horarios=["12:05"])}
        response = await client.post(PRE + old["id"] + "/substituir", headers=headers, json=payload)
        assert response.status_code == 201, response.text
        new = response.json()
        assert new["id"] != old["id"] and new["anterior_id"] == old["id"]
        assert new["situacao"] == "ativa" and new["autor_id"] == user.id
        assert new["prescritor_nome"] == "Dr Segundo" and Decimal(new["dose"]) == 2
        previous = (await client.get(PRE + old["id"], headers=headers)).json()
        assert previous["situacao"] == "substituida"
        for key in ("dose", "prescritor_nome", "autor_id", "medicamento_snapshot"):
            assert previous[key] == old[key]
        assert (await client.post(PRE + old["id"] + "/substituir", headers=headers, json=payload)).status_code == 409
        assert all(d["situacao"] == "cancelada" for d in (await client.get(DOSE, headers=headers, params={"prescricao_id": old["id"]})).json())
    asyncio.run(h._with_client(c5_db, scenario))


@pytest.mark.parametrize("competitor", ["recusada", "suspender"])
def test_concurrent_writes_use_independent_sessions(c5_db, clock, competitor):
    async def scenario(client, db):
        _, _, _, headers, _, row, doses = await _chain(client, db)
        clock[0] = NOW + timedelta(minutes=2)
        start = asyncio.Event()

        async def request(path, payload):
            await start.wait()
            return await client.post(path, headers=headers, json=payload)

        first = asyncio.create_task(request(ADM, _outcome(doses[0])))
        second = asyncio.create_task(request(
            ADM if competitor == "recusada" else PRE + row["id"] + "/suspender",
            _outcome(doses[0], resultado="recusada", justificativa="Recusa") if competitor == "recusada" else {"motivo": "Suspensao concorrente"},
        ))
        start.set()
        responses = await asyncio.wait_for(asyncio.gather(first, second), timeout=30)
        if competitor == "recusada":
            assert sorted(r.status_code for r in responses) == [201, 409], [r.text for r in responses]
        else:
            assert responses[1].status_code == 200, responses[1].text
            assert responses[0].status_code in {201, 409}, responses[0].text
        admins = (await client.get(ADM, headers=headers)).json()
        assert len(admins) == (1 if responses[0].status_code == 201 or competitor == "recusada" else 0)
        dose = (await client.get(DOSE + doses[0]["id"], headers=headers)).json()
        assert dose["pendente"] is False
        assert dose["situacao"] == ("prevista" if admins else "cancelada")
    asyncio.run(h._with_client(c5_db, scenario))


@pytest.mark.parametrize("violation", ["tenant", "duplicate_outcome", "duplicate_schedule", "duplicate_dose", "fork"])
def test_database_constraints_enforce_chain(c5_db, clock, violation):
    async def scenario(client, db):
        ilpi, user, resident, headers, medicine, row, doses = await _chain(client, db)
        other, _, _, _ = await _setup(db)
        clock[0] = NOW + timedelta(minutes=2)
        await _post(client, ADM, headers, _outcome(doses[0]))
        if db.bind.dialect.name == "sqlite":
            await db.execute(text("PRAGMA foreign_keys=ON"))
            assert (await db.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                if violation == "tenant":
                    await db.execute(update(h.m.DosePrevista).where(h.m.DosePrevista.id == doses[0]["id"]).values(ilpi_id=other.id))
                elif violation == "duplicate_outcome":
                    db.add(h.m.Administracao(id=h._new_id(), ilpi_id=ilpi.id, residente_id=resident.id,
                        prescricao_id=row["id"], dose_prevista_id=doses[0]["id"], resultado="recusada",
                        ocorrido_em=clock[0], executor_id=user.id, justificativa="Duplicado"))
                elif violation == "duplicate_schedule":
                    db.add(h.m.ProgramacaoMedicacao(id=h._new_id(), ilpi_id=ilpi.id, residente_id=resident.id,
                        prescricao_id=row["id"], horarios=["13:00"], timezone="UTC", vigencia_inicio=NOW, autor_id=user.id))
                elif violation == "duplicate_dose":
                    db.add(h.m.DosePrevista(id=h._new_id(), ilpi_id=ilpi.id, residente_id=resident.id,
                        prescricao_id=row["id"], programacao_id=doses[0]["programacao_id"], previsto_em=NOW + timedelta(minutes=1)))
                else:
                    for _ in range(2):
                        db.add(h.m.Prescricao(id=h._new_id(), ilpi_id=ilpi.id, residente_id=resident.id,
                            medicamento_id=medicine["id"], prescritor="Prescritor", dose="1", inicio=NOW.date(), anterior_id=row["id"]))
                await db.flush()
        await db.rollback()
    asyncio.run(h._with_client(c5_db, scenario))

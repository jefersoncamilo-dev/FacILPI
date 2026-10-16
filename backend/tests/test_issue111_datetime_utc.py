"""#111: datas com hora sempre em UTC e com fuso, em SQLite e PostgreSQL descartaveis.

O SQLite nao guarda fuso: antes do `UtcDateTime`, `DateTime(timezone=True)`
voltava sem tzinfo, a API devolvia o horario sem `Z` e o navegador o lia como
hora local, exibindo +3 h em Brasilia. Horario com offset diferente de UTC era
gravado como hora de relogio, sem conversao.
"""

import asyncio
import re
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import select

from .test_fase5a3b_sinais_vitais_rbac_tenant import (
    _auth_headers, _create_ilpi_user, _create_residente, _new_institution,
    _with_client, m, sinais_db,  # noqa: F401 - fixture reutilizada
)

# Data com hora sem fuso: exatamente o formato que o navegador interpreta como hora local.
NAIVE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$")

PERMISSOES = {
    "residentes:ler",
    "avaliacoes:ler", "avaliacoes:criar",
    "sinais_vitais:ler", "sinais_vitais:criar",
    "intercorrencias:ler", "intercorrencias:criar",
    "documentos:ler", "documentos:criar",
    "quartos_leitos:ler", "quartos_leitos:criar", "quartos_leitos:atualizar",
}


def _naive_strings(value, path="$"):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _naive_strings(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _naive_strings(item, f"{path}[{index}]")
    elif isinstance(value, str) and NAIVE_ISO.match(value):
        yield f"{path}={value}"


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None, value
    return parsed


async def _setup(db):
    ilpi = _new_institution("ILPI #111")
    db.add(ilpi)
    await db.flush()
    user = await _create_ilpi_user(db, ilpi, permissions=PERMISSOES)
    resident = await _create_residente(db, ilpi.id)
    await db.commit()
    return ilpi, resident, _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)


def test_every_datetime_column_uses_utc_type():
    # Guarda contra regressao: coluna nova com `DateTime` puro voltaria sem fuso no SQLite.
    plain = [
        f"{table.name}.{column.name}"
        for table in m.Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, sa.DateTime)
    ]
    assert plain == []
    utc = [c for t in m.Base.metadata.tables.values() for c in t.columns if isinstance(c.type, m.UtcDateTime)]
    assert utc and all(c.type.impl.timezone for c in utc)


def test_reported_case_avaliacao_returns_utc_instant(sinais_db):
    # Caso relatado: avaliacao das 04:32Z aparecia como 04:32 local (01:32 em Brasilia).
    async def scenario(client, db):
        _, resident, headers = await _setup(db)
        sent = "2026-09-26T04:32:57.524088Z"
        created = await client.post("/api/avaliacoes/", headers=headers, json={
            "residente_id": resident.id, "tipo": "Katz", "data": sent,
        })
        assert created.status_code == 201, created.text
        listed = await client.get("/api/avaliacoes/", headers=headers)
        assert listed.status_code == 200, listed.text
        (row,) = [r for r in listed.json() if r["id"] == created.json()["id"]]
        assert not NAIVE_ISO.match(row["data"]), row["data"]
        assert _instant(row["data"]) == _instant(sent)
    asyncio.run(_with_client(sinais_db, scenario))


def test_offset_input_is_converted_to_utc_before_storing(sinais_db):
    # 07:30 em Brasilia (-03:00) e 10:30 UTC; antes era gravado como 07:30 de relogio.
    async def scenario(client, db):
        _, resident, headers = await _setup(db)
        created = await client.post("/api/sinais-vitais/", headers=headers, json={
            "residente_id": resident.id, "temperatura": 36.5, "data": "2026-09-26T07:30:00-03:00",
        })
        assert created.status_code == 201, created.text
        body = created.json()
        assert _instant(body["data"]) == datetime(2026, 9, 26, 10, 30, tzinfo=timezone.utc)
        read = await client.get(f"/api/sinais-vitais/{body['id']}", headers=headers)
        assert read.status_code == 200, read.text
        assert _instant(read.json()["data"]) == datetime(2026, 9, 26, 10, 30, tzinfo=timezone.utc)
        stored = (await db.execute(select(m.SinalVital.data).where(m.SinalVital.id == body["id"]))).scalar_one()
        assert stored.tzinfo is not None
        assert stored == datetime(2026, 9, 26, 10, 30, tzinfo=timezone.utc)
    asyncio.run(_with_client(sinais_db, scenario))


def test_naive_input_is_treated_as_utc(sinais_db):
    # Contrato atual preservado: data sem fuso na entrada continua aceita e vale como UTC.
    async def scenario(client, db):
        _, resident, headers = await _setup(db)
        created = await client.post("/api/sinais-vitais/", headers=headers, json={
            "residente_id": resident.id, "temperatura": 36.5, "data": "2026-09-26T10:30:00",
        })
        assert created.status_code == 201, created.text
        assert _instant(created.json()["data"]) == datetime(2026, 9, 26, 10, 30, tzinfo=timezone.utc)
    asyncio.run(_with_client(sinais_db, scenario))


def test_listings_never_return_datetime_without_timezone(sinais_db):
    async def scenario(client, db):
        _, resident, headers = await _setup(db)
        for path, payload in (
            ("/api/avaliacoes/", {"residente_id": resident.id, "tipo": "Katz"}),
            ("/api/sinais-vitais/", {"residente_id": resident.id, "temperatura": 36.5}),
            ("/api/intercorrencias/", {"residente_id": resident.id, "tipo": "queda", "gravidade": "leve"}),
            ("/api/documentos/", {"residente_id": resident.id, "tipo": "RG"}),
            ("/api/quartos_leitos/", {"quarto": "01", "leito": "A"}),
        ):
            response = await client.post(path, headers=headers, json=payload)
            assert response.status_code in (200, 201), (path, response.text)
            if path == "/api/quartos_leitos/":
                leito_id = response.json()["id"]
        alocado = await client.post(f"/api/quartos_leitos/{leito_id}/alocar", headers=headers,
                                    json={"residente_id": resident.id})
        assert alocado.status_code == 200, alocado.text

        encontrados = []
        for path in ("/api/residentes/", "/api/avaliacoes/", "/api/sinais-vitais/", "/api/intercorrencias/",
                     "/api/documentos/", "/api/quartos_leitos/"):
            listed = await client.get(path, headers=headers)
            assert listed.status_code == 200, (path, listed.text)
            assert listed.json(), path
            encontrados += [f"{path} {hit}" for hit in _naive_strings(listed.json())]
        assert encontrados == []
    asyncio.run(_with_client(sinais_db, scenario))

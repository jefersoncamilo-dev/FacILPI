"""029: autor_id em avaliacoes, sinais vitais e intercorrencias, preenchido so pela auditoria.

Bancos descartaveis apenas. PostgreSQL reaproveita o alvo da D.3
(D3_TEST_POSTGRES_URL, facilpi_d3_test): cada teste recria o schema, como os
demais arquivos que dividem um database.
"""

import asyncio
import json
import os
import pathlib
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

BACKEND = pathlib.Path(__file__).resolve().parents[1]
BEFORE = "028_alerta_expirado"
HEAD = "029_autoria_autor_id"
TABELAS = ("avaliacoes", "sinais_vitais", "intercorrencias")


def _url(ref):
    if isinstance(ref, pathlib.Path):
        resolved = ref.resolve()
        assert resolved.name.startswith("a29-") and resolved.suffix == ".db"
        assert not resolved.is_relative_to(BACKEND.parent)
        return f"sqlite+aiosqlite:///{resolved.as_posix()}"
    url = make_url(ref)
    assert url.get_backend_name() == "postgresql"
    assert url.host == "127.0.0.1" and url.port == 55486 and url.database == "facilpi_d3_test"
    assert not url.query
    return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)


def _migrate(ref, target=HEAD, command="upgrade"):
    url = _url(ref)
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    env.pop("APP_DATABASE_URL", None)
    script = ("import sys; from types import SimpleNamespace; from alembic.config import Config; "
              "from alembic import command; c=Config('alembic.ini'); "
              "c.cmd_opts=SimpleNamespace(x=['database_url='+sys.argv[1]]); "
              "getattr(command, sys.argv[2])(c, sys.argv[3])")
    result = subprocess.run([sys.executable, "-B", "-c", script, url, command, target], cwd=BACKEND,
                            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr


async def _connection(ref, operation):
    engine = create_async_engine(_url(ref), poolclass=NullPool)
    if isinstance(ref, pathlib.Path):
        @event.listens_for(engine.sync_engine, "connect")
        def pragma(connection, record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    try:
        async with engine.begin() as connection:
            return await operation(connection)
    finally:
        await engine.dispose()


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def a29_db(request, tmp_path):
    if request.param == "sqlite":
        return tmp_path / "a29-test.db"
    ref = os.environ["D3_TEST_POSTGRES_URL"]
    async def reset(connection):
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    asyncio.run(_connection(ref, reset))
    return ref


def _id():
    return str(uuid.uuid4())


async def _seed(c):
    ids = {k: _id() for k in ("ilpi", "outra", "u1", "u2", "res",
                              "sv_ok", "sv_sem", "sv_outra_ilpi", "ic_ok",
                              "av_trio", "av_amb1", "av_amb2", "av_direta")}
    for k in ("ilpi", "outra"):
        await c.execute(text("INSERT INTO instituicoes (id, razao_social) VALUES (:i, 'A29')"), {"i": ids[k]})
    for k in ("u1", "u2"):
        await c.execute(text("INSERT INTO users (id, nome, email, password_hash, ativo) VALUES (:i, :n, :e, 'x', true)"),
                        {"i": ids[k], "n": k, "e": f"{ids[k]}@example.com"})
    await c.execute(text("INSERT INTO residentes (id, instituicao_id, nome, data_nascimento, situacao) "
                         "VALUES (:res, :ilpi, 'Residente A29', '1940-01-01', 'Ativo')"), ids)
    for k in ("sv_ok", "sv_sem", "sv_outra_ilpi"):
        await c.execute(text("INSERT INTO sinais_vitais (id, residente_id, ilpi_id, profissional) VALUES (:i, :r, :t, 'Nome')"),
                        {"i": ids[k], "r": ids["res"], "t": ids["ilpi"]})
    await c.execute(text("INSERT INTO intercorrencias (id, residente_id, ilpi_id, tipo, situacao, ocorrido_em, responsavel) "
                         "VALUES (:ic_ok, :res, :ilpi, 'Queda', 'aberta', CURRENT_TIMESTAMP, 'Nome')"), ids)
    for k, tipo in (("av_trio", "Katz"), ("av_amb1", "Lawton"), ("av_amb2", "Lawton"), ("av_direta", "Braden")):
        await c.execute(text("INSERT INTO avaliacoes (id, residente_id, ilpi_id, tipo, profissional) VALUES (:i, :r, :t, :tipo, 'Nome')"),
                        {"i": ids[k], "r": ids["res"], "t": ids["ilpi"], "tipo": tipo})

    async def audit(acao, registro, usuario, ilpi, valores=None):
        await c.execute(text("INSERT INTO auditoria (id, acao, registro_id, usuario_id, ilpi_id, valores_posteriores) "
                             "VALUES (:id, :a, :r, :u, :t, :v)"),
                        {"id": _id(), "a": acao, "r": registro, "u": usuario, "t": ilpi,
                         "v": json.dumps(valores) if valores else None})
    await audit("sinais_vitais.criar", ids["sv_ok"], ids["u1"], ids["ilpi"])
    # Auditoria de OUTRA ILPI apontando para um registro desta: nao pode preencher.
    await audit("sinais_vitais.criar", ids["sv_outra_ilpi"], ids["u2"], ids["outra"])
    await audit("intercorrencias.criar", ids["ic_ok"], ids["u2"], ids["ilpi"])
    # Avaliacoes: registro_id NULO (defeito anterior ao #157) -> casa pelo trio.
    await audit("avaliacoes.criar", None, ids["u1"], ids["ilpi"], {"residente_id": ids["res"], "tipo": "Katz"})
    await audit("avaliacoes.criar", None, ids["u2"], ids["ilpi"], {"residente_id": ids["res"], "tipo": "Lawton"})
    await audit("avaliacoes.criar", ids["av_direta"], ids["u2"], ids["ilpi"], {"residente_id": ids["res"], "tipo": "Braden"})
    return ids


async def _autores(c):
    out = {}
    for t in TABELAS:
        for id_, autor in (await c.execute(text(f"SELECT id, autor_id FROM {t}"))).all():
            out[id_] = autor
    return out


def test_upgrade_preenche_autor_so_pela_auditoria(a29_db):
    _migrate(a29_db, BEFORE)
    ids = asyncio.run(_connection(a29_db, _seed))
    _migrate(a29_db)

    async def verificar(c):
        autores = await _autores(c)
        nomes = {r[0]: r[1] for r in (await c.execute(text("SELECT id, profissional FROM sinais_vitais"))).all()}
        versao = (await c.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
        fks = {t: await c.run_sync(lambda s, t=t: inspect(s).get_foreign_keys(t)) for t in TABELAS}
        return autores, nomes, versao, fks
    autores, nomes, versao, fks = asyncio.run(_connection(a29_db, verificar))

    assert versao == HEAD
    assert autores[ids["sv_ok"]] == ids["u1"]
    assert autores[ids["sv_sem"]] is None           # sem auditoria: sem autor
    assert autores[ids["sv_outra_ilpi"]] is None    # auditoria de outra ILPI nao vale
    assert autores[ids["ic_ok"]] == ids["u2"]
    assert autores[ids["av_trio"]] == ids["u1"]     # 1 avaliacao x 1 auditoria no trio
    assert autores[ids["av_amb1"]] is None          # 2 avaliacoes no trio: ambiguo
    assert autores[ids["av_amb2"]] is None
    assert autores[ids["av_direta"]] == ids["u2"]   # registro_id direto
    assert set(nomes.values()) == {"Nome"}          # o nome em texto nao muda
    for t in TABELAS:
        assert any(fk["referred_table"] == "users" and fk["constrained_columns"] == ["autor_id"] for fk in fks[t]), t


def test_fk_recusa_usuario_inexistente(a29_db):
    _migrate(a29_db)
    async def tentar(c):
        ids = await _seed(c)
        with pytest.raises(Exception):
            async with c.begin_nested():
                await c.execute(text("UPDATE sinais_vitais SET autor_id = :u WHERE id = :i"), {"u": _id(), "i": ids["sv_sem"]})
    asyncio.run(_connection(a29_db, tentar))


def test_downgrade_remove_coluna_e_reupgrade(a29_db):
    _migrate(a29_db)
    _migrate(a29_db, BEFORE, "downgrade")
    async def colunas(c):
        return {t: {col["name"] for col in await c.run_sync(lambda s, t=t: inspect(s).get_columns(t))} for t in TABELAS}
    assert all("autor_id" not in cols for cols in asyncio.run(_connection(a29_db, colunas)).values())
    _migrate(a29_db)
    assert all("autor_id" in cols for cols in asyncio.run(_connection(a29_db, colunas)).values())

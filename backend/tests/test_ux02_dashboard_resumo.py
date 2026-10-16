"""UX-02 (#85): GET /api/dashboard/resumo — contagens dos fatos oficiais.

Cada numero precisa bater com a regra do modulo de origem, ficar restrito a
ILPI da sessao e so aparecer para quem pode ler aquele modulo. Banco descartavel.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
OFFICIAL_DB = ROOT / "storage" / "app.db"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src import main  # noqa: E402
from src.application import auth  # noqa: E402
from src.application.security import ILPI_CONTEXT_REQUIRED  # noqa: E402
from src.infrastructure import database  # noqa: E402
from src.infrastructure import models as m  # noqa: E402
from tests.sessao_teste import abrir_sessao, token_de  # noqa: E402


LEITURA_TOTAL = {
    "residentes:ler", "quartos_leitos:ler", "ausencias:ler", "intercorrencias:ler",
    "admissoes:ler", "planos_cuidados:ler", "funcionarios:ler",
}
AGORA = datetime.now(timezone.utc)


def _sqlite_url(path: pathlib.Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _database_url(ref: pathlib.Path | str) -> str:
    return _sqlite_url(ref) if isinstance(ref, pathlib.Path) else _async_url(ref)


def _run_migration(ref: pathlib.Path | str) -> None:
    if isinstance(ref, pathlib.Path):
        assert ref.resolve() != OFFICIAL_DB.resolve()
    url = _database_url(ref)
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    env.pop("APP_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"database_url={url}", "upgrade", "head"],
        cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def _reset_postgres(url: str) -> None:
    engine = create_async_engine(_async_url(url), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
            await connection.commit()
    finally:
        await engine.dispose()


def _backends() -> list[str]:
    return ["sqlite"] + (["postgresql"] if os.getenv("FASE2_TEST_POSTGRES_URL") else [])


@pytest.fixture(params=_backends(), ids=lambda backend: backend)
def ux02_db(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> pathlib.Path | str:
    if request.param == "sqlite":
        path = tmp_path / "ux02-dashboard.db"
        _run_migration(path)
        return path
    url = os.environ["FASE2_TEST_POSTGRES_URL"]
    try:
        asyncio.run(_reset_postgres(url))
        _run_migration(url)
    except Exception as error:
        pytest.skip(f"PostgreSQL descartavel indisponivel: {error}")
    return url


async def _with_client(ref, operation):
    engine = create_async_engine(_database_url(ref), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[database.get_db] = override_get_db
    auth._rate_store.clear()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver") as client:
            async with factory() as session:
                return await operation(client, session)
    finally:
        main.app.dependency_overrides.clear()
        await engine.dispose()


def _id() -> str:
    return str(uuid.uuid4())


async def _ilpi(db, nome: str, situacao: str = "ATIVA") -> m.Instituicao:
    ilpi = m.Instituicao(id=_id(), razao_social=nome, situacao=situacao)
    db.add(ilpi)
    await db.flush()
    return ilpi


async def _usuario(db, ilpi: m.Instituicao, permissoes: set[str]) -> m.User:
    user = m.User(id=_id(), nome="Usuario UX-02", email=f"ux02-{_id()}@example.com",
                  password_hash="fixture", ativo=True)
    db.add(user)
    await db.flush()
    perfil = m.Perfil(id=_id(), ilpi_id=ilpi.id, nome="Perfil UX-02", chave=f"ux02_{_id()[:8]}",
                      escopo="ilpi", situacao="ativo")
    db.add(perfil)
    await db.flush()
    db.add_all([
        m.Funcionario(id=_id(), ilpi_id=ilpi.id, usuario_id=user.id, nome=user.nome, email=user.email,
                      cargo="Gestao", situacao="ativo"),
        m.UsuarioIlpiPerfil(id=_id(), usuario_id=user.id, perfil_id=perfil.id, ilpi_id=ilpi.id,
                            situacao="ativo", data_inicial=AGORA - timedelta(minutes=1)),
    ])
    await db.flush()
    for row in (await db.execute(select(m.Permissao).where(m.Permissao.chave.in_(permissoes)))).scalars():
        db.add(m.PerfilPermissao(perfil_id=perfil.id, permissao_id=row.id))
    await db.flush()
    await abrir_sessao(db, user)
    return user


async def _residentes(db, ilpi: m.Instituicao, quantidade: int) -> list[m.Residente]:
    lista = [m.Residente(id=_id(), nome=f"Residente {i}", data_nascimento=date(1940, 1, 1 + i),
                         instituicao_id=ilpi.id) for i in range(quantidade)]
    db.add_all(lista)
    await db.flush()
    return lista


async def _fatos(db, ilpi: m.Instituicao, autor: m.User) -> None:
    """Fatos em todos os estados, inclusive os que NAO devem entrar na contagem."""
    r = await _residentes(db, ilpi, 6)
    db.add_all([
        m.QuartoLeito(id=_id(), instituicao_id=ilpi.id, quarto="101", leito="A", situacao="livre", residente_atual_id=r[0].id),
        m.QuartoLeito(id=_id(), instituicao_id=ilpi.id, quarto="101", leito="B", situacao="livre", residente_atual_id=r[1].id),
        m.QuartoLeito(id=_id(), instituicao_id=ilpi.id, quarto="102", leito="A", situacao="livre"),
        m.QuartoLeito(id=_id(), instituicao_id=ilpi.id, quarto="102", leito="B", situacao="bloqueado"),
        m.QuartoLeito(id=_id(), instituicao_id=ilpi.id, quarto="103", leito="A", situacao="manutencao"),
        m.QuartoLeito(id=_id(), instituicao_id=ilpi.id, quarto="103", leito="B", situacao="inativo"),
    ])
    db.add_all([
        m.Ausencia(id=_id(), instituicao_id=ilpi.id, residente_id=r[0].id, tipo="hospitalizacao",
                   data_inicio=AGORA - timedelta(days=1), motivo="Internação", usuario_id=autor.id),
        m.Ausencia(id=_id(), instituicao_id=ilpi.id, residente_id=r[1].id, tipo="saida_temporaria",
                   data_inicio=AGORA - timedelta(hours=3), motivo="Visita", usuario_id=autor.id),
        m.Ausencia(id=_id(), instituicao_id=ilpi.id, residente_id=r[2].id, tipo="hospitalizacao",
                   data_inicio=AGORA - timedelta(days=9), data_fim=AGORA - timedelta(days=2),
                   motivo="Internação encerrada", usuario_id=autor.id),
    ])
    db.add_all([
        m.Intercorrencia(id=_id(), ilpi_id=ilpi.id, residente_id=r[0].id, tipo="queda", situacao="aberta", ocorrido_em=AGORA),
        m.Intercorrencia(id=_id(), ilpi_id=ilpi.id, residente_id=r[1].id, tipo="febre", situacao="aberta", ocorrido_em=AGORA),
        m.Intercorrencia(id=_id(), ilpi_id=ilpi.id, residente_id=r[2].id, tipo="queda", situacao="encerrada", ocorrido_em=AGORA),
    ])
    db.add_all([
        m.Admissao(id=_id(), ilpi_id=ilpi.id, residente_id=r[3].id, autor_id=autor.id, iniciada_em=AGORA, situacao="triagem"),
        m.Admissao(id=_id(), ilpi_id=ilpi.id, residente_id=r[4].id, autor_id=autor.id, iniciada_em=AGORA, situacao="pais"),
        m.Admissao(id=_id(), ilpi_id=ilpi.id, residente_id=r[5].id, autor_id=autor.id, iniciada_em=AGORA,
                   situacao="concluida", concluida_em=AGORA),
    ])
    hoje = AGORA.date()
    db.add_all([
        m.PlanoCuidados(id=_id(), ilpi_id=ilpi.id, residente_id=r[0].id, data_inicial=hoje, situacao="vigente"),
        m.PlanoCuidados(id=_id(), ilpi_id=ilpi.id, residente_id=r[1].id, data_inicial=hoje, situacao="vigente"),
        m.PlanoCuidados(id=_id(), ilpi_id=ilpi.id, residente_id=r[2].id, data_inicial=hoje, situacao="em_revisao"),
        m.PlanoCuidados(id=_id(), ilpi_id=ilpi.id, residente_id=r[2].id, data_inicial=hoje, situacao="encerrado"),
        m.PlanoCuidados(id=_id(), ilpi_id=ilpi.id, residente_id=r[3].id, data_inicial=hoje, situacao="rascunho"),
        m.PlanoCuidados(id=_id(), ilpi_id=ilpi.id, residente_id=r[4].id, data_inicial=hoje, situacao="em_elaboracao"),
        m.PlanoCuidados(id=_id(), ilpi_id=ilpi.id, residente_id=r[5].id, data_inicial=hoje, situacao="aprovado"),
    ])
    db.add_all([
        m.Funcionario(id=_id(), ilpi_id=ilpi.id, nome="Equipe ativa", situacao="ativo"),
        m.Funcionario(id=_id(), ilpi_id=ilpi.id, nome="Equipe afastada", situacao="afastado"),
        m.Funcionario(id=_id(), ilpi_id=ilpi.id, nome="Equipe inativa", situacao="inativo"),
    ])
    await db.flush()


def _get(client: httpx.AsyncClient, user: m.User, ilpi: m.Instituicao):
    return client.get(
        "/api/dashboard/resumo",
        headers={"Authorization": f"Bearer {token_de(user)}", "X-Scope": "ilpi", "X-ILPI-ID": ilpi.id},
    )


def test_contagens_seguem_a_regra_de_cada_modulo(ux02_db):
    async def scenario(client, db):
        ilpi = await _ilpi(db, "ILPI UX-02")
        gestora = await _usuario(db, ilpi, LEITURA_TOTAL)
        await _fatos(db, ilpi, gestora)
        await db.commit()

        response = await _get(client, gestora, ilpi)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["residentes_total"] == 6
        # ocupado = residente_atual_id preenchido; inativo nao e leito ativo.
        assert body["ocupacao"] == {"leitos_ativos": 5, "ocupados": 2, "livres": 1, "indisponiveis": 2}
        assert body["ausencias_ativas"] == {"total": 2, "hospitalizacoes": 1}
        assert body["intercorrencias_abertas"] == 2
        assert body["admissoes_em_andamento"] == 2
        assert body["planos"] == {"vigentes": 2, "em_revisao": 1, "em_elaboracao": 2, "aprovados_aguardando_vigencia": 1}
        # 1 funcionario da propria gestora + 1 ativo semeado; inativo fica fora.
        assert body["equipe"] == {"ativos": 2, "afastados": 1}

    asyncio.run(_with_client(ux02_db, scenario))


def test_fatos_de_outra_ilpi_nao_entram(ux02_db):
    async def scenario(client, db):
        ilpi_a = await _ilpi(db, "ILPI UX-02 A")
        ilpi_b = await _ilpi(db, "ILPI UX-02 B")
        gestora_a = await _usuario(db, ilpi_a, LEITURA_TOTAL)
        gestora_b = await _usuario(db, ilpi_b, LEITURA_TOTAL)
        await _fatos(db, ilpi_b, gestora_b)
        await db.commit()

        body = (await _get(client, gestora_a, ilpi_a)).json()

        assert body["residentes_total"] == 0
        assert body["ocupacao"] == {"leitos_ativos": 0, "ocupados": 0, "livres": 0, "indisponiveis": 0}
        assert body["ausencias_ativas"] == {"total": 0, "hospitalizacoes": 0}
        assert body["intercorrencias_abertas"] == 0
        assert body["admissoes_em_andamento"] == 0
        assert body["planos"]["vigentes"] == 0
        assert body["equipe"] == {"ativos": 1, "afastados": 0}

    asyncio.run(_with_client(ux02_db, scenario))


def test_cada_bloco_exige_a_leitura_do_proprio_modulo(ux02_db):
    async def scenario(client, db):
        ilpi = await _ilpi(db, "ILPI UX-02")
        gestora = await _usuario(db, ilpi, LEITURA_TOTAL)
        cuidador = await _usuario(db, ilpi, {"intercorrencias:ler", "plantao:ler"})
        await _fatos(db, ilpi, gestora)
        await db.commit()

        body = (await _get(client, cuidador, ilpi)).json()

        assert body["intercorrencias_abertas"] == 2
        for bloco in ("residentes_total", "ocupacao", "ausencias_ativas", "admissoes_em_andamento", "planos", "equipe"):
            assert body[bloco] is None, bloco

    asyncio.run(_with_client(ux02_db, scenario))


def test_ilpi_em_rascunho_nao_expoe_blocos_clinicos(ux02_db):
    async def scenario(client, db):
        ilpi = await _ilpi(db, "ILPI UX-02 rascunho", situacao="ILPI_RASCUNHO")
        gestora = await _usuario(db, ilpi, LEITURA_TOTAL)
        await db.commit()

        response = await _get(client, gestora, ilpi)

        assert response.status_code == 200, response.text
        body = response.json()
        # GATE-2: mesmo com a permissao concedida, rascunho nao libera modulo clinico.
        assert body["intercorrencias_abertas"] is None
        assert body["residentes_total"] is None

    asyncio.run(_with_client(ux02_db, scenario))


def test_contexto_global_e_sem_sessao_sao_recusados(ux02_db):
    async def scenario(client, db):
        user = m.User(id=_id(), nome="Plataforma", email=f"ux02-plat-{_id()}@example.com",
                      password_hash="fixture", ativo=True, is_superuser=True)
        perfil = (await db.execute(select(m.Perfil).where(
            m.Perfil.chave == "platform_superuser", m.Perfil.ilpi_id.is_(None)))).scalar_one()
        db.add(user)
        await db.flush()
        db.add(m.UsuarioIlpiPerfil(id=_id(), usuario_id=user.id, perfil_id=perfil.id, ilpi_id=None,
                                   situacao="ativo", data_inicial=AGORA - timedelta(minutes=1)))
        await db.flush()
        await abrir_sessao(db, user)
        await db.commit()

        global_ = await client.get(
            "/api/dashboard/resumo",
            headers={"Authorization": f"Bearer {token_de(user)}", "X-Scope": "global"},
        )
        sem_sessao = await client.get("/api/dashboard/resumo")

        assert global_.status_code == 403, global_.text
        assert global_.json()["detail"]["code"] == ILPI_CONTEXT_REQUIRED
        assert sem_sessao.status_code == 401, sem_sessao.text

    asyncio.run(_with_client(ux02_db, scenario))

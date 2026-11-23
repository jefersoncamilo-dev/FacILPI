"""#211: rate limit em memoria exige 1 worker; o boot recusa mais."""

import pytest

from src.application.auth import assert_rate_limit_single_process


@pytest.mark.parametrize(
    "env,argv",
    [
        ({}, ["uvicorn", "src.main:app"]),
        ({"WEB_CONCURRENCY": "1"}, ["uvicorn"]),
        ({}, ["uvicorn", "--workers", "1"]),
    ],
)
def test_um_worker_sobe(env, argv):
    assert_rate_limit_single_process(env=env, argv=argv)


@pytest.mark.parametrize(
    "env,argv",
    [
        ({"WEB_CONCURRENCY": "2"}, ["uvicorn"]),
        ({}, ["uvicorn", "src.main:app", "--workers", "4"]),
        ({}, ["uvicorn", "--workers=3"]),
        ({}, ["gunicorn", "-w", "2"]),
        ({"WEB_CONCURRENCY": "dois"}, ["uvicorn"]),
    ],
)
def test_mais_de_um_worker_falha_no_boot(env, argv):
    with pytest.raises(RuntimeError):
        assert_rate_limit_single_process(env=env, argv=argv)


def test_ambiente_do_processo_atual_sobe():
    # A suite roda em um processo; o guard nao pode derrubar o boot da app.
    assert_rate_limit_single_process()


# #314: o guard roda no `lifespan` da app (antes `@app.on_event("startup")`).
# Os testes acima provam a funcao; estes provam que o boot da app a chama.
def _subir_app():
    import asyncio
    from src import main

    async def subir():
        async with main.app.router.lifespan_context(main.app):
            pass

    asyncio.run(subir())


class _EngineProibido:
    def begin(self):
        raise AssertionError("create_all nao pode rodar sem ALLOW_CREATE_ALL")


def test_lifespan_recusa_mais_de_um_worker(monkeypatch):
    from src import main

    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    monkeypatch.setattr(main, "engine", _EngineProibido())
    with pytest.raises(RuntimeError, match="workers"):
        _subir_app()


def test_lifespan_sobe_com_um_worker_sem_create_all(monkeypatch):
    from src import main

    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    assert main.ALLOW_CREATE_ALL is False
    monkeypatch.setattr(main, "engine", _EngineProibido())
    _subir_app()

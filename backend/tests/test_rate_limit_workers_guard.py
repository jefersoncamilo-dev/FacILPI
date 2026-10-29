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

"""Engine do PostgreSQL testa e renova conexões do pool (homologação: 500 por conexão fechada)."""

from src.infrastructure.database import engine_kwargs_for


def test_postgresql_testa_conexao_antes_de_usar_e_renova():
    kwargs = engine_kwargs_for("postgresql+asyncpg://u:p@127.0.0.1:5432/db")
    assert kwargs["pool_pre_ping"] is True
    # Abaixo dos 5 min de ociosidade em que o Neon suspende o compute.
    assert 0 < kwargs["pool_recycle"] < 300
    assert (kwargs["pool_size"], kwargs["max_overflow"]) == (5, 10)


def test_sqlite_sem_parametros_de_pool():
    assert engine_kwargs_for("sqlite+aiosqlite:///./qualquer.db") == {"echo": False}

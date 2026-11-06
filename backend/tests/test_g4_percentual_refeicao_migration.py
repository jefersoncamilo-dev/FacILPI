"""G4 (migration 032, D6): percentual de refeicao em execucoes_cuidado.

Banco SQLite descartavel em tmp_path, mesmo harness de migration da N2/M10.
"""
import sqlite3

from tests.test_d4_prontuario import _new_id
from tests.test_n2_saida_residente import _alembic


def _colunas(con):
    return {row[1] for row in con.execute("PRAGMA table_info(execucoes_cuidado)")}


def _inserir(con, percentual):
    # foreign_keys fica desligado nesta conexao: so o CHECK da coluna esta em jogo.
    con.execute(
        "INSERT INTO execucoes_cuidado (id, ilpi_id, residente_id, programacao_id, ocorrencia_id, resultado, "
        "ocorrido_em, registrado_em, executor_id, percentual_consumido) "
        "VALUES (?, ?, ?, ?, ?, 'executada', '2026-10-29 12:00:00', '2026-10-29 12:00:00', ?, ?)",
        (_new_id(), _new_id(), _new_id(), _new_id(), _new_id(), _new_id(), percentual))


def test_g4_upgrade_check_e_downgrade(tmp_path):
    db_path = tmp_path / "g4.db"
    r = _alembic(db_path, ("upgrade", "032_percentual_refeicao"))
    assert r.returncode == 0, r.stdout + r.stderr
    with sqlite3.connect(db_path) as con:
        assert "percentual_consumido" in _colunas(con)
        for valor in (None, 0, 25, 50, 75, 100):
            _inserir(con, valor)
        for valor in (30, -25, 125):
            try:
                _inserir(con, valor)
            except sqlite3.IntegrityError:
                continue
            raise AssertionError(f"CHECK aceitou {valor}")
    # Com percentual registrado o downgrade recusa (nao descarta fato assistencial).
    r = _alembic(db_path, ("downgrade", "031_grants_medicacao"))
    assert r.returncode != 0
    assert "032 recusa downgrade" in r.stdout + r.stderr
    with sqlite3.connect(db_path) as con:
        con.execute("UPDATE execucoes_cuidado SET percentual_consumido = NULL")
    r = _alembic(db_path, ("downgrade", "031_grants_medicacao"))
    assert r.returncode == 0, r.stdout + r.stderr
    with sqlite3.connect(db_path) as con:
        assert "percentual_consumido" not in _colunas(con)
        # Os indices parciais da D.2 sobrevivem ao ida-e-volta.
        indices = {row[1] for row in con.execute("PRAGMA index_list(execucoes_cuidado)")}
        assert {"uq_exec_ocorrencia_vigente", "uq_exec_substitui"} <= indices

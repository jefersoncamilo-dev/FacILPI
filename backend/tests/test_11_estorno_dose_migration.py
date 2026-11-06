"""#11 (migration 033, D2 = sim): administracoes:corrigir para o responsavel_tecnico.

Banco SQLite descartavel em tmp_path, mesmo harness de migration da N2/M10.
"""
import sqlite3

from tests.test_d4_prontuario import _new_id
from tests.test_n2_saida_residente import _alembic

CHAVE = "administracoes:corrigir"


def _chaves(con, pid):
    return {row[0] for row in con.execute(
        "SELECT p.chave FROM perfil_permissoes pp JOIN permissoes p ON p.id = pp.permissao_id WHERE pp.perfil_id = ?",
        (pid,))}


def _template(con, chave):
    return con.execute("SELECT id FROM perfis WHERE chave = ? AND ilpi_id IS NULL", (chave,)).fetchone()[0]


def test_11_templates_clones_e_downgrade(tmp_path):
    db_path = tmp_path / "m11.db"
    r = _alembic(db_path, ("upgrade", "032_percentual_refeicao"))
    assert r.returncode == 0, r.stdout + r.stderr
    inst = _new_id()
    clones = {chave: _new_id() for chave in ("responsavel_tecnico", "cuidador")}
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT INTO instituicoes (id, razao_social, situacao) VALUES (?, 'Clone', 'ATIVA')", (inst,))
        for chave, pid in clones.items():
            con.execute("INSERT INTO perfis (id, ilpi_id, nome, chave, escopo, situacao) VALUES (?, ?, ?, ?, 'ilpi', 'ativo')",
                        (pid, inst, f"Clone {chave}", chave))
        assert CHAVE in _chaves(con, _template(con, "enfermagem"))
        assert CHAVE not in _chaves(con, _template(con, "responsavel_tecnico"))

    r = _alembic(db_path, ("upgrade", "033_estorno_dose"))
    assert r.returncode == 0, r.stdout + r.stderr
    with sqlite3.connect(db_path) as con:
        assert CHAVE in _chaves(con, _template(con, "responsavel_tecnico"))
        assert CHAVE in _chaves(con, clones["responsavel_tecnico"])
        assert CHAVE in _chaves(con, _template(con, "enfermagem"))
        # D2: cuidador, medico, ilpi_admin e platform nao estornam dose.
        for chave in ("cuidador", "medico", "ilpi_admin", "platform_superuser"):
            assert CHAVE not in _chaves(con, _template(con, chave)), chave
        assert CHAVE not in _chaves(con, clones["cuidador"])

    r = _alembic(db_path, ("downgrade", "032_percentual_refeicao"))
    assert r.returncode == 0, r.stdout + r.stderr
    with sqlite3.connect(db_path) as con:
        assert CHAVE not in _chaves(con, _template(con, "responsavel_tecnico"))
        assert CHAVE not in _chaves(con, clones["responsavel_tecnico"])
        # Vinculo da 015 preservado.
        assert CHAVE in _chaves(con, _template(con, "enfermagem"))


def test_11_downgrade_recusa_vinculo_externo(tmp_path):
    db_path = tmp_path / "m11-externo.db"
    r = _alembic(db_path, ("upgrade", "033_estorno_dose"))
    assert r.returncode == 0, r.stdout + r.stderr
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT INTO perfil_permissoes (perfil_id, permissao_id) SELECT ?, id FROM permissoes "
                    "WHERE chave = ?", (_template(con, "cuidador"), CHAVE))
    r = _alembic(db_path, ("downgrade", "032_percentual_refeicao"))
    assert r.returncode != 0
    assert "033 recusa downgrade" in r.stdout + r.stderr

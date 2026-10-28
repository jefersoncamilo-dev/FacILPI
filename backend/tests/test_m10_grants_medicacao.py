"""M10 (migration 031, D1): grants de medicacao para enfermagem e responsavel_tecnico.

Banco SQLite descartavel em tmp_path, mesmo harness de migration da N2.
"""
import sqlite3

from tests.test_d4_prontuario import _new_id
from tests.test_n2_saida_residente import _alembic

D1 = {"medicamentos:criar", "medicamentos:atualizar", "prescricoes:criar", "prescricoes:atualizar"}


def _chaves(con, pid):
    return {row[0] for row in con.execute(
        "SELECT p.chave FROM perfil_permissoes pp JOIN permissoes p ON p.id = pp.permissao_id WHERE pp.perfil_id = ?",
        (pid,))}


def _template(con, chave):
    return con.execute("SELECT id FROM perfis WHERE chave = ? AND ilpi_id IS NULL", (chave,)).fetchone()[0]


def test_m10_templates_clones_e_downgrade(tmp_path):
    db_path = tmp_path / "m10.db"
    r = _alembic(db_path, ("upgrade", "030_saida_residente"))
    assert r.returncode == 0, r.stdout + r.stderr
    inst = _new_id()
    clones = {chave: _new_id() for chave in ("enfermagem", "responsavel_tecnico", "cuidador")}
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT INTO instituicoes (id, razao_social, situacao) VALUES (?, 'Clone', 'ATIVA')", (inst,))
        for chave, pid in clones.items():
            con.execute("INSERT INTO perfis (id, ilpi_id, nome, chave, escopo, situacao) VALUES (?, ?, ?, ?, 'ilpi', 'ativo')",
                        (pid, inst, f"Clone {chave}", chave))
        antes_medico = _chaves(con, _template(con, "medico")) & D1
    assert antes_medico == {"prescricoes:criar", "prescricoes:atualizar"}

    r = _alembic(db_path, ("upgrade", "head"))
    assert r.returncode == 0, r.stdout + r.stderr
    with sqlite3.connect(db_path) as con:
        for chave in ("enfermagem", "responsavel_tecnico"):
            assert D1 <= _chaves(con, _template(con, chave))
            assert D1 <= _chaves(con, clones[chave])
        # D1: cuidador e ilpi_admin nao cadastram; medico mantem so prescrever.
        assert not D1 & _chaves(con, _template(con, "cuidador"))
        assert not D1 & _chaves(con, clones["cuidador"])
        assert not D1 & _chaves(con, _template(con, "ilpi_admin"))
        assert _chaves(con, _template(con, "medico")) & D1 == antes_medico
        assert con.execute("SELECT COUNT(*) FROM perfil_permissoes GROUP BY perfil_id, permissao_id "
                           "HAVING COUNT(*) > 1").fetchone() is None

    r = _alembic(db_path, ("downgrade", "030_saida_residente"))
    assert r.returncode == 0, r.stdout + r.stderr
    with sqlite3.connect(db_path) as con:
        for chave in ("enfermagem", "responsavel_tecnico"):
            assert not D1 & _chaves(con, _template(con, chave))
            assert not D1 & _chaves(con, clones[chave])
        assert _chaves(con, _template(con, "medico")) & D1 == antes_medico
        assert con.execute("SELECT COUNT(*) FROM permissoes WHERE chave IN (?, ?, ?, ?)", tuple(D1)).fetchone()[0] == 4


def test_m10_downgrade_recusa_vinculo_externo(tmp_path):
    db_path = tmp_path / "m10-externo.db"
    r = _alembic(db_path, ("upgrade", "head"))
    assert r.returncode == 0, r.stdout + r.stderr
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT INTO perfil_permissoes (perfil_id, permissao_id) SELECT ?, id FROM permissoes "
                    "WHERE chave = 'medicamentos:criar'", (_template(con, "cuidador"),))
    r = _alembic(db_path, ("downgrade", "030_saida_residente"))
    assert r.returncode != 0
    assert "031 recusa downgrade" in r.stdout + r.stderr


def test_m10_upgrade_recusa_catalogo_adulterado(tmp_path):
    db_path = tmp_path / "m10-adulterado.db"
    r = _alembic(db_path, ("upgrade", "030_saida_residente"))
    assert r.returncode == 0, r.stdout + r.stderr
    with sqlite3.connect(db_path) as con:
        con.execute("UPDATE permissoes SET descricao = 'x' WHERE chave = 'prescricoes:criar'")
    r = _alembic(db_path, ("upgrade", "head"))
    assert r.returncode != 0
    assert "031 permissao adulterada" in r.stdout + r.stderr

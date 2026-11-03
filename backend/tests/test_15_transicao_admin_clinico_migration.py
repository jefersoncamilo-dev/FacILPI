"""#15 (migration 034, D3): corte das escritas clinicas do ilpi_admin.

Banco SQLite descartavel em tmp_path, mesmo harness de migration da N2/M10.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

from src.application.security import ESCRITAS_CLINICAS_ADMIN
from tests.test_d4_prontuario import _new_id
from tests.test_n2_saida_residente import _alembic


def _chaves(con, pid):
    return {row[0] for row in con.execute(
        "SELECT p.chave FROM perfil_permissoes pp JOIN permissoes p ON p.id = pp.permissao_id WHERE pp.perfil_id = ?",
        (pid,))}


def _template(con, chave):
    return con.execute("SELECT id FROM perfis WHERE chave = ? AND ilpi_id IS NULL", (chave,)).fetchone()[0]


def test_15_corte_prazo_por_ilpi_e_downgrade(tmp_path):
    db_path = tmp_path / "m15.db"
    r = _alembic(db_path, ("upgrade", "033_estorno_dose"))
    assert r.returncode == 0, r.stdout + r.stderr
    inst, clone, enf = _new_id(), _new_id(), _new_id()
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT INTO instituicoes (id, razao_social, situacao) VALUES (?, 'Antiga', 'ATIVA')", (inst,))
        for pid, chave in ((clone, "ilpi_admin"), (enf, "enfermagem")):
            con.execute("INSERT INTO perfis (id, ilpi_id, nome, chave, escopo, situacao) VALUES (?, ?, ?, ?, 'ilpi', 'ativo')",
                        (pid, inst, f"Clone {chave}", chave))
            con.execute("INSERT INTO perfil_permissoes (perfil_id, permissao_id) SELECT ?, permissao_id "
                        "FROM perfil_permissoes WHERE perfil_id = ?", (pid, _template(con, chave)))
        # Clone recortado: so leitura de residentes, sem nenhuma escrita clinica.
        recortado = _new_id()
        con.execute("INSERT INTO perfis (id, ilpi_id, nome, chave, escopo, situacao) "
                    "VALUES (?, ?, 'Recortado', 'ilpi_admin', 'ilpi', 'ativo')", (recortado, _new_id()))
        con.execute("INSERT INTO perfil_permissoes (perfil_id, permissao_id) SELECT ?, id FROM permissoes "
                    "WHERE chave = 'residentes:ler'", (recortado,))
        antes_admin = _chaves(con, _template(con, "ilpi_admin"))
        antes_enf = _chaves(con, enf)
        assert ESCRITAS_CLINICAS_ADMIN <= antes_admin

    inicio = datetime.now(timezone.utc)
    r = _alembic(db_path, ("upgrade", "034_transicao_admin_clinico"))
    assert r.returncode == 0, r.stdout + r.stderr
    with sqlite3.connect(db_path) as con:
        for pid in (_template(con, "ilpi_admin"), clone):
            assert _chaves(con, pid) == antes_admin - ESCRITAS_CLINICAS_ADMIN
        assert _chaves(con, enf) == antes_enf
        prazo = con.execute("SELECT prazo FROM transicao_admin_clinico WHERE ilpi_id = ?", (inst,)).fetchone()[0]
        prazo = datetime.fromisoformat(str(prazo)).replace(tzinfo=timezone.utc)
        assert inicio + timedelta(days=30) - timedelta(minutes=5) <= prazo <= inicio + timedelta(days=30, minutes=5)

    r = _alembic(db_path, ("downgrade", "033_estorno_dose"))
    assert r.returncode == 0, r.stdout + r.stderr
    with sqlite3.connect(db_path) as con:
        for pid in (_template(con, "ilpi_admin"), clone):
            assert _chaves(con, pid) == antes_admin
        # O downgrade devolve so o que a 034 tirou: o clone recortado nao ganha escrita.
        assert _chaves(con, recortado) == {"residentes:ler"}
        assert con.execute("SELECT name FROM sqlite_master WHERE name = 'transicao_admin_clinico'").fetchone() is None

"""
Fase 1 — Testes estruturais: modelos, migrations e isolamento multi-tenant
Valida critérios do parecer aprovado (8 observações).
Não cria admin@ilpi.com, não executa bootstrap, não altera placeholders.
"""
import sqlite3
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import uuid

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _prepare_fase1_db():
    path = pathlib.Path(tempfile.mkdtemp(prefix="facilpi-fase1-")) / "fase1-structure.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{path.resolve().as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "002_fase1_isolamento"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return path


DB_PATH = _prepare_fase1_db()

def _connect(db_path=DB_PATH):
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _disposable_db(tmp_path):
    destination = tmp_path / "fase1-structure.db"
    shutil.copy2(DB_PATH, destination)
    return destination

def test_bootstrap_initial_state():
    """C1: estado inicial deve ser UNINITIALIZED, singleton fixo, sem PLATFORM_BOOTSTRAPPED"""
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT id, estado FROM bootstrap_state")
    rows = cur.fetchall()
    assert len(rows) == 1, f"esperado 1 linha bootstrap_state, encontrou {len(rows)}"
    _id, estado = rows[0]
    assert _id == "00000000-0000-0000-0000-000000000001"
    assert estado == "UNINITIALIZED", f"estado esperado UNINITIALIZED, got {estado}"
    # check constraint existe
    cur.execute("SELECT sql FROM sqlite_master WHERE name='bootstrap_state'")
    sql = cur.fetchone()[0]
    assert "ck_bootstrap_estado" in sql
    assert "UNINITIALIZED" in sql
    con.close()

def test_ilpi_id_columns_exist():
    """C9: ilpi_id em entidades clínicas, nullable, FK, índice"""
    con = _connect()
    cur = con.cursor()
    tabelas = ["familiares","avaliacoes","planos_cuidados","tarefas","prescricoes","sinais_vitais","intercorrencias"]
    for tbl in tabelas:
        cur.execute(f"PRAGMA table_info({tbl})")
        cols = [r[1] for r in cur.fetchall()]
        assert "ilpi_id" in cols, f"{tbl} sem ilpi_id"
        # FK existe
        cur.execute(f"PRAGMA foreign_key_list({tbl})")
        fks = cur.fetchall()
        # fks: (id, seq, table, from, to, on_update, on_delete, match)
        assert any(f[2]=="instituicoes" and f[3]=="ilpi_id" for f in fks), f"{tbl} sem FK ilpi_id -> instituicoes"
        # índice
        cur.execute(f"SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='{tbl}' AND name='ix_{tbl}_ilpi_id'")
        assert cur.fetchone() is not None, f"índice ix_{tbl}_ilpi_id ausente"
    con.close()

def test_backfill_deterministico_no_orfaos():
    """Backfill determinístico e diagnóstico de órfãos: nenhum residente órfão para tabelas vazias"""
    con = _connect()
    cur = con.cursor()
    # tabelas vazias devem ter backfill sem erro; verifica que query de órfãos retorna 0
    for tbl in ["tarefas","avaliacoes","prescricoes"]:
        cur.execute(f"SELECT {tbl}.id FROM {tbl} LEFT JOIN residentes ON residentes.id={tbl}.residente_id WHERE {tbl}.residente_id IS NOT NULL AND residentes.id IS NULL")
        assert cur.fetchall() == [], f"órfãos encontrados em {tbl}"
    con.close()

def test_funcionario_cpf_unico_por_ilpi(tmp_path):
    """C6/C5: CPF único por ILPI, pode repetir em ILPIs diferentes"""
    con = _connect(_disposable_db(tmp_path))
    cur = con.cursor()
    # cria duas ILPIs de teste (String 36)
    ilpi_a = str(uuid.uuid4())
    ilpi_b = str(uuid.uuid4())
    cur.execute("INSERT INTO instituicoes (id, razao_social, situacao) VALUES (?, 'ILPI A Teste', 'ILPI_RASCUNHO')", (ilpi_a,))
    cur.execute("INSERT INTO instituicoes (id, razao_social, situacao) VALUES (?, 'ILPI B Teste', 'ILPI_RASCUNHO')", (ilpi_b,))
    cpf = "52998224725"
    f1 = str(uuid.uuid4())
    f2 = str(uuid.uuid4())
    f3 = str(uuid.uuid4())
    # mesmo CPF mesma ILPI deve falhar na segunda inserção
    cur.execute("INSERT INTO funcionarios (id, ilpi_id, nome, cpf) VALUES (?, ?, 'Joao A', ?)", (f1, ilpi_a, cpf))
    con.commit()
    # tentativa duplicada mesma ILPI
    try:
        cur.execute("INSERT INTO funcionarios (id, ilpi_id, nome, cpf) VALUES (?, ?, 'Joao Dup', ?)", (f2, ilpi_a, cpf))
        con.commit()
        assert False, "UNIQUE cpf+ilpi_id deveria falhar"
    except sqlite3.IntegrityError as e:
        con.rollback()
        assert "uq_funcionario_cpf_ilpi" in str(e) or "UNIQUE" in str(e)
    # mesmo CPF em ILPI diferente deve passar
    cur.execute("INSERT INTO funcionarios (id, ilpi_id, nome, cpf) VALUES (?, ?, 'Joao B', ?)", (f3, ilpi_b, cpf))
    con.commit()
    # cleanup
    cur.execute("DELETE FROM funcionarios WHERE id IN (?,?,?)", (f1,f2,f3))
    cur.execute("DELETE FROM instituicoes WHERE id IN (?,?)", (ilpi_a, ilpi_b))
    con.commit()
    con.close()

def test_funcionario_usuario_unico_por_ilpi_permitido_multi_ilpi(tmp_path):
    """UNIQUE(ilpi_id, usuario_id) quando preenchido — mesmo usuario em ILPIs diferentes OK, mesma ILPI duplicado falha"""
    con = _connect(_disposable_db(tmp_path))
    cur = con.cursor()
    ilpi_a = str(uuid.uuid4())
    ilpi_b = str(uuid.uuid4())
    cur.execute("INSERT INTO instituicoes (id, razao_social, situacao) VALUES (?, 'ILPI A2', 'ILPI_RASCUNHO')", (ilpi_a,))
    cur.execute("INSERT INTO instituicoes (id, razao_social, situacao) VALUES (?, 'ILPI B2', 'ILPI_RASCUNHO')", (ilpi_b,))
    user = str(uuid.uuid4())
    # cria user fake para FK
    cur.execute("INSERT INTO users (id, nome, email, password_hash, ativo) VALUES (?, 'Teste User', ?, 'hash', 1)", (user, f"test_{user[:8]}@ex.com"))
    f1 = str(uuid.uuid4())
    f2 = str(uuid.uuid4())
    f3 = str(uuid.uuid4())
    cur.execute("INSERT INTO funcionarios (id, ilpi_id, usuario_id, nome) VALUES (?, ?, ?, 'Func A')", (f1, ilpi_a, user))
    con.commit()
    # mesmo ilpi, mesmo usuario -> deve falhar
    try:
        cur.execute("INSERT INTO funcionarios (id, ilpi_id, usuario_id, nome) VALUES (?, ?, ?, 'Func Dup')", (f2, ilpi_a, user))
        con.commit()
        assert False, "UNIQUE ilpi_id+usuario_id deveria falhar"
    except sqlite3.IntegrityError as e:
        con.rollback()
        assert "uq_funcionario_ilpi_usuario" in str(e) or "UNIQUE" in str(e)
    # mesmo usuario em ILPI diferente -> ok
    cur.execute("INSERT INTO funcionarios (id, ilpi_id, usuario_id, nome) VALUES (?, ?, ?, 'Func B')", (f3, ilpi_b, user))
    con.commit()
    # permite múltiplos funcionarios sem usuario (null)
    f4 = str(uuid.uuid4())
    f5 = str(uuid.uuid4())
    cur.execute("INSERT INTO funcionarios (id, ilpi_id, nome) VALUES (?, ?, 'Sem Usuario 1')", (f4, ilpi_a))
    cur.execute("INSERT INTO funcionarios (id, ilpi_id, nome) VALUES (?, ?, 'Sem Usuario 2')", (f5, ilpi_a))
    con.commit()
    # cleanup
    for _id in [f1,f3,f4,f5]:
        cur.execute("DELETE FROM funcionarios WHERE id=?", (_id,))
    cur.execute("DELETE FROM users WHERE id=?", (user,))
    cur.execute("DELETE FROM instituicoes WHERE id IN (?,?)", (ilpi_a, ilpi_b))
    con.commit()
    con.close()

def test_perfils_permissoes_vazios_fase1():
    """Observação 1: Fase 1 só cria tabelas, catálogo vai em fase 2"""
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT count(*) FROM perfis")
    assert cur.fetchone()[0] == 0, "perfis deve estar vazio em fase 1"
    cur.execute("SELECT count(*) FROM permissoes")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT count(*) FROM perfil_permissoes")
    assert cur.fetchone()[0] == 0
    con.close()

def test_auditoria_estrutura():
    """Auditoria com ilpi_id, usuario_id, valores Text (não JSONB), índices"""
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT sql FROM sqlite_master WHERE name='auditoria'")
    sql = cur.fetchone()[0]
    assert "valores_anteriores" in sql
    assert "valores_posteriores" in sql
    # Text, não JSONB
    assert "JSONB" not in sql
    # índices
    cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='auditoria'")
    idxs = [r[0] for r in cur.fetchall()]
    assert "ix_auditoria_ilpi_entidade" in idxs
    assert "ix_auditoria_created_at" in idxs
    con.close()

def test_refresh_e_password_reset_separados():
    """Observação 2: tabelas separadas, hash, não reuse"""
    con = _connect()
    cur = con.cursor()
    for tbl in ["refresh_tokens","password_reset_tokens"]:
        cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{tbl}'")
        assert cur.fetchone() is not None, f"{tbl} ausente"
    # colunas
    cur.execute("PRAGMA table_info(refresh_tokens)")
    cols_r = [r[1] for r in cur.fetchall()]
    assert "token_hash" in cols_r and "jti" in cols_r and "token_family" in cols_r
    assert "expires_at" in cols_r
    cur.execute("PRAGMA table_info(password_reset_tokens)")
    cols_p = [r[1] for r in cur.fetchall()]
    assert "token_hash" in cols_p and "expires_at" in cols_p and "used_at" in cols_p
    assert "created_by" in cols_p
    con.close()

def test_no_ilpi_modelo_criada():
    """Observação 4: ILPI Modelo não criada em migration, instituicoes deve permanecer 0 (exceto testes que limpam)"""
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT count(*) FROM instituicoes WHERE razao_social='ILPI Modelo FacILPI'")
    assert cur.fetchone()[0] == 0
    con.close()

def test_migration_sem_forbidden_pg_constructs():
    """Compatibilidade: evita gen_random_uuid(), JSONB, trigger, IF NOT EXISTS generalizado"""
    import pathlib
    mig = pathlib.Path("backend/alembic/versions/002_fase1_isolamento.py")
    if not mig.exists():
        mig = pathlib.Path("alembic/versions/002_fase1_isolamento.py")
    text = mig.read_text(encoding="utf-8")
    # PG UUID geração deve ser via app (gen_uuid python), não via SQL gen_random_uuid
    assert "gen_random_uuid" not in text.lower(), "evitar gen_random_uuid() PG, usar app UUID"
    assert "JSONB" not in text, "evitar JSONB em fase 1, usar Text"
    assert "CREATE TRIGGER" not in text.upper(), "não usar triggers"
    # IF NOT EXISTS só permitido pontualmente, mas não generalizado — aqui não deve ter
    # Verifica que não há CREATE TABLE IF NOT EXISTS
    assert "IF NOT EXISTS" not in text or text.count("IF NOT EXISTS") < 2

def test_usuario_ilpi_perfil_unique(tmp_path):
    con = _connect(_disposable_db(tmp_path))
    cur = con.cursor()
    ilpi = str(uuid.uuid4())
    user = str(uuid.uuid4())
    perfil = str(uuid.uuid4())
    cur.execute("INSERT INTO instituicoes (id, razao_social, situacao) VALUES (?, 'ILPI Teste U', 'ILPI_RASCUNHO')", (ilpi,))
    cur.execute("INSERT INTO users (id, nome, email, password_hash, ativo) VALUES (?, 'U', ?, 'hash',1)", (user, f"u_{user[:6]}@ex.com"))
    cur.execute("INSERT INTO perfis (id, nome, chave, escopo) VALUES (?, 'Admin', ?, 'ilpi')", (perfil, f"test_{perfil[:6]}"))
    cur.execute("INSERT INTO usuario_ilpi_perfis (id, usuario_id, ilpi_id, perfil_id) VALUES (?, ?, ?, ?)", (str(uuid.uuid4()), user, ilpi, perfil))
    con.commit()
    # duplicado deve falhar
    try:
        cur.execute("INSERT INTO usuario_ilpi_perfis (id, usuario_id, ilpi_id, perfil_id) VALUES (?, ?, ?, ?)", (str(uuid.uuid4()), user, ilpi, perfil))
        con.commit()
        assert False, "UNIQUE usuario_ilpi_perfil deveria falhar"
    except sqlite3.IntegrityError:
        con.rollback()
    # cleanup
    cur.execute("DELETE FROM usuario_ilpi_perfis WHERE usuario_id=?", (user,))
    cur.execute("DELETE FROM perfis WHERE id=?", (perfil,))
    cur.execute("DELETE FROM users WHERE id=?", (user,))
    cur.execute("DELETE FROM instituicoes WHERE id=?", (ilpi,))
    con.commit()
    con.close()

"""D.3: processo de admissao, historico append-only e catalogo sem grants.

Nenhuma inferencia/migracao de admissoes legadas, nenhuma mudanca de estado
do Residente. Downgrade recusa processos, historico ou grants existentes.
"""

from alembic import op
import sqlalchemy as sa

revision = "016_d3_admissao"
down_revision = "015_s1_matriz_permissoes"
branch_labels = None
depends_on = None

ACTIONS = ("ler", "criar", "atualizar", "avancar", "reabrir", "concluir", "cancelar")
STATES = "'pre_cadastro','triagem','documentacao','avaliacoes','contrato','quarto_leito','pais','concluida','cancelada','desistencia'"


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("016 suporta somente SQLite e PostgreSQL")
    if bind.execute(sa.text("SELECT id FROM permissoes WHERE modulo='admissoes' OR chave LIKE 'admissoes:%'")).first():
        raise RuntimeError("016 recusa catalogo de admissoes preexistente")
    op.create_index("uq_funcionarios_id_ilpi", "funcionarios", ["id", "ilpi_id"], unique=True)
    op.create_index("uq_documentos_id_instituicao", "documentos", ["id", "instituicao_id"], unique=True)
    op.create_table(
        "admissoes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("residente_id", sa.String(36), nullable=False),
        sa.Column("situacao", sa.String(30), nullable=False),
        sa.Column("autor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("responsavel_funcionario_id", sa.String(36)),
        sa.Column("iniciada_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("concluida_em", sa.DateTime(timezone=True)),
        sa.Column("cancelada_em", sa.DateTime(timezone=True)),
        sa.Column("desistencia_em", sa.DateTime(timezone=True)),
        sa.Column("motivo_cancelamento", sa.Text),
        sa.Column("motivo_desistencia", sa.Text),
        sa.Column("contrato_registrado_em", sa.DateTime(timezone=True)),
        sa.Column("contrato_documento_id", sa.String(36)),
        sa.Column("avaliacoes_requeridas", sa.JSON, nullable=False),
        sa.Column("lock_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "ilpi_id", name="uq_admissoes_id_ilpi"),
        sa.ForeignKeyConstraint(["residente_id", "ilpi_id"], ["residentes.id", "residentes.instituicao_id"], name="fk_admissoes_residente", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["responsavel_funcionario_id", "ilpi_id"], ["funcionarios.id", "funcionarios.ilpi_id"], name="fk_admissoes_responsavel", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["contrato_documento_id", "ilpi_id"], ["documentos.id", "documentos.instituicao_id"], name="fk_admissoes_contrato", ondelete="RESTRICT"),
        sa.CheckConstraint(f"situacao IN ({STATES})", name="ck_admissoes_situacao"),
        sa.CheckConstraint("lock_version >= 0", name="ck_admissoes_version"),
        sa.CheckConstraint("situacao != 'concluida' OR concluida_em IS NOT NULL", name="ck_admissoes_conclusao"),
        sa.CheckConstraint("situacao != 'cancelada' OR (cancelada_em IS NOT NULL AND length(trim(motivo_cancelamento)) > 0 AND motivo_cancelamento IS NOT NULL)", name="ck_admissoes_cancelamento"),
        sa.CheckConstraint("situacao != 'desistencia' OR (desistencia_em IS NOT NULL AND length(trim(motivo_desistencia)) > 0 AND motivo_desistencia IS NOT NULL)", name="ck_admissoes_desistencia"),
    )
    op.create_index("ix_admissoes_ilpi_situacao", "admissoes", ["ilpi_id", "situacao"])
    op.create_index("uq_admissoes_residente_processo", "admissoes", ["ilpi_id", "residente_id"], unique=True,
                    sqlite_where=sa.text("situacao NOT IN ('cancelada','desistencia')"),
                    postgresql_where=sa.text("situacao NOT IN ('cancelada','desistencia')"))
    op.create_table(
        "admissao_historico",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("admissao_id", sa.String(36), nullable=False),
        sa.Column("etapa_origem", sa.String(30)),
        sa.Column("etapa_destino", sa.String(30), nullable=False),
        sa.Column("acao", sa.String(50), nullable=False),
        sa.Column("motivo", sa.Text),
        sa.Column("autor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("lock_version", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["admissao_id", "ilpi_id"], ["admissoes.id", "admissoes.ilpi_id"], name="fk_admissao_historico_processo", ondelete="RESTRICT"),
        sa.UniqueConstraint("admissao_id", "lock_version", name="uq_admissao_historico_version"),
        sa.CheckConstraint("lock_version >= 0", name="ck_admissao_historico_version"),
    )
    op.create_index("ix_admissao_historico_ilpi_processo", "admissao_historico", ["ilpi_id", "admissao_id"])
    if bind.dialect.name == "sqlite":
        op.execute("CREATE TRIGGER d3_historico_no_replace BEFORE INSERT ON admissao_historico WHEN EXISTS (SELECT 1 FROM admissao_historico WHERE id=NEW.id OR (admissao_id=NEW.admissao_id AND lock_version=NEW.lock_version)) BEGIN SELECT RAISE(ABORT, 'admissao_historico append-only'); END")
        for action in ("UPDATE", "DELETE"):
            op.execute(f"CREATE TRIGGER d3_historico_no_{action.lower()} BEFORE {action} ON admissao_historico BEGIN SELECT RAISE(ABORT, 'admissao_historico append-only'); END")
    else:
        op.execute("CREATE FUNCTION d3_historico_append_only() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'admissao_historico append-only'; END; $$")
        op.execute("CREATE TRIGGER d3_historico_append_only BEFORE UPDATE OR DELETE ON admissao_historico FOR EACH ROW EXECUTE FUNCTION d3_historico_append_only()")
        op.execute("CREATE TRIGGER d3_historico_no_truncate BEFORE TRUNCATE ON admissao_historico FOR EACH STATEMENT EXECUTE FUNCTION d3_historico_append_only()")
    for index, action in enumerate(ACTIONS, 86):
        bind.execute(sa.text("INSERT INTO permissoes (id, modulo, acao, chave, descricao) VALUES (:id, 'admissoes', :acao, :chave, :descricao)"),
                     {"id": f"fac11000-0000-4000-8000-{index:012d}", "acao": action, "chave": f"admissoes:{action}", "descricao": f"Admissoes: {action} na ILPI da sessao; atribuicao explicita S.1."})


def downgrade():
    bind = op.get_bind()
    for table in ("admissoes", "admissao_historico"):
        if bind.execute(sa.text(f"SELECT id FROM {table} LIMIT 1")).first():
            raise RuntimeError("016 recusa downgrade: admissoes/historico sem representacao anterior")
    if bind.execute(sa.text("SELECT pp.perfil_id FROM perfil_permissoes pp JOIN permissoes p ON p.id=pp.permissao_id WHERE p.modulo='admissoes' LIMIT 1")).first():
        raise RuntimeError("016 recusa downgrade: grants de admissoes atribuidos explicitamente")
    op.drop_table("admissao_historico")
    if bind.dialect.name == "postgresql":
        op.execute("DROP FUNCTION d3_historico_append_only()")
    op.drop_table("admissoes")
    op.drop_index("uq_documentos_id_instituicao", table_name="documentos")
    op.drop_index("uq_funcionarios_id_ilpi", table_name="funcionarios")
    bind.execute(sa.text("DELETE FROM permissoes WHERE modulo='admissoes'"))

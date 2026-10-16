"""fase1 isolamento multi-tenant — FáciLPI Fase 1

Revision ID: 002_fase1_isolamento
Revises: 001_initial
Create Date: 2026-08-30

Fase 1 — Modelos, migrations e isolamento multi-tenant
Cria apenas estrutura (sem catálogo/perfis seed). Compatível PG + SQLite.
Observações incorporadas:
- Tabelas novas apenas, catálogo vai em fase 2
- password_reset_tokens separada de refresh_tokens
- ilpi_id nullable + backfill determinístico, falha em órfãos
- UUID app (String 36) sem gen_uuid() PG
- Checks via String + CheckConstraint compatível
- Sem triggers, FK composta lógica via serviço + FK simples
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import uuid

revision: str = "002_fase1_isolamento"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _gen_uuid():
    return str(uuid.uuid4())


def upgrade() -> None:
    # ===== bootstrap_state =====
    op.create_table(
        "bootstrap_state",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("estado", sa.String(length=40), nullable=False, server_default="UNINITIALIZED"),
        sa.Column("platform_bootstrapped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("atualizado_por", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.ForeignKeyConstraint(["atualizado_por"], ["users.id"], ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("estado IN ('UNINITIALIZED','PLATFORM_BOOTSTRAPPED','FIRST_PASSWORD_CHANGED')", name="ck_bootstrap_estado"),
    )
    # Seed singleton UNINITIALIZED (id fixo para gate)
    op.execute(
        sa.text("INSERT INTO bootstrap_state (id, estado) VALUES ('00000000-0000-0000-0000-000000000001', 'UNINITIALIZED')")
    )

    # ===== perfis =====
    op.create_table(
        "perfis",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("ilpi_id", sa.String(length=36), nullable=True),
        sa.Column("nome", sa.String(length=100), nullable=False),
        sa.Column("chave", sa.String(length=100), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.Column("escopo", sa.String(length=10), nullable=False, server_default="ilpi"),
        sa.Column("situacao", sa.String(length=20), nullable=False, server_default="ativo"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.ForeignKeyConstraint(["ilpi_id"], ["instituicoes.id"], ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chave", "ilpi_id", name="uq_perfil_chave_ilpi"),
        sa.CheckConstraint("escopo IN ('global','ilpi')", name="ck_perfil_escopo"),
        sa.CheckConstraint("situacao IN ('ativo','inativo')", name="ck_perfil_situacao"),
    )
    op.create_index("ix_perfis_ilpi_id", "perfis", ["ilpi_id"], unique=False)
    op.create_index("ix_perfis_chave", "perfis", ["chave"], unique=False)

    # ===== permissoes =====
    op.create_table(
        "permissoes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("modulo", sa.String(length=100), nullable=False),
        sa.Column("acao", sa.String(length=100), nullable=False),
        sa.Column("chave", sa.String(length=200), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chave", name="uq_permissao_chave"),
        sa.UniqueConstraint("modulo", "acao", name="uq_permissao_modulo_acao"),
    )

    # ===== perfil_permissoes =====
    op.create_table(
        "perfil_permissoes",
        sa.Column("perfil_id", sa.String(length=36), nullable=False),
        sa.Column("permissao_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.ForeignKeyConstraint(["perfil_id"], ["perfis.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permissao_id"], ["permissoes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("perfil_id", "permissao_id"),
    )

    # ===== funcionarios =====
    op.create_table(
        "funcionarios",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("ilpi_id", sa.String(length=36), nullable=False),
        sa.Column("usuario_id", sa.String(length=36), nullable=True),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("cpf", sa.String(length=14), nullable=True),
        sa.Column("telefone", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("cargo", sa.String(length=100), nullable=True),
        sa.Column("profissao", sa.String(length=100), nullable=True),
        sa.Column("conselho_profissional", sa.String(length=50), nullable=True),
        sa.Column("numero_conselho", sa.String(length=50), nullable=True),
        sa.Column("uf_conselho", sa.String(length=2), nullable=True),
        sa.Column("situacao", sa.String(length=20), nullable=False, server_default="ativo"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.ForeignKeyConstraint(["ilpi_id"], ["instituicoes.id"], ),
        sa.ForeignKeyConstraint(["usuario_id"], ["users.id"], ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cpf", "ilpi_id", name="uq_funcionario_cpf_ilpi"),
        sa.UniqueConstraint("ilpi_id", "usuario_id", name="uq_funcionario_ilpi_usuario"),
        sa.CheckConstraint("situacao IN ('ativo','afastado','inativo')", name="ck_funcionario_situacao"),
    )
    op.create_index("ix_funcionarios_ilpi_id", "funcionarios", ["ilpi_id"], unique=False)
    op.create_index("ix_funcionarios_usuario_id", "funcionarios", ["usuario_id"], unique=False)
    op.create_index("ix_funcionarios_cpf", "funcionarios", ["cpf"], unique=False)

    # ===== usuario_ilpi_perfis =====
    op.create_table(
        "usuario_ilpi_perfis",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("usuario_id", sa.String(length=36), nullable=False),
        sa.Column("ilpi_id", sa.String(length=36), nullable=True),
        sa.Column("perfil_id", sa.String(length=36), nullable=False),
        sa.Column("situacao", sa.String(length=20), nullable=False, server_default="ativo"),
        sa.Column("data_inicial", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("data_final", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.ForeignKeyConstraint(["ilpi_id"], ["instituicoes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["perfil_id"], ["perfis.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["usuario_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("usuario_id", "ilpi_id", "perfil_id", name="uq_usuario_ilpi_perfil"),
        sa.CheckConstraint("situacao IN ('ativo','inativo')", name="ck_usuario_ilpi_perfil_situacao"),
    )
    op.create_index("ix_usuario_ilpi_perfis_usuario", "usuario_ilpi_perfis", ["usuario_id"], unique=False)
    op.create_index("ix_usuario_ilpi_perfis_ilpi", "usuario_ilpi_perfis", ["ilpi_id"], unique=False)
    op.create_index("ix_usuario_ilpi_perfis_perfil", "usuario_ilpi_perfis", ["perfil_id"], unique=False)

    # ===== auditoria =====
    op.create_table(
        "auditoria",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("ilpi_id", sa.String(length=36), nullable=True),
        sa.Column("usuario_id", sa.String(length=36), nullable=True),
        sa.Column("acao", sa.String(length=100), nullable=False),
        sa.Column("entidade", sa.String(length=100), nullable=True),
        sa.Column("registro_id", sa.String(length=36), nullable=True),
        sa.Column("valores_anteriores", sa.Text(), nullable=True),
        sa.Column("valores_posteriores", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["ilpi_id"], ["instituicoes.id"], ),
        sa.ForeignKeyConstraint(["usuario_id"], ["users.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auditoria_ilpi_entidade", "auditoria", ["ilpi_id", "entidade"], unique=False)
    op.create_index("ix_auditoria_created_at", "auditoria", ["created_at"], unique=False)
    op.create_index("ix_auditoria_usuario", "auditoria", ["usuario_id"], unique=False)

    # ===== refresh_tokens =====
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("jti", sa.String(length=36), nullable=False),
        sa.Column("token_family", sa.String(length=36), nullable=False),
        sa.Column("ilpi_id", sa.String(length=36), nullable=True),
        sa.Column("perfil_id", sa.String(length=36), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["ilpi_id"], ["instituicoes.id"], ),
        sa.ForeignKeyConstraint(["perfil_id"], ["perfis.id"], ),
        sa.ForeignKeyConstraint(["replaced_by"], ["refresh_tokens.id"], ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_token_hash"),
        sa.UniqueConstraint("jti", name="uq_refresh_jti"),
    )
    op.create_index("ix_refresh_user_family", "refresh_tokens", ["user_id", "token_family"], unique=False)
    op.create_index("ix_refresh_expires", "refresh_tokens", ["expires_at"], unique=False)

    # ===== password_reset_tokens =====
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_token_hash"),
    )
    op.create_index("ix_pwd_reset_user", "password_reset_tokens", ["user_id"], unique=False)
    op.create_index("ix_pwd_reset_expires", "password_reset_tokens", ["expires_at"], unique=False)

    # ===== ilpi_id em entidades clínicas (nullable, FK simples, backfill determinístico) =====
    # SQLite requer batch mode para ALTER com FK; usa batch_alter_table para compat PG+SQLite
    tables_to_alter = [
        "familiares",
        "avaliacoes",
        "planos_cuidados",
        "tarefas",
        "prescricoes",
        "sinais_vitais",
        "intercorrencias",
    ]
    for tbl in tables_to_alter:
        with op.batch_alter_table(tbl) as batch_op:
            batch_op.add_column(sa.Column("ilpi_id", sa.String(length=36), nullable=True))
            batch_op.create_foreign_key(f"fk_{tbl}_ilpi", "instituicoes", ["ilpi_id"], ["id"])
        op.create_index(f"ix_{tbl}_ilpi_id", tbl, ["ilpi_id"], unique=False)

    # Backfill determinístico: ilpi_id = instituicao_id do residente
    # Usa UPDATE com subselect compatível SQLite e PG
    for tbl in tables_to_alter:
        # Apenas tabelas com residente_id
        op.execute(
            sa.text(
                f"UPDATE {tbl} SET ilpi_id = (SELECT instituicao_id FROM residentes WHERE residentes.id = {tbl}.residente_id) "
                f"WHERE {tbl}.residente_id IS NOT NULL AND {tbl}.ilpi_id IS NULL"
            )
        )

    # Diagnóstico de órfãos: residente_id que não existe em residentes
    # Falha determinística se houver órfão para garantir integridade antes de Fase 2
    for tbl in tables_to_alter:
        # Verifica órfãos via SELECT; se encontrar, levanta exceção com diagnóstico
        # Em SQL puro não podemos levantar exceção direta, então fazemos verificação em Python via conn
        conn = op.get_bind()
        result = conn.execute(
            sa.text(f"SELECT {tbl}.id, {tbl}.residente_id FROM {tbl} LEFT JOIN residentes ON residentes.id = {tbl}.residente_id WHERE {tbl}.residente_id IS NOT NULL AND residentes.id IS NULL LIMIT 5")
        ).fetchall()
        if result:
            orphan_ids = ", ".join([r[0] for r in result])
            raise Exception(
                f"Migration 002 falhou: registros órfãos em {tbl} (residente_id inexistente). "
                f"Exemplos: {orphan_ids}. Corrija ou remova antes de aplicar."
            )

    # Nota: ILPI Modelo não criada aqui (observação C3). Apenas estrutura.
    # Nota: checks de instituicoes mantidos via modelo; não adiciona trigger.


def downgrade() -> None:
    tables_to_alter = [
        "intercorrencias",
        "sinais_vitais",
        "prescricoes",
        "tarefas",
        "planos_cuidados",
        "avaliacoes",
        "familiares",
    ]
    for tbl in tables_to_alter:
        op.drop_index(f"ix_{tbl}_ilpi_id", table_name=tbl)
        with op.batch_alter_table(tbl) as batch_op:
            batch_op.drop_constraint(f"fk_{tbl}_ilpi", type_="foreignkey")
            batch_op.drop_column("ilpi_id")

    op.drop_index("ix_pwd_reset_expires", table_name="password_reset_tokens")
    op.drop_index("ix_pwd_reset_user", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")

    op.drop_index("ix_refresh_expires", table_name="refresh_tokens")
    op.drop_index("ix_refresh_user_family", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index("ix_auditoria_usuario", table_name="auditoria")
    op.drop_index("ix_auditoria_created_at", table_name="auditoria")
    op.drop_index("ix_auditoria_ilpi_entidade", table_name="auditoria")
    op.drop_table("auditoria")

    op.drop_index("ix_usuario_ilpi_perfis_perfil", table_name="usuario_ilpi_perfis")
    op.drop_index("ix_usuario_ilpi_perfis_ilpi", table_name="usuario_ilpi_perfis")
    op.drop_index("ix_usuario_ilpi_perfis_usuario", table_name="usuario_ilpi_perfis")
    op.drop_table("usuario_ilpi_perfis")

    op.drop_index("ix_funcionarios_cpf", table_name="funcionarios")
    op.drop_index("ix_funcionarios_usuario_id", table_name="funcionarios")
    op.drop_index("ix_funcionarios_ilpi_id", table_name="funcionarios")
    op.drop_table("funcionarios")

    op.drop_table("perfil_permissoes")

    op.drop_table("permissoes")
    op.drop_index("ix_perfis_chave", table_name="perfis")
    op.drop_index("ix_perfis_ilpi_id", table_name="perfis")
    op.drop_table("perfis")

    op.drop_table("bootstrap_state")

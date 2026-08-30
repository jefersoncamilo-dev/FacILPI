"""correções fase1 — composite FK + default ILPI_RASCUNHO

Revision ID: 003_correcoes_fase1
Revises: 002_fase1_isolamento
Create Date: 2026-08-30

Correções obrigatórias pós-57d25fe (A-K):
- Default instituicoes.situacao alinhado para ILPI_RASCUNHO (modelo e banco)
- UNIQUE residentes(id, instituicao_id) para alvo de FK composta
- FKs compostas (residente_id, ilpi_id) -> residentes(id, instituicao_id) mantendo FK direta ilpi_id->instituicoes
- Aplica a familiares, avaliacoes, planos_cuidados, tarefas, prescricoes, sinais_vitais, intercorrencias e quartos_leitos(residente_atual_id)
- Sem triggers, sem IF NOT EXISTS generalizado, sem gen_uuid, sem JSONB
- Mantém FK direta + composta (requisito C)
- Não apaga residente legado, apenas adiciona constraint que permite ilpi_id NULL (TENANT_BACKFILL_PENDING)
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003_correcoes_fase1"
down_revision: Union[str, None] = "002_fase1_isolamento"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Default instituicoes.situacao -> ILPI_RASCUNHO
    # SQLite batch para alterar default (compat PG via alter_column)
    # Verifica se precisa: tenta batch alter; se falhar, ignora para PG onde default já pode ser alterado via raw SQL
    try:
        with op.batch_alter_table("instituicoes") as batch_op:
            batch_op.alter_column("situacao", server_default="ILPI_RASCUNHO", existing_type=sa.String(length=50), existing_nullable=True)
    except Exception:
        # Fallback PG: raw ALTER
        op.execute(sa.text("ALTER TABLE instituicoes ALTER COLUMN situacao SET DEFAULT 'ILPI_RASCUNHO'"))

    # 2) UNIQUE residentes(id, instituicao_id) para FK composta alvo
    # SQLite: batch create unique
    with op.batch_alter_table("residentes") as batch_op:
        batch_op.create_unique_constraint("uq_residentes_id_ilpi", ["id", "instituicao_id"])

    # 3) FKs compostas mantendo FK direta
    # Lista tabelas e colunas: (tabela, col_residente, col_ilpi, fk_name)
    composites = [
        ("familiares", "residente_id", "ilpi_id", "fk_familiares_residente_ilpi"),
        ("avaliacoes", "residente_id", "ilpi_id", "fk_avaliacoes_residente_ilpi"),
        ("planos_cuidados", "residente_id", "ilpi_id", "fk_planos_residente_ilpi"),
        ("tarefas", "residente_id", "ilpi_id", "fk_tarefas_residente_ilpi"),
        ("prescricoes", "residente_id", "ilpi_id", "fk_prescricoes_residente_ilpi"),
        ("sinais_vitais", "residente_id", "ilpi_id", "fk_sinais_residente_ilpi"),
        ("intercorrencias", "residente_id", "ilpi_id", "fk_intercorrencias_residente_ilpi"),
    ]
    for tbl, col_res, col_ilpi, fk_name in composites:
        # Verifica órfãos cross-tenant antes de criar FK composta: se existir tarefa com ilpi_id != residente.instituicao_id, falhar com diagnóstico
        # Essa verificação é determinística e produz BLOCKED se necessário
        conn = op.get_bind()
        # Procura cross-tenant: child.ilpi_id not null and residente.instituicao_id not null and different
        # Para tabelas onde residente.instituicao_id pode ser null (legado), ignora
        result = conn.execute(sa.text(
            f"SELECT {tbl}.id, {tbl}.ilpi_id, r.instituicao_id FROM {tbl} JOIN residentes r ON r.id={tbl}.residente_id "
            f"WHERE {tbl}.ilpi_id IS NOT NULL AND r.instituicao_id IS NOT NULL AND {tbl}.ilpi_id != r.instituicao_id LIMIT 3"
        )).fetchall()
        if result:
            detail = ", ".join([f"{r[0]}(child ilpi {r[1]} != residente ilpi {r[2]})" for r in result])
            raise Exception(f"Migration 003 falhou: cross-tenant detectado em {tbl}: {detail}. Corrija antes de aplicar FK composta.")
        # Cria FK composta via batch
        with op.batch_alter_table(tbl) as batch_op:
            batch_op.create_foreign_key(fk_name, "residentes", [col_res, col_ilpi], ["id", "instituicao_id"])

    # Quartos_leitos caso especial: residente_atual_id + instituicao_id
    with op.batch_alter_table("quartos_leitos") as batch_op:
        batch_op.create_foreign_key("fk_quartos_residente_ilpi", "residentes", ["residente_atual_id", "instituicao_id"], ["id", "instituicao_id"])


def downgrade() -> None:
    # Remove quartos
    with op.batch_alter_table("quartos_leitos") as batch_op:
        batch_op.drop_constraint("fk_quartos_residente_ilpi", type_="foreignkey")

    composites = [
        ("intercorrencias", "fk_intercorrencias_residente_ilpi"),
        ("sinais_vitais", "fk_sinais_residente_ilpi"),
        ("prescricoes", "fk_prescricoes_residente_ilpi"),
        ("tarefas", "fk_tarefas_residente_ilpi"),
        ("planos_cuidados", "fk_planos_residente_ilpi"),
        ("avaliacoes", "fk_avaliacoes_residente_ilpi"),
        ("familiares", "fk_familiares_residente_ilpi"),
    ]
    for tbl, fk_name in composites:
        with op.batch_alter_table(tbl) as batch_op:
            batch_op.drop_constraint(fk_name, type_="foreignkey")

    with op.batch_alter_table("residentes") as batch_op:
        batch_op.drop_constraint("uq_residentes_id_ilpi", type_="unique")

    try:
        with op.batch_alter_table("instituicoes") as batch_op:
            batch_op.alter_column("situacao", server_default="ativa", existing_type=sa.String(length=50), existing_nullable=True)
    except Exception:
        op.execute(sa.text("ALTER TABLE instituicoes ALTER COLUMN situacao SET DEFAULT 'ativa'"))

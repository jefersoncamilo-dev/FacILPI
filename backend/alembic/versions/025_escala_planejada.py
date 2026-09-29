"""025_escala_planejada: escala planejada x plantao real (#122).

Camada Operacional, Fase 2B (ROADMAP §16). ``escalas`` registra quem DEVERIA
trabalhar (previsto); ``plantoes`` (024) continua sendo quem EFETIVAMENTE
trabalhou. Quando o plantao nasce de uma escala, a escala guarda ``plantao_id``
(vinculo criado com a tabela: nenhuma alteracao em ``plantoes``, sem recriar
tabela no SQLite nem arriscar os indices unicos parciais da 024).

Suporta apenas: previsto, presente/efetivo, ausencia (com motivo),
substituicao simples (nova escala ``substituicao`` apontando a original) e
cobertura (escala extra ou plantao sem escala). Faltas/trocas/redistribuicao
avancadas ficam para a Fase 8. Nao e RH: sem folha, ponto ou banco de horas.

Nenhuma permissao nova: ``escala:gerenciar`` planeja; ``plantao:registrar``
inicia o proprio plantao. Historico nao se apaga: ausencia e cancelamento sao
situacoes, nao DELETE. Downgrade recusa se houver escala ou plantao ligado.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "025_escala_planejada"
down_revision: Union[str, None] = "024_escala_estrutura"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("025 suporta somente SQLite e PostgreSQL")
    op.create_table(
        "escalas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("funcionario_id", sa.String(36), nullable=False),
        sa.Column("turno_id", sa.String(36)),
        sa.Column("area_id", sa.String(36)),
        sa.Column("inicio_previsto", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fim_previsto", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("situacao", sa.String(20), nullable=False),
        sa.Column("substitui_escala_id", sa.String(36)),
        sa.Column("plantao_id", sa.String(36)),
        sa.Column("motivo", sa.Text),
        sa.Column("criado_por", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("atualizado_por", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("id", "ilpi_id", name="uq_escalas_id_ilpi"),
        sa.ForeignKeyConstraint(["funcionario_id", "ilpi_id"], ["funcionarios.id", "funcionarios.ilpi_id"],
                                name="fk_escalas_funcionario", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["turno_id", "ilpi_id"], ["turnos.id", "turnos.ilpi_id"],
                                name="fk_escalas_turno", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["area_id", "ilpi_id"], ["areas_operacionais.id", "areas_operacionais.ilpi_id"],
                                name="fk_escalas_area", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["substitui_escala_id", "ilpi_id"], ["escalas.id", "escalas.ilpi_id"],
                                name="fk_escalas_substitui", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["plantao_id", "ilpi_id"], ["plantoes.id", "plantoes.ilpi_id"],
                                name="fk_escalas_plantao", ondelete="RESTRICT"),
        sa.CheckConstraint("plantao_id IS NULL OR situacao = 'prevista'", name="ck_escalas_plantao_prevista"),
        sa.CheckConstraint("fim_previsto > inicio_previsto", name="ck_escalas_periodo"),
        sa.CheckConstraint("tipo IN ('regular','substituicao','cobertura')", name="ck_escalas_tipo"),
        sa.CheckConstraint("situacao IN ('prevista','ausente','cancelada')", name="ck_escalas_situacao"),
        sa.CheckConstraint("(tipo = 'substituicao') = (substitui_escala_id IS NOT NULL)", name="ck_escalas_substituicao"),
        sa.CheckConstraint("situacao = 'prevista' OR (motivo IS NOT NULL AND length(trim(motivo)) > 0)",
                           name="ck_escalas_motivo"),
    )
    op.create_index("ix_escalas_ilpi_inicio", "escalas", ["ilpi_id", "inicio_previsto"])
    op.create_index("ix_escalas_funcionario", "escalas", ["ilpi_id", "funcionario_id", "inicio_previsto"])
    # Uma escala tem no maximo UMA substituicao valida (a substituta pode, por sua vez, ser substituida).
    op.create_index("uq_escalas_substituicao", "escalas", ["substitui_escala_id"], unique=True,
                    sqlite_where=sa.text("substitui_escala_id IS NOT NULL AND situacao != 'cancelada'"),
                    postgresql_where=sa.text("substitui_escala_id IS NOT NULL AND situacao != 'cancelada'"))
    # Um plantao real cumpre no maximo uma escala.
    op.create_index("uq_escalas_plantao", "escalas", ["plantao_id"], unique=True,
                    sqlite_where=sa.text("plantao_id IS NOT NULL"), postgresql_where=sa.text("plantao_id IS NOT NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM escalas LIMIT 1")).first() is not None:
        raise RuntimeError("025 recusa downgrade: escalas tem historico de planejamento")
    op.drop_index("uq_escalas_plantao", table_name="escalas")
    op.drop_index("uq_escalas_substituicao", table_name="escalas")
    op.drop_index("ix_escalas_funcionario", table_name="escalas")
    op.drop_index("ix_escalas_ilpi_inicio", table_name="escalas")
    op.drop_table("escalas")

"""037 — Portal da familia configuravel por ILPI (#303).

Uma linha por ILPI em ``portal_familia_config``: ``ativo`` liga o portal inteiro
e ``categorias`` lista o que o familiar pode ver. Sem linha = portal desligado e
todas as categorias bloqueadas; o upgrade nao cria linha para nenhuma ILPI, entao
o portal liberado em #271 fica desligado ate a equipe liga-lo.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "037_portal_familia_config"
down_revision: Union[str, None] = "036_portal_familia"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("037 suporta somente SQLite e PostgreSQL")
    op.create_table(
        "portal_familia_config",
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("categorias", sa.JSON(), nullable=False),
        sa.Column("atualizado_por", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("portal_familia_config")

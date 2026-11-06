"""032 — percentual de refeicao consumido (G4, D6).

A refeicao e registrada como execucao de cuidado (``execucoes_cuidado``); nao ha
tabela propria. Coluna opcional ``percentual_consumido`` com CHECK 0/25/50/75/100.
Sem grants: quem ja registra cuidado (``execucoes:criar``) informa o percentual.

Downgrade recusa quando ha percentual registrado (nao descarta fato assistencial).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "032_percentual_refeicao"
down_revision: Union[str, None] = "031_grants_medicacao"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("032 suporta somente SQLite e PostgreSQL")
    # ADD COLUMN com CHECK de coluna funciona nos dois bancos sem recriar a
    # tabela (o batch do SQLite reescreveria os indices parciais da D.2).
    bind.execute(sa.text(
        "ALTER TABLE execucoes_cuidado ADD COLUMN percentual_consumido INTEGER "
        "CONSTRAINT ck_exec_percentual CHECK "
        "(percentual_consumido IS NULL OR percentual_consumido IN (0, 25, 50, 75, 100))"))


def downgrade() -> None:
    bind = op.get_bind()
    registrados = bind.execute(sa.text(
        "SELECT count(*) FROM execucoes_cuidado WHERE percentual_consumido IS NOT NULL")).scalar()
    if registrados:
        raise RuntimeError(f"032 recusa downgrade: {registrados} execucoes com percentual_consumido")
    bind.execute(sa.text("ALTER TABLE execucoes_cuidado DROP COLUMN percentual_consumido"))

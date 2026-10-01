"""#132: estado de alerta "expirado sem registro".

Cuidado/dose que sai da janela de 24 h da projecao SEM execucao nao pode
encerrar o estado do alerta como "resolvido pela fonte": passa a encerrar como
``situacao='expirado'`` / ``encerramento='janela'``. So amplia as CHECKs de
``alerta_estados`` (026); nenhum dado e apagado ou reescrito.

No SQLite a CHECK so muda recriando a tabela (batch): o indice unico parcial e
removido antes e recriado depois, com o mesmo WHERE (a reflexao do batch nao o
preserva de forma confiavel). Downgrade recusa se ja houver estado expirado.

Revision ID: 028_alerta_expirado
Revises: 027_passagem_plantao
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "028_alerta_expirado"
down_revision: Union[str, None] = "027_passagem_plantao"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABELA = "alerta_estados"
ABERTO = "situacao IN ('assumido','em_atendimento')"

SITUACAO_026 = "situacao IN ('assumido','em_atendimento','resolvido','liberado')"
ENCERRAMENTO_026 = (
    "(situacao IN ('assumido','em_atendimento') AND encerrado_em IS NULL AND encerramento IS NULL) OR "
    "(situacao = 'resolvido' AND encerramento = 'fonte' AND encerrado_em IS NOT NULL) OR "
    "(situacao = 'liberado' AND encerramento = 'liberado' AND encerrado_em IS NOT NULL)"
)
SITUACAO_028 = "situacao IN ('assumido','em_atendimento','resolvido','liberado','expirado')"
ENCERRAMENTO_028 = ENCERRAMENTO_026 + " OR (situacao = 'expirado' AND encerramento = 'janela' AND encerrado_em IS NOT NULL)"


def _preflight(bind):
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("028 suporta somente SQLite e PostgreSQL")


def _trocar_checks(situacao: str, encerramento: str) -> None:
    op.drop_index("uq_alerta_estados_aberto", table_name=TABELA)
    with op.batch_alter_table(TABELA) as batch:
        batch.drop_constraint("ck_alerta_estados_situacao", type_="check")
        batch.drop_constraint("ck_alerta_estados_encerramento", type_="check")
        batch.create_check_constraint("ck_alerta_estados_situacao", situacao)
        batch.create_check_constraint("ck_alerta_estados_encerramento", encerramento)
    op.create_index("uq_alerta_estados_aberto", TABELA, ["ilpi_id", "alerta_id"], unique=True,
                    sqlite_where=sa.text(ABERTO), postgresql_where=sa.text(ABERTO))


def upgrade() -> None:
    _preflight(op.get_bind())
    _trocar_checks(SITUACAO_028, ENCERRAMENTO_028)


def downgrade() -> None:
    bind = op.get_bind()
    _preflight(bind)
    if bind.execute(sa.text("SELECT 1 FROM alerta_estados WHERE situacao = 'expirado' LIMIT 1")).first() is not None:
        raise RuntimeError("028 recusa downgrade: ha estados 'expirado' (historico nao e reescrito)")
    _trocar_checks(SITUACAO_026, ENCERRAMENTO_026)

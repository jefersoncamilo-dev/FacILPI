"""005_fase3a_bootstrap_auth: bootstrap seguro e onboarding inicial.

Expande a máquina de estados e adiciona os campos mínimos para primeiro
acesso, refresh-cookie e ativação controlada da ILPI. Não cria usuários,
ILPIs, funcionários, perfis ou vínculos.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "005_fase3a_bootstrap_auth"
down_revision: Union[str, None] = "004_catalogo_permissoes_rbac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BOOTSTRAP_STATES = (
    "UNINITIALIZED",
    "PLATFORM_BOOTSTRAPPED",
    "FIRST_PASSWORD_CHANGED",
    "ILPI_CREATED",
    "ONBOARDING_IN_PROGRESS",
    "ONBOARDING_COMPLETED",
)

BOOTSTRAP_STATE_CHECK = (
    "estado IN ("
    + ",".join(f"'{state}'" for state in BOOTSTRAP_STATES)
    + ")"
)

INSTITUICAO_SITUACOES = (
    "ativa",
    "rascunho",
    "ILPI_RASCUNHO",
    "ONBOARDING_IN_PROGRESS",
    "READY_FOR_ACTIVATION",
    "ACTIVE",
    "ATIVA",
    "SUSPENSA",
    "INATIVA",
    "suspensa",
    "inativa",
)

INSTITUICAO_SITUACAO_CHECK = (
    "situacao IN ("
    + ",".join(f"'{state}'" for state in INSTITUICAO_SITUACOES)
    + ")"
)


def _columns(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _check_names(bind, table_name: str) -> set[str]:
    return {
        constraint.get("name")
        for constraint in sa.inspect(bind).get_check_constraints(table_name)
        if constraint.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()

    user_columns = _columns(bind, "users")
    with op.batch_alter_table("users") as batch_op:
        if "is_superuser" not in user_columns:
            batch_op.add_column(
                sa.Column(
                    "is_superuser",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )
        if "exige_troca_senha" not in user_columns:
            batch_op.add_column(
                sa.Column(
                    "exige_troca_senha",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )

    institution_columns = _columns(bind, "instituicoes")
    institution_checks = _check_names(bind, "instituicoes")
    with op.batch_alter_table("instituicoes") as batch_op:
        if "finalidade" not in institution_columns:
            batch_op.add_column(sa.Column("finalidade", sa.String(length=255), nullable=True))
        if "uf" not in institution_columns:
            batch_op.add_column(sa.Column("uf", sa.String(length=2), nullable=True))
        if "ck_instituicoes_situacao" in institution_checks:
            batch_op.drop_constraint("ck_instituicoes_situacao", type_="check")
        batch_op.create_check_constraint(
            "ck_instituicoes_situacao",
            INSTITUICAO_SITUACAO_CHECK,
        )

    bootstrap_columns = _columns(bind, "bootstrap_state")
    bootstrap_checks = _check_names(bind, "bootstrap_state")
    with op.batch_alter_table("bootstrap_state") as batch_op:
        if "ck_bootstrap_estado" in bootstrap_checks:
            batch_op.drop_constraint("ck_bootstrap_estado", type_="check")
        if "ilpi_created_at" not in bootstrap_columns:
            batch_op.add_column(sa.Column("ilpi_created_at", sa.DateTime(timezone=True), nullable=True))
        if "onboarding_started_at" not in bootstrap_columns:
            batch_op.add_column(sa.Column("onboarding_started_at", sa.DateTime(timezone=True), nullable=True))
        if "onboarding_completed_at" not in bootstrap_columns:
            batch_op.add_column(sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_check_constraint("ck_bootstrap_estado", BOOTSTRAP_STATE_CHECK)

    op.execute(sa.text("UPDATE users SET is_superuser = false WHERE is_superuser IS NULL"))
    op.execute(sa.text("UPDATE users SET exige_troca_senha = false WHERE exige_troca_senha IS NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    invalid_state = bind.execute(
        sa.text(
            "SELECT estado FROM bootstrap_state "
            "WHERE estado NOT IN ('UNINITIALIZED','PLATFORM_BOOTSTRAPPED','FIRST_PASSWORD_CHANGED') "
            "LIMIT 1"
        )
    ).scalar_one_or_none()
    if invalid_state is not None:
        raise RuntimeError(
            "Downgrade 005 bloqueado: bootstrap_state avançado para "
            f"{invalid_state!r}."
        )

    bootstrap_checks = _check_names(bind, "bootstrap_state")
    with op.batch_alter_table("bootstrap_state") as batch_op:
        if "ck_bootstrap_estado" in bootstrap_checks:
            batch_op.drop_constraint("ck_bootstrap_estado", type_="check")
        for column_name in (
            "onboarding_completed_at",
            "onboarding_started_at",
            "ilpi_created_at",
        ):
            if column_name in _columns(bind, "bootstrap_state"):
                batch_op.drop_column(column_name)
        batch_op.create_check_constraint(
            "ck_bootstrap_estado",
            "estado IN ('UNINITIALIZED','PLATFORM_BOOTSTRAPPED','FIRST_PASSWORD_CHANGED')",
        )

    institution_checks = _check_names(bind, "instituicoes")
    with op.batch_alter_table("instituicoes") as batch_op:
        if "ck_instituicoes_situacao" in institution_checks:
            batch_op.drop_constraint("ck_instituicoes_situacao", type_="check")
        for column_name in ("uf", "finalidade"):
            if column_name in _columns(bind, "instituicoes"):
                batch_op.drop_column(column_name)

    user_columns = _columns(bind, "users")
    with op.batch_alter_table("users") as batch_op:
        if "exige_troca_senha" in user_columns:
            batch_op.drop_column("exige_troca_senha")
        if "is_superuser" in user_columns:
            batch_op.drop_column("is_superuser")

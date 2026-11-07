"""036 — Portal da familia (#271).

O familiar ganha conta propria (``familiares.usuario_id``) liberada ou bloqueada
pela equipe (``portal_ativo``). Papel proprio ``familiar_portal`` com uma unica
permissao, ``portal_familia:ler``, sem nenhum grant clinico. Recados da equipe
para a familia ficam em ``portal_recados`` (so leitura para o familiar).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "036_portal_familia"
down_revision: Union[str, None] = "035_complementares"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSOES = (
    {"id": "fac36000-0000-4000-8000-000000000001", "modulo": "portal_familia", "acao": "ler",
     "chave": "portal_familia:ler", "descricao": "Ver o portal do proprio residente vinculado."},
    {"id": "fac36000-0000-4000-8000-000000000002", "modulo": "portal_familia", "acao": "publicar",
     "chave": "portal_familia:publicar", "descricao": "Liberar o portal e publicar recados para a familia."},
)
TEMPLATE = {"id": "fac36100-0000-4000-8000-000000000001", "chave": "familiar_portal", "nome": "Familiar (Portal)"}
PUBLICAR = ("ilpi_admin", "enfermagem", "responsavel_tecnico")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("036 suporta somente SQLite e PostgreSQL")
    with op.batch_alter_table("familiares") as batch:
        batch.add_column(sa.Column("usuario_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("portal_ativo", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_foreign_key("fk_familiares_usuario", "users", ["usuario_id"], ["id"], ondelete="RESTRICT")
        batch.create_unique_constraint("uq_familiares_usuario", ["usuario_id"])
    op.create_table(
        "portal_recados",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("residente_id", sa.String(36), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("autor_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("autor_nome", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["residente_id", "ilpi_id"], ["residentes.id", "residentes.instituicao_id"],
                                name="fk_recado_residente", ondelete="RESTRICT"),
    )
    for p in PERMISSOES:
        bind.execute(sa.text("INSERT INTO permissoes (id, modulo, acao, chave, descricao) VALUES (:id, :modulo, :acao, :chave, :descricao)"), p)
    bind.execute(sa.text("INSERT INTO perfis (id, ilpi_id, nome, chave, descricao, escopo, situacao) VALUES "
                         "(:id, NULL, :nome, :chave, 'Acesso do familiar ao portal, sem dados clinicos.', 'ilpi', 'ativo')"), TEMPLATE)
    bind.execute(sa.text("INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:p, :m)"),
                 {"p": TEMPLATE["id"], "m": PERMISSOES[0]["id"]})
    for chave in PUBLICAR:
        for (perfil,) in bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c"), {"c": chave}).all():
            bind.execute(sa.text("INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:p, :m)"),
                         {"p": perfil, "m": PERMISSOES[1]["id"]})


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM familiares WHERE usuario_id IS NOT NULL")).first():
        raise RuntimeError("036 recusa downgrade: ha familiares com conta do portal")
    for p in PERMISSOES:
        bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE permissao_id = :m"), {"m": p["id"]})
    perfis = [r[0] for r in bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c"), {"c": TEMPLATE["chave"]}).all()]
    for perfil in perfis:
        if bind.execute(sa.text("SELECT 1 FROM usuario_ilpi_perfis WHERE perfil_id = :p"), {"p": perfil}).first():
            raise RuntimeError("036 recusa downgrade: perfil familiar_portal atribuido")
        bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE perfil_id = :p"), {"p": perfil})
        bind.execute(sa.text("DELETE FROM perfis WHERE id = :p"), {"p": perfil})
    for p in PERMISSOES:
        bind.execute(sa.text("DELETE FROM permissoes WHERE id = :m"), {"m": p["id"]})
    op.drop_table("portal_recados")
    with op.batch_alter_table("familiares") as batch:
        batch.drop_constraint("uq_familiares_usuario", type_="unique")
        batch.drop_constraint("fk_familiares_usuario", type_="foreignkey")
        batch.drop_column("portal_ativo")
        batch.drop_column("usuario_id")

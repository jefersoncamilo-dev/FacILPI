"""030 — saida do residente (N2, #171).

Tabela append-only ``residente_saidas`` (obito, transferencia, desligamento,
retorno a familia), com estorno que preserva o registro original, e as
permissoes ``residentes:registrar_saida`` (ilpi_admin, responsavel_tecnico,
enfermagem, administrativo) e ``residentes:estornar_saida`` (ilpi_admin,
responsavel_tecnico). Templates e clones por chave; profissao nao concede.

Downgrade recusa historico de saidas e vinculos externos.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "030_saida_residente"
down_revision: Union[str, None] = "029_autoria_autor_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSOES = (
    {"id": "fac11000-0000-4000-8000-000000000102", "chave": "residentes:registrar_saida", "modulo": "residentes",
     "acao": "registrar_saida", "descricao": "Registrar a saida do residente (obito, transferencia, desligamento, retorno a familia)."},
    {"id": "fac11000-0000-4000-8000-000000000103", "chave": "residentes:estornar_saida", "modulo": "residentes",
     "acao": "estornar_saida", "descricao": "Estornar saida registrada por engano, preservando o registro original."},
)
GRANTS = {
    "ilpi_admin": ("residentes:registrar_saida", "residentes:estornar_saida"),
    "responsavel_tecnico": ("residentes:registrar_saida", "residentes:estornar_saida"),
    "enfermagem": ("residentes:registrar_saida",),
    "administrativo": ("residentes:registrar_saida",),
}
CAMPOS = ("id", "modulo", "acao", "chave", "descricao")


def _id_da_chave(chave):
    return next(p["id"] for p in PERMISSOES if p["chave"] == chave)


def _perfis(bind, chave):
    rows = bind.execute(sa.text("SELECT id, ilpi_id FROM perfis WHERE chave = :c"), {"c": chave}).all()
    if not any(r[1] is None for r in rows):
        raise RuntimeError(f"030 exige o template {chave}; execute as migrations em ordem")
    return [r[0] for r in rows]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("030 suporta somente SQLite e PostgreSQL")
    for registro in PERMISSOES:
        row = bind.execute(sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"),
                           {"id": registro["id"]}).mappings().first()
        if row is None:
            conflito = bind.execute(
                sa.text("SELECT id FROM permissoes WHERE chave = :chave OR (modulo = :modulo AND acao = :acao)"),
                {k: registro[k] for k in ("chave", "modulo", "acao")}).first()
            if conflito is not None:
                raise RuntimeError(f"030 recusa catalogo preexistente para {registro['chave']} (id {conflito[0]})")
            bind.execute(sa.text("INSERT INTO permissoes (id, modulo, acao, chave, descricao) "
                                 "VALUES (:id, :modulo, :acao, :chave, :descricao)"), registro)
        else:
            diferencas = {f: (row[f], registro[f]) for f in CAMPOS if row[f] != registro[f]}
            if diferencas:
                raise RuntimeError(f"030 permissao adulterada: {diferencas}")
    for chave_perfil, chaves in GRANTS.items():
        for perfil in _perfis(bind, chave_perfil):
            for chave in chaves:
                permissao = _id_da_chave(chave)
                if bind.execute(sa.text("SELECT 1 FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"),
                                {"p": perfil, "m": permissao}).first() is None:
                    bind.execute(sa.text("INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:p, :m)"),
                                 {"p": perfil, "m": permissao})

    op.create_table(
        "residente_saidas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("residente_id", sa.String(36), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("ocorrido_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_obito", sa.String(20)),
        sa.Column("destino_tipo", sa.String(20)),
        sa.Column("destino_descricao", sa.String(255)),
        sa.Column("motivo_desligamento", sa.String(30)),
        sa.Column("observacao", sa.String(500)),
        sa.Column("registrado_por", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("registrado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("estornado_em", sa.DateTime(timezone=True)),
        sa.Column("estornado_por", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("motivo_estorno", sa.String(500)),
        sa.ForeignKeyConstraint(["residente_id", "ilpi_id"], ["residentes.id", "residentes.instituicao_id"],
                                name="fk_residente_saidas_residente_ilpi", ondelete="RESTRICT"),
        sa.CheckConstraint("tipo IN ('obito','transferencia','desligamento','retorno_familia')",
                           name="ck_residente_saidas_tipo"),
        sa.CheckConstraint("tipo <> 'obito' OR local_obito IN ('ilpi','hospital')",
                           name="ck_residente_saidas_obito_local"),
        sa.CheckConstraint("tipo <> 'transferencia' OR (destino_tipo IN ('instituicao','hospital') "
                           "AND destino_descricao IS NOT NULL)", name="ck_residente_saidas_transferencia_destino"),
        sa.CheckConstraint("tipo <> 'desligamento' OR motivo_desligamento IN "
                           "('fim_contrato','pedido_familia','pedido_residente','pedido_ilpi')",
                           name="ck_residente_saidas_desligamento_motivo"),
        sa.CheckConstraint("(estornado_em IS NULL AND estornado_por IS NULL AND motivo_estorno IS NULL) OR "
                           "(estornado_em IS NOT NULL AND estornado_por IS NOT NULL AND motivo_estorno IS NOT NULL)",
                           name="ck_residente_saidas_estorno"),
    )
    op.create_index("ix_residente_saidas_ilpi_residente", "residente_saidas", ["ilpi_id", "residente_id"])
    # No maximo uma saida vigente (nao estornada) por residente.
    op.create_index("uq_residente_saidas_vigente", "residente_saidas", ["ilpi_id", "residente_id"], unique=True,
                    sqlite_where=sa.text("estornado_em IS NULL"), postgresql_where=sa.text("estornado_em IS NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM residente_saidas LIMIT 1")).first() is not None:
        raise RuntimeError("030 recusa downgrade: residente_saidas tem historico de saidas")
    permitidos: dict[str, set] = {p["id"]: set() for p in PERMISSOES}
    for chave_perfil, chaves in GRANTS.items():
        perfis = _perfis(bind, chave_perfil)
        for chave in chaves:
            permitidos[_id_da_chave(chave)].update(perfis)
    for permissao, perfis in permitidos.items():
        vinculos = {r[0] for r in bind.execute(sa.text("SELECT perfil_id FROM perfil_permissoes WHERE permissao_id = :m"),
                                               {"m": permissao}).all()}
        externos = sorted(vinculos - perfis)
        if externos:
            raise RuntimeError(f"030 recusa downgrade: vinculos externos a {permissao}: {externos}")
    op.drop_index("uq_residente_saidas_vigente", table_name="residente_saidas")
    op.drop_index("ix_residente_saidas_ilpi_residente", table_name="residente_saidas")
    op.drop_table("residente_saidas")
    for registro in PERMISSOES:
        bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE permissao_id = :m"), {"m": registro["id"]})
        bind.execute(sa.text("DELETE FROM permissoes WHERE id = :id"), {"id": registro["id"]})

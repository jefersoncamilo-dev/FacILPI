"""026_alerta_estados: estado persistente do alerta (#123).

Camada Operacional, Fase 3. Tres camadas, nunca duas verdades:
fonte (a situacao existe?) -> projecao (o alerta, com id estavel) -> ESTADO
(o que a equipe fez: assumiu, esta em atendimento). O estado nunca cria nem
mantem alerta: quando a projecao deixa de gerar o id, o estado aberto e
encerrado como ``resolvido`` pela fonte. Estado e por episodio: um aberto por
(ILPI, alerta_id); fechado, fica como historico.

Permissao nova ``alertas:assumir`` (modulo clinico ``alertas``, ILPI-only) para
o template ``ilpi_admin`` e os 5 institucionais da 015 (quem ja le alertas),
templates e clones por chave. ``platform_superuser`` nada.
Downgrade recusa historico de estados e vinculos externos da permissao.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "026_alerta_estados"
down_revision: Union[str, None] = "025_escala_planejada"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSAO = {
    "id": "fac11000-0000-4000-8000-000000000099",
    "chave": "alertas:assumir",
    "modulo": "alertas",
    "acao": "assumir",
    "descricao": "Assumir, iniciar atendimento e liberar alertas da ILPI atual (a resolucao vem da fonte).",
}
CAMPOS = ("id", "modulo", "acao", "chave", "descricao")
PERFIS = ("ilpi_admin", "cuidador", "enfermagem", "medico", "responsavel_tecnico", "administrativo")


def _perfis(bind):
    rows = bind.execute(
        sa.text("SELECT id, chave, ilpi_id FROM perfis WHERE chave IN :chaves").bindparams(sa.bindparam("chaves", expanding=True)),
        {"chaves": list(PERFIS)},
    ).all()
    templates = {r[1] for r in rows if r[2] is None}
    if templates != set(PERFIS):
        raise RuntimeError(f"026 exige os templates {sorted(set(PERFIS) - templates)}; execute as migrations em ordem")
    return [r[0] for r in rows]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("026 suporta somente SQLite e PostgreSQL")
    row = bind.execute(sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"),
                       {"id": PERMISSAO["id"]}).mappings().first()
    if row is None:
        conflito = bind.execute(
            sa.text("SELECT id FROM permissoes WHERE chave = :chave OR (modulo = :modulo AND acao = :acao)"),
            {k: PERMISSAO[k] for k in ("chave", "modulo", "acao")}).first()
        if conflito is not None:
            raise RuntimeError(f"026 recusa catalogo preexistente de alertas:assumir (id {conflito[0]})")
        bind.execute(sa.text("INSERT INTO permissoes (id, modulo, acao, chave, descricao) "
                             "VALUES (:id, :modulo, :acao, :chave, :descricao)"), PERMISSAO)
    else:
        diferencas = {f: (row[f], PERMISSAO[f]) for f in CAMPOS if row[f] != PERMISSAO[f]}
        if diferencas:
            raise RuntimeError(f"026 permissao adulterada: {diferencas}")
    for perfil in _perfis(bind):
        existe = bind.execute(sa.text("SELECT 1 FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"),
                              {"p": perfil, "m": PERMISSAO["id"]}).first()
        if existe is None:
            bind.execute(sa.text("INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:p, :m)"),
                         {"p": perfil, "m": PERMISSAO["id"]})

    op.create_table(
        "alerta_estados",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("alerta_id", sa.String(255), nullable=False),
        sa.Column("regra", sa.String(64), nullable=False),
        sa.Column("referencia_id", sa.String(36)),
        sa.Column("residente_id", sa.String(36)),
        sa.Column("situacao", sa.String(20), nullable=False),
        sa.Column("assumido_por", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assumido_por_funcionario_id", sa.String(36)),
        sa.Column("assumido_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("em_atendimento_em", sa.DateTime(timezone=True)),
        sa.Column("encerrado_em", sa.DateTime(timezone=True)),
        sa.Column("encerrado_por", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("encerramento", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["residente_id", "ilpi_id"], ["residentes.id", "residentes.instituicao_id"],
                                name="fk_alerta_estados_residente", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assumido_por_funcionario_id", "ilpi_id"], ["funcionarios.id", "funcionarios.ilpi_id"],
                                name="fk_alerta_estados_funcionario", ondelete="RESTRICT"),
        sa.CheckConstraint("situacao IN ('assumido','em_atendimento','resolvido','liberado')", name="ck_alerta_estados_situacao"),
        sa.CheckConstraint(
            "(situacao IN ('assumido','em_atendimento') AND encerrado_em IS NULL AND encerramento IS NULL) OR "
            "(situacao = 'resolvido' AND encerramento = 'fonte' AND encerrado_em IS NOT NULL) OR "
            "(situacao = 'liberado' AND encerramento = 'liberado' AND encerrado_em IS NOT NULL)",
            name="ck_alerta_estados_encerramento"),
        sa.CheckConstraint("situacao != 'em_atendimento' OR em_atendimento_em IS NOT NULL", name="ck_alerta_estados_atendimento"),
    )
    op.create_index("uq_alerta_estados_aberto", "alerta_estados", ["ilpi_id", "alerta_id"], unique=True,
                    sqlite_where=sa.text("situacao IN ('assumido','em_atendimento')"),
                    postgresql_where=sa.text("situacao IN ('assumido','em_atendimento')"))
    op.create_index("ix_alerta_estados_ilpi_situacao", "alerta_estados", ["ilpi_id", "situacao"])
    op.create_index("ix_alerta_estados_ilpi_alerta", "alerta_estados", ["ilpi_id", "alerta_id", "assumido_em"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM alerta_estados LIMIT 1")).first() is not None:
        raise RuntimeError("026 recusa downgrade: alerta_estados tem historico de atendimento")
    permitidos = set(_perfis(bind))
    vinculos = {r[0] for r in bind.execute(sa.text("SELECT perfil_id FROM perfil_permissoes WHERE permissao_id = :m"),
                                           {"m": PERMISSAO["id"]}).all()}
    externos = sorted(vinculos - permitidos)
    if externos:
        raise RuntimeError(f"026 recusa downgrade: vinculos externos a alertas:assumir: {externos}")
    op.drop_table("alerta_estados")
    bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE permissao_id = :m"), {"m": PERMISSAO["id"]})
    bind.execute(sa.text("DELETE FROM permissoes WHERE id = :id"), {"id": PERMISSAO["id"]})

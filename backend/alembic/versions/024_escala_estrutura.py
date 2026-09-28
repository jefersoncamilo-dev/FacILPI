"""024_escala_estrutura: estrutura operacional da ILPI (#120).

Camada Operacional, Fase 2A (ROADMAP §16): areas operacionais (ala, setor,
unidade, grupo), vinculo area <-> leito com vigencia, turnos, plantao REAL e
responsabilidade operacional temporal. Nao e RH: sem folha, ponto ou banco de
horas. ``QuartoLeito.unidade`` segue texto livre do leito e nao vira area.

Responsabilidade NAO e permissao: nenhuma linha destas tabelas concede acesso.
Vigencias sao append-only (so ``fim_em`` e gravado, uma vez).

Permissoes novas (ids fixos, padrao 022):
- ``escala:ler`` e ``escala:gerenciar``: modulo operacional, nao clinico,
  ILPI-only (analogo a ``funcionarios``; o gestor pode repassar localmente);
- ``plantao:registrar``: iniciar e encerrar o proprio plantao.
Grants: ``ilpi_admin`` -> as tres; cuidador, enfermagem, responsavel_tecnico ->
``escala:ler`` + ``plantao:registrar``; medico -> ``escala:ler``. Templates e
clones locais, por chave. ``administrativo`` e ``platform_superuser`` nada.

Downgrade recusa se houver qualquer linha nas tabelas novas (historico
operacional nao some em silencio) ou vinculo das permissoes novas fora dos
perfis que esta migration alcanca.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "024_escala_estrutura"
down_revision: Union[str, None] = "023_alertas_operacionais"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSOES = (
    {"id": "fac11000-0000-4000-8000-000000000096", "chave": "escala:ler", "modulo": "escala", "acao": "ler",
     "descricao": "Ver areas operacionais, turnos, plantoes e quem responde por cada area na ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000097", "chave": "escala:gerenciar", "modulo": "escala", "acao": "gerenciar",
     "descricao": "Gerir areas operacionais, leitos das areas, turnos e responsabilidades da ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000098", "chave": "plantao:registrar", "modulo": "plantao", "acao": "registrar",
     "descricao": "Iniciar e encerrar o proprio plantao na ILPI atual."},
)
GRANTS = {
    "ilpi_admin": ("escala:ler", "escala:gerenciar", "plantao:registrar"),
    "cuidador": ("escala:ler", "plantao:registrar"),
    "enfermagem": ("escala:ler", "plantao:registrar"),
    "responsavel_tecnico": ("escala:ler", "plantao:registrar"),
    "medico": ("escala:ler",),
}
TABELAS = ("responsabilidades", "plantoes", "area_leitos", "turnos", "areas_operacionais")
CAMPOS = ("id", "modulo", "acao", "chave", "descricao")


def _preflight(bind):
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("024 suporta somente SQLite e PostgreSQL")


def _ensure_permissao(bind, registro):
    row = bind.execute(sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"),
                       {"id": registro["id"]}).mappings().first()
    if row is not None:
        diferencas = {f: (row[f], registro[f]) for f in CAMPOS if row[f] != registro[f]}
        if diferencas:
            raise RuntimeError(f"024 permissao adulterada: {diferencas}")
        return
    conflito = bind.execute(
        sa.text("SELECT id FROM permissoes WHERE chave = :chave OR (modulo = :modulo AND acao = :acao)"),
        {k: registro[k] for k in ("chave", "modulo", "acao")},
    ).first()
    if conflito is not None:
        raise RuntimeError(f"024 recusa catalogo preexistente para {registro['chave']} (id {conflito[0]})")
    bind.execute(sa.text("INSERT INTO permissoes (id, modulo, acao, chave, descricao) "
                         "VALUES (:id, :modulo, :acao, :chave, :descricao)"), registro)


def _perfis(bind, chave):
    rows = bind.execute(sa.text("SELECT id, ilpi_id FROM perfis WHERE chave = :c"), {"c": chave}).all()
    if not any(r[1] is None for r in rows):
        raise RuntimeError(f"024 exige o template {chave}; execute as migrations em ordem")
    return [r[0] for r in rows]


def _id_da_chave(chave):
    return next(p["id"] for p in PERMISSOES if p["chave"] == chave)


def _criar_tabelas():
    op.create_table(
        "areas_operacionais",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("nome", sa.String(100), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("descricao", sa.Text),
        sa.Column("situacao", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("id", "ilpi_id", name="uq_areas_operacionais_id_ilpi"),
        sa.UniqueConstraint("ilpi_id", "nome", name="uq_areas_operacionais_nome"),
        sa.CheckConstraint("tipo IN ('ala','setor','unidade','grupo')", name="ck_areas_operacionais_tipo"),
        sa.CheckConstraint("situacao IN ('ativa','inativa')", name="ck_areas_operacionais_situacao"),
    )
    op.create_index("ix_areas_operacionais_ilpi_id", "areas_operacionais", ["ilpi_id"])
    op.create_table(
        "area_leitos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("area_id", sa.String(36), nullable=False),
        sa.Column("quarto_leito_id", sa.String(36), nullable=False),
        sa.Column("inicio_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fim_em", sa.DateTime(timezone=True)),
        sa.Column("criado_por", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("encerrado_por", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["area_id", "ilpi_id"], ["areas_operacionais.id", "areas_operacionais.ilpi_id"],
                                name="fk_area_leitos_area", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["quarto_leito_id", "ilpi_id"], ["quartos_leitos.id", "quartos_leitos.instituicao_id"],
                                name="fk_area_leitos_leito", ondelete="RESTRICT"),
        sa.CheckConstraint("fim_em IS NULL OR fim_em >= inicio_em", name="ck_area_leitos_vigencia"),
    )
    op.create_index("uq_area_leitos_leito_ativo", "area_leitos", ["quarto_leito_id"], unique=True,
                    sqlite_where=sa.text("fim_em IS NULL"), postgresql_where=sa.text("fim_em IS NULL"))
    op.create_index("ix_area_leitos_ilpi_area", "area_leitos", ["ilpi_id", "area_id"])
    op.create_table(
        "turnos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("nome", sa.String(60), nullable=False),
        sa.Column("hora_inicio", sa.String(5), nullable=False),
        sa.Column("hora_fim", sa.String(5), nullable=False),
        sa.Column("situacao", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("id", "ilpi_id", name="uq_turnos_id_ilpi"),
        sa.UniqueConstraint("ilpi_id", "nome", name="uq_turnos_nome"),
        sa.CheckConstraint("situacao IN ('ativo','inativo')", name="ck_turnos_situacao"),
        sa.CheckConstraint("hora_inicio != hora_fim", name="ck_turnos_horas"),
    )
    op.create_index("ix_turnos_ilpi_id", "turnos", ["ilpi_id"])
    op.create_table(
        "plantoes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("funcionario_id", sa.String(36), nullable=False),
        sa.Column("turno_id", sa.String(36)),
        sa.Column("inicio_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fim_em", sa.DateTime(timezone=True)),
        sa.Column("situacao", sa.String(20), nullable=False),
        sa.Column("iniciado_por", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("encerrado_por", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("id", "ilpi_id", name="uq_plantoes_id_ilpi"),
        sa.ForeignKeyConstraint(["funcionario_id", "ilpi_id"], ["funcionarios.id", "funcionarios.ilpi_id"],
                                name="fk_plantoes_funcionario", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["turno_id", "ilpi_id"], ["turnos.id", "turnos.ilpi_id"],
                                name="fk_plantoes_turno", ondelete="RESTRICT"),
        sa.CheckConstraint("situacao IN ('em_andamento','encerrado')", name="ck_plantoes_situacao"),
        sa.CheckConstraint("(situacao = 'em_andamento' AND fim_em IS NULL) OR "
                           "(situacao = 'encerrado' AND fim_em IS NOT NULL AND fim_em >= inicio_em)",
                           name="ck_plantoes_vigencia"),
    )
    op.create_index("uq_plantoes_funcionario_ativo", "plantoes", ["ilpi_id", "funcionario_id"], unique=True,
                    sqlite_where=sa.text("situacao = 'em_andamento'"), postgresql_where=sa.text("situacao = 'em_andamento'"))
    op.create_index("ix_plantoes_ilpi_inicio", "plantoes", ["ilpi_id", "inicio_em"])
    op.create_table(
        "responsabilidades",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("plantao_id", sa.String(36), nullable=False),
        sa.Column("funcionario_id", sa.String(36), nullable=False),
        sa.Column("area_id", sa.String(36), nullable=False),
        sa.Column("inicio_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fim_em", sa.DateTime(timezone=True)),
        sa.Column("motivo_fim", sa.String(20)),
        sa.Column("criado_por", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("encerrado_por", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["plantao_id", "ilpi_id"], ["plantoes.id", "plantoes.ilpi_id"],
                                name="fk_responsabilidades_plantao", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["funcionario_id", "ilpi_id"], ["funcionarios.id", "funcionarios.ilpi_id"],
                                name="fk_responsabilidades_funcionario", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["area_id", "ilpi_id"], ["areas_operacionais.id", "areas_operacionais.ilpi_id"],
                                name="fk_responsabilidades_area", ondelete="RESTRICT"),
        sa.CheckConstraint("motivo_fim IS NULL OR motivo_fim IN ('fim_plantao','transferencia','ajuste')",
                           name="ck_responsabilidades_motivo"),
        sa.CheckConstraint("(fim_em IS NULL AND motivo_fim IS NULL) OR "
                           "(fim_em IS NOT NULL AND motivo_fim IS NOT NULL AND fim_em >= inicio_em)",
                           name="ck_responsabilidades_vigencia"),
    )
    op.create_index("uq_responsabilidades_aberta", "responsabilidades", ["area_id", "funcionario_id"], unique=True,
                    sqlite_where=sa.text("fim_em IS NULL"), postgresql_where=sa.text("fim_em IS NULL"))
    op.create_index("ix_responsabilidades_ilpi_area_inicio", "responsabilidades", ["ilpi_id", "area_id", "inicio_em"])
    op.create_index("ix_responsabilidades_plantao", "responsabilidades", ["plantao_id"])


def upgrade() -> None:
    bind = op.get_bind()
    _preflight(bind)
    for registro in PERMISSOES:
        _ensure_permissao(bind, registro)
    for chave_perfil, chaves in GRANTS.items():
        for perfil in _perfis(bind, chave_perfil):
            for chave in chaves:
                permissao = _id_da_chave(chave)
                existe = bind.execute(sa.text("SELECT 1 FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"),
                                      {"p": perfil, "m": permissao}).first()
                if existe is None:
                    bind.execute(sa.text("INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:p, :m)"),
                                 {"p": perfil, "m": permissao})
    _criar_tabelas()


def downgrade() -> None:
    bind = op.get_bind()
    _preflight(bind)
    for tabela in TABELAS:
        if bind.execute(sa.text(f"SELECT 1 FROM {tabela} LIMIT 1")).first() is not None:
            raise RuntimeError(f"024 recusa downgrade: {tabela} tem historico operacional")
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
            raise RuntimeError(f"024 recusa downgrade: vinculos externos a {permissao}: {externos}")
    for tabela in TABELAS:
        op.drop_table(tabela)
    for registro in PERMISSOES:
        bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE permissao_id = :m"), {"m": registro["id"]})
        bind.execute(sa.text("DELETE FROM permissoes WHERE id = :id"), {"id": registro["id"]})

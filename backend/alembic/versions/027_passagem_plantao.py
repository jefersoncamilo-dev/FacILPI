"""027_passagem_plantao: passagem de plantao persistida (#125).

Camada Operacional, Fase 4. A passagem e o REGISTRO do que foi comunicado na
troca de turno — nao e fonte de fatos clinicos. A parte automatica e montada
pelo servidor a partir das fontes reais (alertas/pendencias, intercorrencias
abertas, atividades nao concluidas, ausencias); a parte manual sao observacoes
curtas e categorizadas (ate 280 caracteres), sem virar prontuario paralelo.
Cada item guarda o que foi dito (titulo) e aponta para a origem; quem recebe
ve a situacao ATUAL da fonte.

Permissoes (modulo clinico ``passagem_plantao``, ja listado nas duas listas):
``passagem_plantao:ler`` (ilpi_admin, cuidador, enfermagem, medico,
responsavel_tecnico) e ``passagem_plantao:registrar`` (ilpi_admin, cuidador,
enfermagem, responsavel_tecnico). Templates e clones por chave.
Downgrade recusa historico de passagens e vinculos externos.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "027_passagem_plantao"
down_revision: Union[str, None] = "026_alerta_estados"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSOES = (
    {"id": "fac11000-0000-4000-8000-000000000100", "chave": "passagem_plantao:ler", "modulo": "passagem_plantao",
     "acao": "ler", "descricao": "Ver passagens de plantao da ILPI atual (itens filtrados pela leitura de origem)."},
    {"id": "fac11000-0000-4000-8000-000000000101", "chave": "passagem_plantao:registrar", "modulo": "passagem_plantao",
     "acao": "registrar", "descricao": "Entregar e receber passagens de plantao na ILPI atual."},
)
GRANTS = {
    "ilpi_admin": ("passagem_plantao:ler", "passagem_plantao:registrar"),
    "cuidador": ("passagem_plantao:ler", "passagem_plantao:registrar"),
    "enfermagem": ("passagem_plantao:ler", "passagem_plantao:registrar"),
    "responsavel_tecnico": ("passagem_plantao:ler", "passagem_plantao:registrar"),
    "medico": ("passagem_plantao:ler",),
}
CAMPOS = ("id", "modulo", "acao", "chave", "descricao")
CATEGORIAS = "'assistencial','comportamento','familia_visitas','estrutura_materiais','outro'"


def _id_da_chave(chave):
    return next(p["id"] for p in PERMISSOES if p["chave"] == chave)


def _perfis(bind, chave):
    rows = bind.execute(sa.text("SELECT id, ilpi_id FROM perfis WHERE chave = :c"), {"c": chave}).all()
    if not any(r[1] is None for r in rows):
        raise RuntimeError(f"027 exige o template {chave}; execute as migrations em ordem")
    return [r[0] for r in rows]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("027 suporta somente SQLite e PostgreSQL")
    for registro in PERMISSOES:
        row = bind.execute(sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"),
                           {"id": registro["id"]}).mappings().first()
        if row is None:
            conflito = bind.execute(
                sa.text("SELECT id FROM permissoes WHERE chave = :chave OR (modulo = :modulo AND acao = :acao)"),
                {k: registro[k] for k in ("chave", "modulo", "acao")}).first()
            if conflito is not None:
                raise RuntimeError(f"027 recusa catalogo preexistente para {registro['chave']} (id {conflito[0]})")
            bind.execute(sa.text("INSERT INTO permissoes (id, modulo, acao, chave, descricao) "
                                 "VALUES (:id, :modulo, :acao, :chave, :descricao)"), registro)
        else:
            diferencas = {f: (row[f], registro[f]) for f in CAMPOS if row[f] != registro[f]}
            if diferencas:
                raise RuntimeError(f"027 permissao adulterada: {diferencas}")
    for chave_perfil, chaves in GRANTS.items():
        for perfil in _perfis(bind, chave_perfil):
            for chave in chaves:
                permissao = _id_da_chave(chave)
                if bind.execute(sa.text("SELECT 1 FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"),
                                {"p": perfil, "m": permissao}).first() is None:
                    bind.execute(sa.text("INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:p, :m)"),
                                 {"p": perfil, "m": permissao})

    op.create_table(
        "passagens_plantao",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("plantao_id", sa.String(36)),
        sa.Column("area_id", sa.String(36)),
        sa.Column("janela_inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("janela_fim", sa.DateTime(timezone=True), nullable=False),
        sa.Column("situacao", sa.String(20), nullable=False),
        sa.Column("entregue_por", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("entregue_por_funcionario_id", sa.String(36)),
        sa.Column("entregue_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recebida_por", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("recebida_por_funcionario_id", sa.String(36)),
        sa.Column("recebida_em", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("id", "ilpi_id", name="uq_passagens_plantao_id_ilpi"),
        sa.ForeignKeyConstraint(["plantao_id", "ilpi_id"], ["plantoes.id", "plantoes.ilpi_id"],
                                name="fk_passagens_plantao", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["area_id", "ilpi_id"], ["areas_operacionais.id", "areas_operacionais.ilpi_id"],
                                name="fk_passagens_area", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["entregue_por_funcionario_id", "ilpi_id"], ["funcionarios.id", "funcionarios.ilpi_id"],
                                name="fk_passagens_entregue_funcionario", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recebida_por_funcionario_id", "ilpi_id"], ["funcionarios.id", "funcionarios.ilpi_id"],
                                name="fk_passagens_recebida_funcionario", ondelete="RESTRICT"),
        sa.CheckConstraint("situacao IN ('entregue','recebida')", name="ck_passagens_situacao"),
        sa.CheckConstraint("(situacao = 'entregue' AND recebida_em IS NULL AND recebida_por IS NULL) OR "
                           "(situacao = 'recebida' AND recebida_em IS NOT NULL AND recebida_por IS NOT NULL)",
                           name="ck_passagens_recebimento"),
        sa.CheckConstraint("janela_fim >= janela_inicio", name="ck_passagens_janela"),
    )
    op.create_index("ix_passagens_ilpi_situacao", "passagens_plantao", ["ilpi_id", "situacao", "entregue_em"])
    op.create_table(
        "passagem_itens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("passagem_id", sa.String(36), nullable=False),
        sa.Column("ordem", sa.Integer, nullable=False),
        sa.Column("origem", sa.String(20), nullable=False),
        sa.Column("alerta_id", sa.String(255)),
        sa.Column("regra", sa.String(64)),
        sa.Column("referencia_id", sa.String(36)),
        sa.Column("residente_id", sa.String(36)),
        sa.Column("gravidade", sa.String(20)),
        sa.Column("natureza", sa.String(20)),
        sa.Column("titulo", sa.String(255), nullable=False),
        sa.Column("previsto_em", sa.DateTime(timezone=True)),
        sa.Column("categoria", sa.String(30)),
        sa.Column("texto", sa.String(280)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["passagem_id", "ilpi_id"], ["passagens_plantao.id", "passagens_plantao.ilpi_id"],
                                name="fk_passagem_itens_passagem", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["residente_id", "ilpi_id"], ["residentes.id", "residentes.instituicao_id"],
                                name="fk_passagem_itens_residente", ondelete="RESTRICT"),
        sa.CheckConstraint("origem IN ('alerta','intercorrencia','atividade','ausencia','observacao')", name="ck_passagem_itens_origem"),
        sa.CheckConstraint(f"categoria IS NULL OR categoria IN ({CATEGORIAS})", name="ck_passagem_itens_categoria"),
        sa.CheckConstraint("origem != 'observacao' OR (categoria IS NOT NULL AND texto IS NOT NULL AND length(trim(texto)) > 0)",
                           name="ck_passagem_itens_observacao"),
    )
    op.create_index("ix_passagem_itens_passagem", "passagem_itens", ["passagem_id", "ordem"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM passagens_plantao LIMIT 1")).first() is not None:
        raise RuntimeError("027 recusa downgrade: passagens_plantao tem historico de passagens")
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
            raise RuntimeError(f"027 recusa downgrade: vinculos externos a {permissao}: {externos}")
    op.drop_table("passagem_itens")
    op.drop_table("passagens_plantao")
    for registro in PERMISSOES:
        bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE permissao_id = :m"), {"m": registro["id"]})
        bind.execute(sa.text("DELETE FROM permissoes WHERE id = :id"), {"id": registro["id"]})

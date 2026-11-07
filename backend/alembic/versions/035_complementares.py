"""035 — complementares D5: agenda, multidisciplinar, PIA, estoque e mensalidades.

Tabelas novas e catalogo proprio. Historico: atendimento multidisciplinar so
estorna, PIA so ganha versao, movimento de estoque e append-only, mensalidade e
agendamento cancelam sem apagar. Profissao nao concede: areas sem template ficam
para atribuicao por perfil. Downgrade recusa vinculos externos.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "035_complementares"
down_revision: Union[str, None] = "034_transicao_admin_clinico"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AREAS = ("fisioterapia", "nutricao", "psicologia", "servico_social", "enfermagem")
_CHAVES = [
    ("agenda", "ler"), ("agenda", "gerenciar"),
    *[(f"multidisciplinar.{a}", acao) for a in AREAS for acao in ("ler", "registrar")],
    ("pia", "ler"), ("pia", "registrar"),
    ("estoque", "ler"), ("estoque", "movimentar"),
    ("financeiro", "ler"), ("financeiro", "gerenciar"),
]
PERMISSOES = [
    {"id": f"fac35000-0000-4000-8000-{n:012d}", "modulo": mod.split(".")[0], "acao": f"{mod.split('.')[-1]}_{acao}" if "." in mod else acao,
     "chave": f"{mod}:{acao}", "descricao": f"{acao.capitalize()} em {mod} na ILPI atual."}
    for n, (mod, acao) in enumerate(_CHAVES, start=1)
]
_LER_AREAS = tuple(f"multidisciplinar.{a}:ler" for a in AREAS)
GRANTS = {
    "ilpi_admin": ("agenda:ler", "agenda:gerenciar", "pia:ler", "estoque:ler", "financeiro:ler", "financeiro:gerenciar"),
    "cuidador": ("agenda:ler", "pia:ler"),
    "enfermagem": ("agenda:ler", "agenda:gerenciar", "pia:ler", "pia:registrar", "estoque:ler", "estoque:movimentar",
                   "multidisciplinar.enfermagem:ler", "multidisciplinar.enfermagem:registrar"),
    "medico": ("agenda:ler", "agenda:gerenciar", "pia:ler"),
    "responsavel_tecnico": ("agenda:ler", "agenda:gerenciar", "pia:ler", "pia:registrar", "estoque:ler", "estoque:movimentar",
                            *_LER_AREAS),
}
# Templates novos: atribuidos so por perfil; profissao continua nao concedendo.
PERFIS_NOVOS = {
    "fisioterapeuta": ("Fisioterapeuta", "fisioterapia", 1),
    "nutricionista": ("Nutricionista", "nutricao", 2),
    "psicologo": ("Psicólogo(a)", "psicologia", 3),
    "assistente_social": ("Assistente Social", "servico_social", 4),
}
_COMUNS = ("agenda:ler", "pia:ler", "pia:registrar", "residentes:ler")


def _base():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id", ondelete="RESTRICT"), nullable=False, index=True),
    ]


def _residente_fk(nome):
    return sa.ForeignKeyConstraint(["residente_id", "ilpi_id"], ["residentes.id", "residentes.instituicao_id"], name=nome, ondelete="RESTRICT")


def _autor():
    return sa.Column("autor_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


def _criado():
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("035 suporta somente SQLite e PostgreSQL")
    op.create_table(
        "agenda_eventos", *_base(),
        sa.Column("residente_id", sa.String(36), nullable=False),
        sa.Column("motivo", sa.String(255), nullable=False),
        sa.Column("especialidade", sa.String(100)),
        sa.Column("profissional", sa.String(255)),
        sa.Column("local", sa.String(255)),
        sa.Column("inicio_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("situacao", sa.String(20), nullable=False, server_default="agendado"),
        sa.Column("resultado", sa.Text()),
        sa.Column("motivo_cancelamento", sa.Text()),
        _autor(), _criado(),
        _residente_fk("fk_agenda_residente"),
        sa.CheckConstraint("situacao IN ('agendado','realizado','cancelado')", name="ck_agenda_situacao"),
    )
    op.create_table(
        "atendimentos_multidisciplinares", *_base(),
        sa.Column("residente_id", sa.String(36), nullable=False),
        sa.Column("area", sa.String(30), nullable=False),
        sa.Column("ocorrido_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evolucao", sa.Text(), nullable=False),
        _autor(),
        sa.Column("autor_nome", sa.String(255), nullable=False),
        sa.Column("estornado_em", sa.DateTime(timezone=True)),
        sa.Column("estornado_por", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("motivo_estorno", sa.Text()),
        _criado(),
        _residente_fk("fk_atendimento_residente"),
        sa.CheckConstraint("area IN ('fisioterapia','nutricao','psicologia','servico_social','enfermagem')", name="ck_atendimento_area"),
    )
    op.create_table(
        "pia_versoes", *_base(),
        sa.Column("residente_id", sa.String(36), nullable=False),
        sa.Column("versao", sa.Integer(), nullable=False),
        *[sa.Column(c, sa.Text()) for c in ("informacoes_gerais", "institucionalizacao", "habitos_interesses",
                                            "apoio_social", "financas", "historico_saude", "planejamento_individual")],
        _autor(),
        sa.Column("autor_nome", sa.String(255), nullable=False),
        _criado(),
        _residente_fk("fk_pia_residente"),
        sa.UniqueConstraint("residente_id", "versao", name="uq_pia_residente_versao"),
    )
    op.create_table(
        "estoque_itens", *_base(),
        sa.Column("nome", sa.String(255), nullable=False),
        sa.Column("categoria", sa.String(100)),
        sa.Column("unidade", sa.String(50), nullable=False),
        sa.Column("estoque_minimo", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("localizacao", sa.String(255)),
        _autor(), _criado(),
        sa.UniqueConstraint("id", "ilpi_id", name="uq_estoque_itens_id_ilpi"),
        sa.UniqueConstraint("ilpi_id", "nome", name="uq_estoque_itens_nome"),
    )
    op.create_table(
        "estoque_movimentos", *_base(),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("quantidade", sa.Integer(), nullable=False),
        sa.Column("lote", sa.String(50)),
        sa.Column("validade", sa.Date()),
        sa.Column("residente_id", sa.String(36)),
        sa.Column("motivo", sa.Text()),
        _autor(), _criado(),
        sa.ForeignKeyConstraint(["item_id", "ilpi_id"], ["estoque_itens.id", "estoque_itens.ilpi_id"], name="fk_movimento_item", ondelete="RESTRICT"),
        _residente_fk("fk_movimento_residente"),
        sa.CheckConstraint("tipo IN ('entrada','saida')", name="ck_movimento_tipo"),
        sa.CheckConstraint("quantidade > 0", name="ck_movimento_quantidade"),
    )
    op.create_table(
        "mensalidades", *_base(),
        sa.Column("residente_id", sa.String(36), nullable=False),
        sa.Column("competencia", sa.String(7), nullable=False),
        sa.Column("valor_centavos", sa.Integer(), nullable=False),
        sa.Column("vencimento", sa.Date(), nullable=False),
        sa.Column("situacao", sa.String(20), nullable=False, server_default="aberta"),
        sa.Column("pago_em", sa.Date()),
        sa.Column("observacao", sa.Text()),
        _autor(), _criado(),
        _residente_fk("fk_mensalidade_residente"),
        sa.CheckConstraint("situacao IN ('aberta','paga','cancelada')", name="ck_mensalidade_situacao"),
        sa.CheckConstraint("valor_centavos > 0", name="ck_mensalidade_valor"),
    )
    op.create_index("uq_mensalidade_vigente", "mensalidades", ["residente_id", "competencia"], unique=True,
                    sqlite_where=sa.text("situacao <> 'cancelada'"), postgresql_where=sa.text("situacao <> 'cancelada'"))

    for p in PERMISSOES:
        bind.execute(sa.text("INSERT INTO permissoes (id, modulo, acao, chave, descricao) VALUES (:id, :modulo, :acao, :chave, :descricao)"), p)
    ids = {p["chave"]: p["id"] for p in PERMISSOES}
    for chave, (nome, area, n) in PERFIS_NOVOS.items():
        perfil = f"fac35100-0000-4000-8000-{n:012d}"
        bind.execute(sa.text("INSERT INTO perfis (id, ilpi_id, nome, chave, descricao, escopo, situacao) "
                             "VALUES (:id, NULL, :nome, :chave, :d, 'ilpi', 'ativo')"),
                     {"id": perfil, "nome": nome, "chave": chave, "d": f"Atendimentos de {area}, agenda e PIA."})
        for permissao in (*_COMUNS, f"multidisciplinar.{area}:ler", f"multidisciplinar.{area}:registrar"):
            bind.execute(sa.text("INSERT INTO perfil_permissoes (perfil_id, permissao_id) "
                                 "SELECT :p, id FROM permissoes WHERE chave = :c"), {"p": perfil, "c": permissao})
    for perfil_chave, chaves in GRANTS.items():
        for (perfil,) in bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c"), {"c": perfil_chave}).all():
            for chave in chaves:
                bind.execute(sa.text("INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:p, :m)"), {"p": perfil, "m": ids[chave]})


def downgrade() -> None:
    bind = op.get_bind()
    for chave in PERFIS_NOVOS:
        ids_perfil = bind.execute(sa.text("SELECT id, ilpi_id FROM perfis WHERE chave = :c"), {"c": chave}).all()
        if any(r[1] is not None for r in ids_perfil):
            raise RuntimeError(f"035 recusa downgrade: clone em uso do perfil {chave}")
        for r in ids_perfil:
            if bind.execute(sa.text("SELECT 1 FROM usuario_ilpi_perfis WHERE perfil_id = :p"), {"p": r[0]}).first():
                raise RuntimeError(f"035 recusa downgrade: perfil {chave} atribuido")
            bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE perfil_id = :p"), {"p": r[0]})
            bind.execute(sa.text("DELETE FROM perfis WHERE id = :p"), {"p": r[0]})
    for p in PERMISSOES:
        permitidos = [k for k, v in GRANTS.items() if p["chave"] in v]
        externos = bind.execute(sa.text(
            "SELECT pf.chave FROM perfil_permissoes pp JOIN perfis pf ON pf.id = pp.perfil_id WHERE pp.permissao_id = :m"),
            {"m": p["id"]}).scalars().all()
        fora = sorted(set(externos) - set(permitidos))
        if fora:
            raise RuntimeError(f"035 recusa downgrade: vinculos externos a {p['chave']}: {fora}")
        bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE permissao_id = :m"), {"m": p["id"]})
        bind.execute(sa.text("DELETE FROM permissoes WHERE id = :m"), {"m": p["id"]})
    op.drop_index("uq_mensalidade_vigente", table_name="mensalidades")
    for tabela in ("mensalidades", "estoque_movimentos", "estoque_itens", "pia_versoes",
                   "atendimentos_multidisciplinares", "agenda_eventos"):
        op.drop_table(tabela)

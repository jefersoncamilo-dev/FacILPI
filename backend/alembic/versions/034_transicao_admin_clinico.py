"""034 — retirar as escritas clinicas do ilpi_admin, com transicao (#15, D3 = opcao B).

D3 (29/10/2026): o template ``ilpi_admin`` (e seus clones, casados por chave)
deixa de ter as escritas clinicas listadas em ``ESCRITAS_CLINICAS``. Leituras,
Dashboard, Alertas e a gestao institucional (usuarios, perfis, residentes,
documentos, escala, passagem) continuam. Nada de historico clinico e apagado:
so vinculos perfil-permissao saem.

Transicao de 30 dias, contada POR ILPI: cada ILPI existente no momento desta
migration ganha uma linha em ``transicao_admin_clinico`` com
``prazo = momento do upgrade + 30 dias``. Ate o prazo, a sessao do ilpi_admin
daquela ILPI ainda pode as escritas clinicas (carencia em
``security.py``); depois, perde so elas. ILPI criada depois desta migration nao
tem linha e ja nasce sem as escritas no administrador. O responsavel pode
ajustar o prazo de uma ILPI com UPDATE nessa tabela (registrar a decisao).

Os vinculos removidos ficam em ``transicao_admin_clinico_vinculos``; o downgrade
devolve exatamente esses (um clone que nao tinha a escrita nao a ganha) e
remove as duas tabelas.
"""

from datetime import datetime, timedelta, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "034_transicao_admin_clinico"
down_revision: Union[str, None] = "033_estorno_dose"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATE_KEY = "ilpi_admin"
PRAZO_DIAS = 30
# Fonte unica: security.ESCRITAS_CLINICAS_ADMIN repete esta lista (congelada aqui).
ESCRITAS_CLINICAS = (
    "avaliacoes:criar", "avaliacoes:atualizar",
    "grau_dependencia:criar",
    "sinais_vitais:criar",
    "intercorrencias:criar", "intercorrencias:atualizar",
    "planos_cuidados:criar", "planos_cuidados:atualizar", "planos_cuidados:revisar",
    "planos_cuidados:aprovar", "planos_cuidados:encerrar",
    "programacoes:criar", "programacoes:atualizar", "programacoes:inativar",
    "ocorrencias:cancelar",
    "execucoes:criar", "execucoes:corrigir",
)


def _perfis_admin(bind):
    rows = bind.execute(sa.text("SELECT id, ilpi_id FROM perfis WHERE chave = :c"), {"c": TEMPLATE_KEY}).all()
    if not any(r[1] is None for r in rows):
        raise RuntimeError("034 exige o template ilpi_admin; execute as migrations em ordem")
    return [r[0] for r in rows]


def _permissoes(bind):
    ids = {}
    for chave in ESCRITAS_CLINICAS:
        row = bind.execute(sa.text("SELECT id FROM permissoes WHERE chave = :c"), {"c": chave}).first()
        if row is None:
            raise RuntimeError(f"034 exige a permissao {chave}; execute as migrations em ordem")
        ids[chave] = row[0]
    return ids


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("034 suporta somente SQLite e PostgreSQL")
    permissoes = _permissoes(bind)
    perfis = _perfis_admin(bind)

    op.create_table(
        "transicao_admin_clinico",
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("prazo", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    prazo = datetime.now(timezone.utc) + timedelta(days=PRAZO_DIAS)
    for (ilpi_id,) in bind.execute(sa.text("SELECT id FROM instituicoes")).all():
        bind.execute(sa.text("INSERT INTO transicao_admin_clinico (ilpi_id, prazo) VALUES (:i, :p)"),
                     {"i": ilpi_id, "p": prazo})

    op.create_table(
        "transicao_admin_clinico_vinculos",
        sa.Column("perfil_id", sa.String(36), primary_key=True),
        sa.Column("permissao_id", sa.String(36), primary_key=True),
    )
    for perfil in perfis:
        for permissao in permissoes.values():
            if bind.execute(sa.text("SELECT 1 FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"),
                            {"p": perfil, "m": permissao}).first() is None:
                continue
            bind.execute(sa.text("INSERT INTO transicao_admin_clinico_vinculos (perfil_id, permissao_id) "
                                 "VALUES (:p, :m)"), {"p": perfil, "m": permissao})
            bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"),
                         {"p": perfil, "m": permissao})


def downgrade() -> None:
    bind = op.get_bind()
    removidos = bind.execute(sa.text(
        "SELECT v.perfil_id, v.permissao_id FROM transicao_admin_clinico_vinculos v "
        "JOIN perfis p ON p.id = v.perfil_id")).all()
    for perfil, permissao in removidos:
        if bind.execute(sa.text("SELECT 1 FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"),
                        {"p": perfil, "m": permissao}).first() is None:
            bind.execute(sa.text("INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:p, :m)"),
                         {"p": perfil, "m": permissao})
    op.drop_table("transicao_admin_clinico_vinculos")
    op.drop_table("transicao_admin_clinico")

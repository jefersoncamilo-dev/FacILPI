"""Autoria por usuario em avaliacoes, sinais vitais e intercorrencias.

Ate aqui a autoria desses tres registros era so o NOME de quem registrou
(``profissional`` / ``responsavel``), derivado da sessao mas sem vinculo com o
usuario. Esta migration acrescenta ``autor_id`` (FK ``users.id``, RESTRICT),
sem tocar no texto: ele continua como foto do nome no momento do registro.

Preenchimento dos registros existentes, so a partir da AUDITORIA de criacao
(nunca pelo nome, que pode ter homonimos):
- casamento direto: ``auditoria.registro_id = registro.id`` com a acao de
  criacao do modulo e a mesma ILPI;
- avaliacoes: a auditoria de criacao gravava ``registro_id`` NULO (o id era lido
  antes do flush; corrigido no #157). Para elas, casa por ILPI + residente +
  tipo SOMENTE quando ha exatamente uma avaliacao e uma auditoria para o trio.
O que nao casa sem ambiguidade fica sem autor.

Nenhum dado e apagado ou reescrito alem de preencher a coluna nova.
SQLite: ``ADD COLUMN ... REFERENCES`` (sem recriar tabela). PostgreSQL:
constraint nomeada. Downgrade remove indice, FK e coluna.

Revision ID: 029_autoria_autor_id
Revises: 028_alerta_expirado
"""

import json
from collections import defaultdict
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "029_autoria_autor_id"
down_revision: Union[str, None] = "028_alerta_expirado"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABELAS = {
    "avaliacoes": "avaliacoes.criar",
    "sinais_vitais": "sinais_vitais.criar",
    "intercorrencias": "intercorrencias.criar",
}


def _preflight(bind):
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("029 suporta somente SQLite e PostgreSQL")


def _adicionar_coluna(bind, tabela: str) -> None:
    if bind.dialect.name == "sqlite":
        op.execute(sa.text(
            f"ALTER TABLE {tabela} ADD COLUMN autor_id VARCHAR(36) REFERENCES users (id) ON DELETE RESTRICT"))
    else:
        op.add_column(tabela, sa.Column("autor_id", sa.String(36), nullable=True))
        op.create_foreign_key(f"fk_{tabela}_autor", tabela, "users", ["autor_id"], ["id"], ondelete="RESTRICT")
    op.create_index(f"ix_{tabela}_autor_id", tabela, ["autor_id"])


def _preencher_direto(bind, tabela: str, acao: str) -> None:
    linhas = bind.execute(sa.text(
        f"SELECT t.id, a.usuario_id FROM {tabela} t JOIN auditoria a "
        "ON a.registro_id = t.id AND a.acao = :acao AND a.ilpi_id = t.ilpi_id "
        "AND a.usuario_id IS NOT NULL WHERE t.autor_id IS NULL"), {"acao": acao}).all()
    # Mais de uma auditoria de criacao com usuarios diferentes: nao se escolhe um.
    por_registro: dict[str, set[str]] = defaultdict(set)
    for registro_id, usuario_id in linhas:
        por_registro[registro_id].add(usuario_id)
    for registro_id, usuarios in por_registro.items():
        if len(usuarios) == 1:
            bind.execute(sa.text(f"UPDATE {tabela} SET autor_id = :u WHERE id = :id AND autor_id IS NULL"),
                         {"u": next(iter(usuarios)), "id": registro_id})


def _preencher_avaliacoes_pelo_trio(bind) -> None:
    auditorias: dict[tuple, list[str]] = defaultdict(list)
    for ilpi_id, usuario_id, valores in bind.execute(sa.text(
            "SELECT ilpi_id, usuario_id, valores_posteriores FROM auditoria "
            "WHERE acao = 'avaliacoes.criar' AND registro_id IS NULL AND usuario_id IS NOT NULL")).all():
        try:
            dados = json.loads(valores or "{}")
        except ValueError:
            continue
        auditorias[(ilpi_id, dados.get("residente_id"), dados.get("tipo"))].append(usuario_id)
    avaliacoes: dict[tuple, list[str]] = defaultdict(list)
    for id_, ilpi_id, residente_id, tipo, autor_id in bind.execute(sa.text(
            "SELECT id, ilpi_id, residente_id, tipo, autor_id FROM avaliacoes")).all():
        avaliacoes[(ilpi_id, residente_id, tipo)].append((id_, autor_id))
    for trio, registros in avaliacoes.items():
        usuarios = auditorias.get(trio, [])
        if len(registros) == 1 and len(usuarios) == 1 and registros[0][1] is None:
            bind.execute(sa.text("UPDATE avaliacoes SET autor_id = :u WHERE id = :id AND autor_id IS NULL"),
                         {"u": usuarios[0], "id": registros[0][0]})


def upgrade() -> None:
    bind = op.get_bind()
    _preflight(bind)
    for tabela in TABELAS:
        _adicionar_coluna(bind, tabela)
    for tabela, acao in TABELAS.items():
        _preencher_direto(bind, tabela, acao)
    _preencher_avaliacoes_pelo_trio(bind)


def downgrade() -> None:
    bind = op.get_bind()
    _preflight(bind)
    for tabela in TABELAS:
        op.drop_index(f"ix_{tabela}_autor_id", table_name=tabela)
        if bind.dialect.name == "sqlite":
            op.execute(sa.text(f"ALTER TABLE {tabela} DROP COLUMN autor_id"))
        else:
            op.drop_constraint(f"fk_{tabela}_autor", tabela, type_="foreignkey")
            op.drop_column(tabela, "autor_id")

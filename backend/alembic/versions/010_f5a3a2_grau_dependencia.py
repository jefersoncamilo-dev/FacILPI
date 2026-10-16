"""010_f5a3a2_grau_dependencia: Grau de Dependência — fonte única + histórico.

Creates the graus_dependencia table (sole official source: append-only
history ativo/substituido/revogado, at most ONE ativo per residente via
partial unique index), adds 2 RBAC permissions
(grau_dependencia:ler/criar) granted to the ilpi_admin template and
clones, and backfills exact-match legacy Residente.grau_dependencia
values as origem='migracao' rows.

Platform superuser receives zero Grau grants. Residente.grau_dependencia
is NOT touched: it stays as a frozen legacy column (no writes, no sync,
no trigger). Historical migrations 001-009 are not modified.
"""

import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010_f5a3a2_grau_dependencia"
down_revision: Union[str, None] = "009_f5a3a1_avaliacoes_rbac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATE_KEY = "ilpi_admin"

NEW_PERMISSIONS = (
    {"id": "fac11000-0000-4000-8000-000000000055", "chave": "grau_dependencia:ler", "modulo": "grau_dependencia", "acao": "ler", "descricao": "Consultar graus de dependência e histórico da ILPI atual.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000056", "chave": "grau_dependencia:criar", "modulo": "grau_dependencia", "acao": "criar", "descricao": "Confirmar, substituir ou revogar grau de dependência na ILPI atual.", "escopo_permitido": "ilpi"},
)

PERMISSION_FIELDS = ("id", "modulo", "acao", "chave", "descricao")

GRAU_LEGADO_VALIDO = ("Grau I", "Grau II", "Grau III")

BACKFILL_JUSTIFICATIVA = "Migração legado F5A-3A2: valor herdado de Residente.grau_dependencia sem autoria histórica confiável."


def _assert_same_record(row, record, fields, label):
    differences = {f: (row[f], record[f]) for f in fields if row[f] != record[f]}
    if differences:
        raise RuntimeError(f"010 {label} adulterado: {differences}")


def _assert_no_unique_conflicts(bind, table, record, unique_sets, label, exclude_id=None):
    for unique in unique_sets:
        clauses, params = [], {}
        for field in unique:
            value = record[field]
            if value is None:
                clauses.append(f"{field} IS NULL")
            else:
                clauses.append(f"{field} = :{field}")
                params[field] = value
        if exclude_id is not None:
            clauses.append("id != :exclude_id")
            params["exclude_id"] = exclude_id
        hit = bind.execute(sa.text(f"SELECT id FROM {table} WHERE {' AND '.join(clauses)}"), params).first()
        if hit is not None:
            raise RuntimeError(f"010 conflito de {label}: {dict(record)} colide com id {hit[0]}")


def _ensure_permission(bind, permission):
    record = {f: permission[f] for f in PERMISSION_FIELDS}
    row = bind.execute(sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"), {"id": record["id"]}).mappings().first()
    if row is not None:
        _assert_same_record(row, record, PERMISSION_FIELDS, "permissao")
        _assert_no_unique_conflicts(bind, "permissoes", record, (("chave",), ("modulo", "acao")), "permissao", exclude_id=record["id"])
        return record["id"]
    _assert_no_unique_conflicts(bind, "permissoes", record, (("chave",), ("modulo", "acao")), "permissao")
    bind.execute(sa.text("INSERT INTO permissoes (id, modulo, acao, chave, descricao) VALUES (:id, :modulo, :acao, :chave, :descricao)"), record)
    return record["id"]


def _ensure_link(bind, profile_id, permission_id):
    exists = bind.execute(sa.text("SELECT 1 FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"), {"p": profile_id, "m": permission_id}).first()
    if exists is None:
        bind.execute(sa.text("INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:p, :m)"), {"p": profile_id, "m": permission_id})


def _template_id(bind):
    row = bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c AND ilpi_id IS NULL"), {"c": TEMPLATE_KEY}).first()
    if row is None:
        raise RuntimeError("010 exige o template ilpi_admin da 004; execute as migrations em ordem")
    return row[0]


def _local_clone_ids(bind):
    return [r[0] for r in bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c AND ilpi_id IS NOT NULL"), {"c": TEMPLATE_KEY}).all()]


def _create_table():
    op.create_table(
        "graus_dependencia",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False, index=True),
        sa.Column("residente_id", sa.String(36), sa.ForeignKey("residentes.id"), nullable=False, index=True),
        sa.Column("classificacao", sa.String(20), nullable=False),
        sa.Column("sugestao_classificacao", sa.String(100), nullable=True),
        sa.Column("origem", sa.String(20), nullable=False),
        sa.Column("avaliacao_id", sa.String(36), sa.ForeignKey("avaliacoes.id"), nullable=True, index=True),
        sa.Column("justificativa", sa.Text(), nullable=False),
        sa.Column("confirmado_por", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("confirmado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("validade", sa.Date(), nullable=True),
        sa.Column("situacao", sa.String(20), nullable=False, server_default="ativo"),
        sa.Column("superseded_by", sa.String(36), sa.ForeignKey("graus_dependencia.id"), nullable=True),
        sa.Column("motivo_revogacao", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(
            ["residente_id", "ilpi_id"],
            ["residentes.id", "residentes.instituicao_id"],
            name="fk_graus_residente_ilpi",
        ),
        sa.CheckConstraint(
            "classificacao IN ('Grau I','Grau II','Grau III')",
            name="ck_graus_classificacao",
        ),
        sa.CheckConstraint(
            "origem IN ('avaliacao','manual','migracao')",
            name="ck_graus_origem",
        ),
        sa.CheckConstraint(
            "situacao IN ('ativo','substituido','revogado')",
            name="ck_graus_situacao",
        ),
        sa.CheckConstraint(
            "(origem = 'avaliacao' AND avaliacao_id IS NOT NULL) "
            "OR (origem IN ('manual','migracao') AND avaliacao_id IS NULL)",
            name="ck_graus_origem_avaliacao",
        ),
        sa.CheckConstraint(
            "(origem = 'migracao' OR confirmado_por IS NOT NULL)",
            name="ck_graus_confirmado_por",
        ),
    )
    op.create_index(
        "uq_graus_ativo_por_residente",
        "graus_dependencia",
        ["residente_id"],
        unique=True,
        sqlite_where=sa.text("situacao = 'ativo'"),
        postgresql_where=sa.text("situacao = 'ativo'"),
    )
    op.create_index("ix_graus_ilpi_residente", "graus_dependencia", ["ilpi_id", "residente_id"])
    op.create_index("ix_graus_avaliacao", "graus_dependencia", ["avaliacao_id"])


def _backfill_legado(bind):
    # Migra SOMENTE valores legados exatos (trim + enum). Texto
    # desconhecido é ignorado aqui: pendência de migração manual, nunca
    # conversão inventada. Sem autor histórico confiável: origem=migracao
    # com confirmado_por NULL (permitido pelo CHECK só para migracao).
    rows = bind.execute(
        sa.text(
            "SELECT id, instituicao_id, grau_dependencia FROM residentes "
            "WHERE grau_dependencia IS NOT NULL AND instituicao_id IS NOT NULL"
        )
    ).mappings().all()
    for row in rows:
        valor = (row["grau_dependencia"] or "").strip()
        if valor not in GRAU_LEGADO_VALIDO:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO graus_dependencia "
                "(id, ilpi_id, residente_id, classificacao, origem, justificativa, situacao) "
                "VALUES (:id, :ilpi, :residente, :classificacao, 'migracao', :justificativa, 'ativo')"
            ),
            {
                "id": str(uuid.uuid4()),
                "ilpi": row["instituicao_id"],
                "residente": row["id"],
                "classificacao": valor,
                "justificativa": BACKFILL_JUSTIFICATIVA,
            },
        )


def upgrade() -> None:
    bind = op.get_bind()

    _create_table()

    permission_ids = [_ensure_permission(bind, permission) for permission in NEW_PERMISSIONS]
    template_id = _template_id(bind)
    for permission_id in permission_ids:
        _ensure_link(bind, template_id, permission_id)
    for clone_id in _local_clone_ids(bind):
        for permission_id in permission_ids:
            _ensure_link(bind, clone_id, permission_id)

    _backfill_legado(bind)


def downgrade() -> None:
    bind = op.get_bind()

    permission_ids = [p["id"] for p in NEW_PERMISSIONS]
    for permission in NEW_PERMISSIONS:
        row = bind.execute(sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"), {"id": permission["id"]}).mappings().first()
        if row is not None:
            _assert_same_record(row, {f: permission[f] for f in PERMISSION_FIELDS}, PERMISSION_FIELDS, "permissao")
    allowed_profile_ids = set([_template_id(bind)] + _local_clone_ids(bind))
    external = bind.execute(sa.text("SELECT perfil_id, permissao_id FROM perfil_permissoes WHERE permissao_id IN :mids").bindparams(sa.bindparam("mids", expanding=True)), {"mids": permission_ids}).mappings().all()
    foreign = [(e["perfil_id"], e["permissao_id"]) for e in external if e["perfil_id"] not in allowed_profile_ids]
    if foreign:
        raise RuntimeError(f"010 recusa downgrade: vínculos externos às permissões: {sorted(foreign)}")
    for profile_id in allowed_profile_ids:
        for permission_id in permission_ids:
            bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"), {"p": profile_id, "m": permission_id})
    for permission_id in permission_ids:
        bind.execute(sa.text("DELETE FROM permissoes WHERE id = :id"), {"id": permission_id})

    # Downgrade remove a tabela e TODO o histórico de graus (perda
    # declarada). A coluna legada Residente.grau_dependencia permanece
    # intacta; nenhuma escrita nela é restaurada.
    op.drop_index("ix_graus_avaliacao", table_name="graus_dependencia")
    op.drop_index("ix_graus_ilpi_residente", table_name="graus_dependencia")
    op.drop_index("uq_graus_ativo_por_residente", table_name="graus_dependencia")
    op.drop_table("graus_dependencia")

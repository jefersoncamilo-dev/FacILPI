"""008_f5a2d_quartos_leitos_ausencias: Quarto/Leito + Ocupação + Ausências + Histórico.

Adds constraints to quartos_leitos (capacity=1, situacao check, unique indexes,
partial unique for resident), creates ocupacao_historico and ausencias tables,
adds 7 new RBAC permissions (quartos_leitos:ler/criar/atualizar/inativar,
ausencias:ler/criar/atualizar), grants them to ilpi_admin template and clones.
Platform superuser receives zero grants.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "008_f5a2d_quartos_leitos"
down_revision: Union[str, None] = "007_expandir_rbac_documentos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATE_KEY = "ilpi_admin"

NEW_PERMISSIONS = (
    {"id": "fac11000-0000-4000-8000-000000000045", "chave": "quartos_leitos:ler", "modulo": "quartos_leitos", "acao": "ler", "descricao": "Consultar quartos e leitos da ILPI atual.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000046", "chave": "quartos_leitos:criar", "modulo": "quartos_leitos", "acao": "criar", "descricao": "Criar quarto/leito na ILPI atual.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000047", "chave": "quartos_leitos:atualizar", "modulo": "quartos_leitos", "acao": "atualizar", "descricao": "Atualizar dados e operações de ocupação do leito.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000048", "chave": "quartos_leitos:inativar", "modulo": "quartos_leitos", "acao": "inativar", "descricao": "Inativar leito preservando histórico.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000049", "chave": "ausencias:ler", "modulo": "ausencias", "acao": "ler", "descricao": "Consultar ausências de residentes da ILPI atual.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000050", "chave": "ausencias:criar", "modulo": "ausencias", "acao": "criar", "descricao": "Registrar ausência de residente da ILPI atual.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000051", "chave": "ausencias:atualizar", "modulo": "ausencias", "acao": "atualizar", "descricao": "Atualizar/corrigir ou encerrar ausência.", "escopo_permitido": "ilpi"},
)

PERMISSION_FIELDS = ("id", "modulo", "acao", "chave", "descricao")


def _assert_same_record(row, record, fields, label):
    differences = {f: (row[f], record[f]) for f in fields if row[f] != record[f]}
    if differences:
        raise RuntimeError(f"008 {label} adulterado: {differences}")


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
            raise RuntimeError(f"008 conflito de {label}: {dict(record)} colide com id {hit[0]}")


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
        raise RuntimeError("008 exige o template ilpi_admin da 004; execute as migrations em ordem")
    return row[0]


def _local_clone_ids(bind):
    return [r[0] for r in bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c AND ilpi_id IS NOT NULL"), {"c": TEMPLATE_KEY}).all()]


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "sqlite":
        _upgrade_sqlite()
    else:
        _upgrade_pg()

    # --- RBAC permissions ---
    permission_ids = [_ensure_permission(bind, permission) for permission in NEW_PERMISSIONS]
    template_id = _template_id(bind)
    for permission_id in permission_ids:
        _ensure_link(bind, template_id, permission_id)
    for clone_id in _local_clone_ids(bind):
        for permission_id in permission_ids:
            _ensure_link(bind, clone_id, permission_id)


def _upgrade_pg():
    # --- QuartosLeito constraints on existing table (PostgreSQL) ---
    op.create_check_constraint(
        "ck_quartos_leitos_capacidade_1",
        "quartos_leitos",
        sa.text("capacidade = 1"),
    )
    op.create_check_constraint(
        "ck_quartos_leitos_situacao",
        "quartos_leitos",
        sa.text("situacao IN ('livre','reservado','bloqueado','manutencao','inativo')"),
    )
    # Required for composite FK from ocupacao_historico
    op.create_unique_constraint(
        "uq_quartos_leitos_id_ilpi",
        "quartos_leitos",
        ["id", "instituicao_id"],
    )
    # Partial unique: same quarto+leito only forbidden when unidade IS NULL
    op.create_index(
        "uq_quartos_leitos_inst_quarto_leito",
        "quartos_leitos",
        ["instituicao_id", "quarto", "leito"],
        unique=True,
        postgresql_where=sa.text("unidade IS NULL"),
    )
    op.create_unique_constraint(
        "uq_quartos_leitos_inst_unidade_quarto_leito",
        "quartos_leitos",
        ["instituicao_id", "unidade", "quarto", "leito"],
    )
    op.create_index(
        "uq_quartos_leitos_residente_ativo",
        "quartos_leitos",
        ["instituicao_id", "residente_atual_id"],
        unique=True,
        postgresql_where=sa.text("residente_atual_id IS NOT NULL"),
    )
    op.create_index("ix_quartos_leitos_ilpi_id", "quartos_leitos", ["instituicao_id"])

    # --- OcupacaoHistorico table ---
    op.create_table(
        "ocupacao_historico",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("instituicao_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("residente_id", sa.String(36), sa.ForeignKey("residentes.id"), nullable=False),
        sa.Column("quarto_leito_id", sa.String(36), sa.ForeignKey("quartos_leitos.id"), nullable=False),
        sa.Column("data_entrada", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_saida", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tipo_movimentacao", sa.String(50), nullable=False),
        sa.Column("motivo", sa.Text, nullable=True),
        sa.Column("usuario_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_foreign_key(
        "fk_ocupacao_hist_residente_ilpi",
        "ocupacao_historico",
        "residentes",
        ["residente_id", "instituicao_id"],
        ["id", "instituicao_id"],
    )
    op.create_foreign_key(
        "fk_ocupacao_hist_leito_ilpi",
        "ocupacao_historico",
        "quartos_leitos",
        ["quarto_leito_id", "instituicao_id"],
        ["id", "instituicao_id"],
    )
    op.create_index("ix_ocupacao_hist_ilpi_residente", "ocupacao_historico", ["instituicao_id", "residente_id"])
    op.create_index("ix_ocupacao_hist_ilpi_leito", "ocupacao_historico", ["instituicao_id", "quarto_leito_id"])

    # --- Ausencias table ---
    op.create_table(
        "ausencias",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("instituicao_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("residente_id", sa.String(36), sa.ForeignKey("residentes.id"), nullable=False),
        sa.Column("quarto_leito_id", sa.String(36), sa.ForeignKey("quartos_leitos.id"), nullable=True),
        sa.Column("tipo", sa.String(50), nullable=False),
        sa.Column("data_inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_fim", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo", sa.Text, nullable=False),
        sa.Column("observacoes", sa.Text, nullable=True),
        sa.Column("usuario_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_foreign_key(
        "fk_ausencias_residente_ilpi",
        "ausencias",
        "residentes",
        ["residente_id", "instituicao_id"],
        ["id", "instituicao_id"],
    )
    op.create_check_constraint(
        "ck_ausencias_tipo",
        "ausencias",
        sa.text("tipo IN ('hospitalizacao','saida_temporaria')"),
    )
    op.create_index(
        "uq_ausencias_ativa_por_residente",
        "ausencias",
        ["instituicao_id", "residente_id"],
        unique=True,
        postgresql_where=sa.text("data_fim IS NULL"),
    )
    op.create_index("ix_ausencias_ilpi_residente", "ausencias", ["instituicao_id", "residente_id"])


def _upgrade_sqlite():
    bind = op.get_bind()

    # --- QuartosLeito constraints on existing table (SQLite batch) ---
    with op.batch_alter_table("quartos_leitos") as batch_op:
        batch_op.create_check_constraint(
            "ck_quartos_leitos_capacidade_1",
            sa.text("capacidade = 1"),
        )
        batch_op.create_check_constraint(
            "ck_quartos_leitos_situacao",
            sa.text("situacao IN ('livre','reservado','bloqueado','manutencao','inativo')"),
        )
        # Required for composite FK from ocupacao_historico
        batch_op.create_unique_constraint(
            "uq_quartos_leitos_id_ilpi",
            ["id", "instituicao_id"],
        )
        batch_op.create_index(
            "uq_quartos_leitos_inst_quarto_leito",
            ["instituicao_id", "quarto", "leito"],
            unique=True,
            sqlite_where=sa.text("unidade IS NULL"),
        )
        batch_op.create_unique_constraint(
            "uq_quartos_leitos_inst_unidade_quarto_leito",
            ["instituicao_id", "unidade", "quarto", "leito"],
        )
        batch_op.create_index(
            "uq_quartos_leitos_residente_ativo",
            ["instituicao_id", "residente_atual_id"],
            unique=True,
            sqlite_where=sa.text("residente_atual_id IS NOT NULL"),
        )
        batch_op.create_index("ix_quartos_leitos_ilpi_id", ["instituicao_id"])

    # --- OcupacaoHistorico table (SQLite: create without composite FKs, then add via batch) ---
    op.create_table(
        "ocupacao_historico",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("instituicao_id", sa.String(36), nullable=False),
        sa.Column("residente_id", sa.String(36), nullable=False),
        sa.Column("quarto_leito_id", sa.String(36), nullable=False),
        sa.Column("data_entrada", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_saida", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tipo_movimentacao", sa.String(50), nullable=False),
        sa.Column("motivo", sa.Text, nullable=True),
        sa.Column("usuario_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["instituicao_id"], ["instituicoes.id"]),
        sa.ForeignKeyConstraint(["quarto_leito_id"], ["quartos_leitos.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["users.id"]),
    )
    with op.batch_alter_table("ocupacao_historico") as batch_op:
        batch_op.create_foreign_key(
            "fk_ocupacao_hist_residente_ilpi",
            "residentes",
            ["residente_id", "instituicao_id"],
            ["id", "instituicao_id"],
        )
        batch_op.create_foreign_key(
            "fk_ocupacao_hist_leito_ilpi",
            "quartos_leitos",
            ["quarto_leito_id", "instituicao_id"],
            ["id", "instituicao_id"],
        )
        batch_op.create_index("ix_ocupacao_hist_ilpi_residente", ["instituicao_id", "residente_id"])
        batch_op.create_index("ix_ocupacao_hist_ilpi_leito", ["instituicao_id", "quarto_leito_id"])

    # --- Ausencias table (SQLite: create without composite FK, then add via batch) ---
    op.create_table(
        "ausencias",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("instituicao_id", sa.String(36), nullable=False),
        sa.Column("residente_id", sa.String(36), nullable=False),
        sa.Column("quarto_leito_id", sa.String(36), nullable=True),
        sa.Column("tipo", sa.String(50), nullable=False),
        sa.Column("data_inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_fim", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo", sa.Text, nullable=False),
        sa.Column("observacoes", sa.Text, nullable=True),
        sa.Column("usuario_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["instituicao_id"], ["instituicoes.id"]),
        sa.ForeignKeyConstraint(["quarto_leito_id"], ["quartos_leitos.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["users.id"]),
        sa.CheckConstraint("tipo IN ('hospitalizacao','saida_temporaria')", name="ck_ausencias_tipo"),
    )
    with op.batch_alter_table("ausencias") as batch_op:
        batch_op.create_foreign_key(
            "fk_ausencias_residente_ilpi",
            "residentes",
            ["residente_id", "instituicao_id"],
            ["id", "instituicao_id"],
        )
        batch_op.create_index(
            "uq_ausencias_ativa_por_residente",
            ["instituicao_id", "residente_id"],
            unique=True,
            sqlite_where=sa.text("data_fim IS NULL"),
        )
        batch_op.create_index("ix_ausencias_ilpi_residente", ["instituicao_id", "residente_id"])


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # --- Remove RBAC permissions ---
    permission_ids = [p["id"] for p in NEW_PERMISSIONS]
    for permission in NEW_PERMISSIONS:
        row = bind.execute(sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"), {"id": permission["id"]}).mappings().first()
        if row is not None:
            _assert_same_record(row, {f: permission[f] for f in PERMISSION_FIELDS}, PERMISSION_FIELDS, "permissao")
    allowed_profile_ids = set([_template_id(bind)] + _local_clone_ids(bind))
    external = bind.execute(sa.text("SELECT perfil_id, permissao_id FROM perfil_permissoes WHERE permissao_id IN :mids").bindparams(sa.bindparam("mids", expanding=True)), {"mids": permission_ids}).mappings().all()
    foreign = [(e["perfil_id"], e["permissao_id"]) for e in external if e["perfil_id"] not in allowed_profile_ids]
    if foreign:
        raise RuntimeError(f"008 recusa downgrade: vínculos externos às permissões: {sorted(foreign)}")
    for profile_id in allowed_profile_ids:
        for permission_id in permission_ids:
            bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"), {"p": profile_id, "m": permission_id})
    for permission_id in permission_ids:
        bind.execute(sa.text("DELETE FROM permissoes WHERE id = :id"), {"id": permission_id})

    # --- Drop ausencias ---
    ausencia_count = bind.execute(sa.text("SELECT COUNT(*) FROM ausencias")).scalar()
    if ausencia_count and ausencia_count > 0:
        raise RuntimeError(f"008 recusa downgrade: {ausencia_count} registros em ausencias")
    op.drop_index("ix_ausencias_ilpi_residente", table_name="ausencias")
    op.drop_index("uq_ausencias_ativa_por_residente", table_name="ausencias")
    op.drop_table("ausencias")

    # --- Drop ocupacao_historico ---
    hist_count = bind.execute(sa.text("SELECT COUNT(*) FROM ocupacao_historico")).scalar()
    if hist_count and hist_count > 0:
        raise RuntimeError(f"008 recusa downgrade: {hist_count} registros em ocupacao_historico")
    op.drop_index("ix_ocupacao_hist_ilpi_leito", table_name="ocupacao_historico")
    op.drop_index("ix_ocupacao_hist_ilpi_residente", table_name="ocupacao_historico")
    op.drop_table("ocupacao_historico")

    # --- Remove quartos_leito constraints ---
    if dialect == "sqlite":
        with op.batch_alter_table("quartos_leitos") as batch_op:
            batch_op.drop_index("ix_quartos_leitos_ilpi_id")
            batch_op.drop_index("uq_quartos_leitos_residente_ativo")
            batch_op.drop_index("uq_quartos_leitos_inst_quarto_leito")
            batch_op.drop_constraint("uq_quartos_leitos_inst_unidade_quarto_leito", type_="unique")
            batch_op.drop_constraint("uq_quartos_leitos_id_ilpi", type_="unique")
            batch_op.drop_constraint("ck_quartos_leitos_situacao", type_="check")
            batch_op.drop_constraint("ck_quartos_leitos_capacidade_1", type_="check")
    else:
        op.drop_index("ix_quartos_leitos_ilpi_id", table_name="quartos_leitos")
        op.drop_index("uq_quartos_leitos_residente_ativo", table_name="quartos_leitos")
        op.drop_index("uq_quartos_leitos_inst_quarto_leito", table_name="quartos_leitos")
        op.drop_constraint("uq_quartos_leitos_inst_unidade_quarto_leito", table_name="quartos_leitos", type_="unique")
        op.drop_constraint("uq_quartos_leitos_id_ilpi", table_name="quartos_leitos", type_="unique")
        op.drop_constraint("ck_quartos_leitos_situacao", table_name="quartos_leitos", type_="check")
        op.drop_constraint("ck_quartos_leitos_capacidade_1", table_name="quartos_leitos", type_="check")

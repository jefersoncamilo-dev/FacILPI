"""C5 medication history and tenant-safe scheduling; catalog only, no grants.

Standalone schema: never import application models. SQLite batch recreation
requires foreign_keys OFF on the dedicated migration connection (env.py default).
Run with application writers stopped; preflight cannot protect concurrent writes.
"""

from alembic import op
import sqlalchemy as sa

revision = "012_c5_medicacao"
down_revision = "011_f5a4a_intercorrencias_rbac"
branch_labels = None
depends_on = None

NEW_PERMISSIONS = tuple(
    {
        "id": f"fac11000-0000-4000-8000-{number:012d}",
        "modulo": module,
        "acao": action,
        "chave": f"{module}:{action}",
        "descricao": description,
    }
    for number, module, action, description in (
        (60, "medicamentos", "ler", "Consultar medicamentos da ILPI atual."),
        (61, "medicamentos", "criar", "Criar medicamento na ILPI atual."),
        (62, "medicamentos", "atualizar", "Atualizar medicamento da ILPI atual."),
        (63, "prescricoes", "ler", "Consultar prescricoes da ILPI atual."),
        (64, "prescricoes", "criar", "Criar versao de prescricao na ILPI atual."),
        (65, "prescricoes", "atualizar", "Transicionar prescricao da ILPI atual."),
        (66, "doses_previstas", "ler", "Consultar doses previstas da ILPI atual."),
        (67, "administracoes", "ler", "Consultar administracoes da ILPI atual."),
        (68, "administracoes", "criar", "Registrar administracao na ILPI atual."),
        (69, "administracoes", "corrigir", "Estornar e corrigir administracao na ILPI atual."),
    )
)

# Frozen column specifications also define the lossless-downgrade preflight.
PRESCRICAO_FIELDS = (
    ("autor_id", sa.String(36)),
    ("prescritor_nome", sa.String(255)),
    ("prescritor_categoria", sa.String(50)),
    ("prescritor_conselho", sa.String(50)),
    ("prescritor_numero", sa.String(50)),
    ("prescritor_uf", sa.String(2)),
    ("unidade", sa.String(50)),
    ("medicamento_snapshot", sa.JSON()),
    ("anterior_id", sa.String(36)),
    ("motivo_versao", sa.Text()),
    ("ativado_por", sa.String(36)),
    ("ativado_em", sa.DateTime(timezone=True)),
    ("suspenso_por", sa.String(36)),
    ("suspenso_em", sa.DateTime(timezone=True)),
    ("motivo_suspensao", sa.Text()),
    ("encerrado_por", sa.String(36)),
    ("encerrado_em", sa.DateTime(timezone=True)),
    ("motivo_encerramento", sa.Text()),
    ("substituido_em", sa.DateTime(timezone=True)),
)
PRESCRICAO_USERS = ("autor_id", "ativado_por", "suspenso_por", "encerrado_por")
STATES = ("rascunho", "ativa", "suspensa", "substituida", "encerrada")


def _preflight_connection(bind):
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("012 suporta somente SQLite e PostgreSQL")
    if bind.dialect.name == "sqlite" and bind.exec_driver_sql("PRAGMA foreign_keys").scalar():
        # Changing this pragma inside Alembic's transaction silently does nothing.
        raise RuntimeError("012 exige conexao exclusiva SQLite com foreign_keys=OFF antes da transacao")


def _preflight_permissions(bind, downgrade=False):
    missing = []
    for permission in NEW_PERMISSIONS:
        rows = bind.execute(sa.text(
            "SELECT id, modulo, acao, chave, descricao FROM permissoes "
            "WHERE id = :id OR chave = :chave OR (modulo = :modulo AND acao = :acao)"
        ), permission).mappings().all()
        if rows and (len(rows) != 1 or dict(rows[0]) != permission):
            raise RuntimeError("012 conflito no catalogo de medicacao")
        if not rows:
            missing.append(permission)
        if downgrade and bind.execute(sa.text(
            "SELECT 1 FROM perfil_permissoes WHERE permissao_id = :id"
        ), permission).first():
            raise RuntimeError("012 recusa downgrade: grants externos de medicacao")
    return missing


def _preflight_legacy(bind):
    institutions = set(bind.execute(sa.text("SELECT id FROM instituicoes")).scalars())
    residents = dict(bind.execute(sa.text("SELECT id, instituicao_id FROM residentes")).all())
    medications = set(bind.execute(sa.text("SELECT id FROM medicamentos")).scalars())
    tenants = {identifier: set() for identifier in medications}
    prescriptions = bind.execute(sa.text("SELECT * FROM prescricoes")).mappings().all()
    resolved = []
    for row in prescriptions:
        tenant = residents.get(row["residente_id"])
        if not tenant or tenant not in institutions or row["ilpi_id"] not in (None, tenant):
            raise RuntimeError(f"012 prescricao {row['id']}: tenant ausente ou inconsistente")
        if row["medicamento_id"] not in medications:
            raise RuntimeError(f"012 prescricao {row['id']}: medicamento orfao")
        if row["situacao"] not in STATES:
            raise RuntimeError(f"012 prescricao {row['id']}: situacao desconhecida")
        tenants[row["medicamento_id"]].add(tenant)
        # Legacy free text is retained verbatim, never parsed into a schedule or
        # professional credentials. Incomplete active orders require sanitation.
        complete = all(
            row[field] is not None and str(row[field]).strip()
            for field in ("prescritor", "dose", "via", "frequencia", "horarios", "inicio")
        )
        state = "rascunho" if row["situacao"] == "ativa" and not complete else row["situacao"]
        resolved.append({"id": row["id"], "ilpi": tenant, "situacao": state})
    for identifier, candidates in tenants.items():
        if len(candidates) != 1:
            raise RuntimeError(f"012 medicamento {identifier}: sem referencia ou multiplos tenants")
    return resolved, {identifier: next(iter(values)) for identifier, values in tenants.items()}


def _partial(name, table, columns, predicate):
    op.create_index(name, table, columns, unique=True,
                    sqlite_where=sa.text(predicate), postgresql_where=sa.text(predicate))


def _create_clinical_tables():
    op.create_table(
        "programacoes_medicacao",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), nullable=False),
        sa.Column("residente_id", sa.String(36), nullable=False),
        sa.Column("prescricao_id", sa.String(36), nullable=False),
        sa.Column("horarios", sa.JSON(), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("vigencia_inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vigencia_fim", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cobertura_ate", sa.DateTime(timezone=True), nullable=True),
        sa.Column("situacao", sa.String(20), nullable=False, server_default="ativa"),
        sa.Column("autor_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["prescricao_id", "ilpi_id", "residente_id"], ["prescricoes.id", "prescricoes.ilpi_id", "prescricoes.residente_id"], name="fk_programacoes_prescricao", ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "ilpi_id", "residente_id", "prescricao_id", name="uq_programacoes_cadeia"),
        sa.UniqueConstraint("prescricao_id", name="uq_programacoes_prescricao"),
        sa.CheckConstraint("situacao IN ('ativa','cancelada')", name="ck_programacoes_situacao"),
    )
    op.create_index("ix_programacoes_ilpi_residente_inicio", "programacoes_medicacao", ["ilpi_id", "residente_id", "vigencia_inicio"])
    op.create_table(
        "doses_previstas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), nullable=False),
        sa.Column("residente_id", sa.String(36), nullable=False),
        sa.Column("prescricao_id", sa.String(36), nullable=False),
        sa.Column("programacao_id", sa.String(36), nullable=False),
        sa.Column("previsto_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("situacao", sa.String(20), nullable=False, server_default="prevista"),
        sa.Column("cancelado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelado_por", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("motivo_cancelamento", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["programacao_id", "ilpi_id", "residente_id", "prescricao_id"], ["programacoes_medicacao.id", "programacoes_medicacao.ilpi_id", "programacoes_medicacao.residente_id", "programacoes_medicacao.prescricao_id"], name="fk_doses_programacao", ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "ilpi_id", "residente_id", "prescricao_id", name="uq_doses_cadeia"),
        sa.UniqueConstraint("programacao_id", "previsto_em", name="uq_doses_programacao_horario"),
        sa.CheckConstraint("situacao IN ('prevista','cancelada')", name="ck_doses_situacao"),
    )
    op.create_index("ix_doses_ilpi_residente_previsto", "doses_previstas", ["ilpi_id", "residente_id", "previsto_em"])
    op.create_table(
        "administracoes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), nullable=False),
        sa.Column("residente_id", sa.String(36), nullable=False),
        sa.Column("prescricao_id", sa.String(36), nullable=False),
        sa.Column("dose_prevista_id", sa.String(36), nullable=False),
        sa.Column("resultado", sa.String(20), nullable=False),
        sa.Column("ocorrido_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registrado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("executor_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantidade_realizada", sa.Numeric(14, 4), nullable=True),
        sa.Column("justificativa", sa.Text(), nullable=True),
        sa.Column("observacao", sa.Text(), nullable=True),
        sa.Column("estornado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estornado_por", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("motivo_estorno", sa.Text(), nullable=True),
        sa.Column("substitui_id", sa.String(36), nullable=True),
        sa.ForeignKeyConstraint(["dose_prevista_id", "ilpi_id", "residente_id", "prescricao_id"], ["doses_previstas.id", "doses_previstas.ilpi_id", "doses_previstas.residente_id", "doses_previstas.prescricao_id"], name="fk_administracoes_dose", ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "ilpi_id", "residente_id", "prescricao_id", "dose_prevista_id", name="uq_administracoes_cadeia"),
        sa.ForeignKeyConstraint(["substitui_id", "ilpi_id", "residente_id", "prescricao_id", "dose_prevista_id"], ["administracoes.id", "administracoes.ilpi_id", "administracoes.residente_id", "administracoes.prescricao_id", "administracoes.dose_prevista_id"], name="fk_administracoes_substitui", ondelete="RESTRICT"),
        sa.CheckConstraint("resultado IN ('administrada','recusada','omitida')", name="ck_administracoes_resultado"),
        sa.CheckConstraint("quantidade_realizada IS NULL OR quantidade_realizada > 0", name="ck_administracoes_quantidade"),
        sa.CheckConstraint("resultado <> 'administrada' OR quantidade_realizada IS NOT NULL", name="ck_administracoes_quantidade_obrigatoria"),
        sa.CheckConstraint("resultado = 'administrada' OR (justificativa IS NOT NULL AND length(trim(justificativa)) > 0)", name="ck_administracoes_justificativa"),
        sa.CheckConstraint("(estornado_em IS NULL AND estornado_por IS NULL AND motivo_estorno IS NULL) OR (estornado_em IS NOT NULL AND estornado_por IS NOT NULL AND motivo_estorno IS NOT NULL AND length(trim(motivo_estorno)) > 0)", name="ck_administracoes_estorno"),
    )
    _partial("uq_administracoes_dose_vigente", "administracoes", ["dose_prevista_id"], "estornado_em IS NULL")
    _partial("uq_administracoes_substitui", "administracoes", ["substitui_id"], "substitui_id IS NOT NULL")
    op.create_index("ix_administracoes_ilpi_residente_ocorrido", "administracoes", ["ilpi_id", "residente_id", "ocorrido_em"])


def upgrade():
    bind = op.get_bind()
    _preflight_connection(bind)
    missing = _preflight_permissions(bind)
    prescriptions, medications = _preflight_legacy(bind)

    # Every legacy row and every seed has been checked before the first mutation.
    op.add_column("medicamentos", sa.Column("ilpi_id", sa.String(36), nullable=True))
    op.add_column("medicamentos", sa.Column("autor_id", sa.String(36), nullable=True))
    for identifier, tenant in medications.items():
        bind.execute(sa.text("UPDATE medicamentos SET ilpi_id = :ilpi WHERE id = :id"), {"id": identifier, "ilpi": tenant})
    with op.batch_alter_table("medicamentos") as batch:
        batch.alter_column("ilpi_id", existing_type=sa.String(36), nullable=False)
        batch.create_foreign_key("fk_medicamentos_ilpi", "instituicoes", ["ilpi_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_medicamentos_autor", "users", ["autor_id"], ["id"], ondelete="RESTRICT")
        batch.create_unique_constraint("uq_medicamentos_id_ilpi", ["id", "ilpi_id"])
        batch.create_index("ix_medicamentos_ilpi_id", ["ilpi_id"])
    for row in prescriptions:
        bind.execute(sa.text("UPDATE prescricoes SET ilpi_id = :ilpi, situacao = :situacao WHERE id = :id"), row)
    with op.batch_alter_table("prescricoes") as batch:
        for name, datatype in PRESCRICAO_FIELDS:
            batch.add_column(sa.Column(name, datatype, nullable=True))
        batch.add_column(sa.Column("lock_version", sa.Integer(), nullable=False, server_default="0"))
        batch.alter_column("ilpi_id", existing_type=sa.String(36), nullable=False)
        batch.alter_column("situacao", existing_type=sa.String(50), nullable=False)
        batch.drop_constraint("fk_prescricoes_residente_ilpi", type_="foreignkey")
        batch.create_foreign_key("fk_prescricoes_residente_ilpi", "residentes", ["residente_id", "ilpi_id"], ["id", "instituicao_id"], ondelete="RESTRICT")
        for name in PRESCRICAO_USERS:
            batch.create_foreign_key(f"fk_prescricoes_{name}", "users", [name], ["id"], ondelete="RESTRICT")
        batch.create_unique_constraint("uq_prescricoes_id_ilpi_residente", ["id", "ilpi_id", "residente_id"])
        batch.create_foreign_key("fk_prescricoes_medicamento_ilpi", "medicamentos", ["medicamento_id", "ilpi_id"], ["id", "ilpi_id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_prescricoes_anterior", "prescricoes", ["anterior_id", "ilpi_id", "residente_id"], ["id", "ilpi_id", "residente_id"], ondelete="RESTRICT")
        batch.create_check_constraint("ck_prescricoes_situacao", "situacao IN ('rascunho','ativa','suspensa','substituida','encerrada')")
        batch.create_index("ix_prescricoes_ilpi_residente_inicio", ["ilpi_id", "residente_id", "inicio"])
    _partial("uq_prescricoes_anterior", "prescricoes", ["anterior_id"], "anterior_id IS NOT NULL")
    _create_clinical_tables()
    for permission in missing:
        bind.execute(sa.text(
            "INSERT INTO permissoes (id, modulo, acao, chave, descricao) "
            "VALUES (:id, :modulo, :acao, :chave, :descricao)"
        ), permission)


def downgrade():
    bind = op.get_bind()
    _preflight_connection(bind)
    _preflight_permissions(bind, downgrade=True)
    for table in ("administracoes", "doses_previstas", "programacoes_medicacao"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(f"012 recusa downgrade: historico em {table}")
    unsupported = " OR ".join(f"{name} IS NOT NULL" for name, _ in PRESCRICAO_FIELDS)
    if bind.execute(sa.text(
        f"SELECT 1 FROM prescricoes WHERE {unsupported} OR lock_version <> 0 LIMIT 1"
    )).first():
        raise RuntimeError("012 recusa downgrade: dados de prescricao nao representaveis no legado")
    if bind.execute(sa.text("SELECT 1 FROM medicamentos WHERE autor_id IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("012 recusa downgrade: autoria de medicamento")
    # Medication tenancy may only be discarded if exactly recoverable by the
    # same resident-only rule. Prescription tenant metadata remains in place.
    _, tenants = _preflight_legacy(bind)
    for row in bind.execute(sa.text("SELECT id, ilpi_id FROM medicamentos")).mappings():
        if row["ilpi_id"] != tenants[row["id"]]:
            raise RuntimeError("012 recusa downgrade: tenant de medicamento nao recuperavel")

    for table in ("administracoes", "doses_previstas", "programacoes_medicacao"):
        op.drop_table(table)
    with op.batch_alter_table("prescricoes") as batch:
        batch.drop_index("uq_prescricoes_anterior")
        batch.drop_index("ix_prescricoes_ilpi_residente_inicio")
        batch.drop_constraint("fk_prescricoes_anterior", type_="foreignkey")
        batch.drop_constraint("fk_prescricoes_medicamento_ilpi", type_="foreignkey")
        batch.drop_constraint("uq_prescricoes_id_ilpi_residente", type_="unique")
        batch.drop_constraint("ck_prescricoes_situacao", type_="check")
        batch.drop_constraint("fk_prescricoes_residente_ilpi", type_="foreignkey")
        batch.create_foreign_key("fk_prescricoes_residente_ilpi", "residentes", ["residente_id", "ilpi_id"], ["id", "instituicao_id"])
        for name in PRESCRICAO_USERS:
            batch.drop_constraint(f"fk_prescricoes_{name}", type_="foreignkey")
        for name, _ in PRESCRICAO_FIELDS:
            batch.drop_column(name)
        batch.drop_column("lock_version")
        batch.alter_column("ilpi_id", existing_type=sa.String(36), nullable=True)
        batch.alter_column("situacao", existing_type=sa.String(50), nullable=True)
    with op.batch_alter_table("medicamentos") as batch:
        batch.drop_index("ix_medicamentos_ilpi_id")
        batch.drop_constraint("uq_medicamentos_id_ilpi", type_="unique")
        batch.drop_constraint("fk_medicamentos_ilpi", type_="foreignkey")
        batch.drop_constraint("fk_medicamentos_autor", type_="foreignkey")
        batch.drop_column("autor_id")
        batch.drop_column("ilpi_id")
    for permission in NEW_PERMISSIONS:
        bind.execute(sa.text("DELETE FROM permissoes WHERE id = :id"), permission)

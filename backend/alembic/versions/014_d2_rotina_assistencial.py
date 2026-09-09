"""014_d2_rotina_assistencial: Programação, Ocorrência, Execução e Meu Plantão.

Cria programacoes_cuidado (horários fixos confirmados da Intervenção do
PAIS vigente), ocorrencias_cuidado (previstas persistidas; pendente e
atrasada são DERIVADOS, nunca colunas) e execucoes_cuidado (append-only
com estorno+substituto, sem PUT livre, sem DELETE).

Meu Plantão é PROJEÇÃO (sem tabela): ocorrências pendentes + doses
previstas pendentes + intercorrências abertas. Tarefa legada preservada
isolada: nenhum dado migrado, nada apagado, nenhuma autoria inventada.
DosePrevista de Medicação NÃO é duplicada. Intercorrência NÃO gera tarefa.

Adiciona 10 permissões (programacoes/ocorrencias/execucoes/plantao) ao
catálogo e concede ao template ilpi_admin e clones locais como
GRANT_TECNICO_TRANSITORIO_D2 (S.1 pendente). Platform zero grants.

Migrations 001-013 não são modificadas.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "014_d2_rotina_assistencial"
down_revision: Union[str, None] = "013_d1_pais"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATE_KEY = "ilpi_admin"

NEW_PERMISSIONS = (
    {"id": "fac11000-0000-4000-8000-000000000076", "chave": "programacoes:ler", "modulo": "programacoes", "acao": "ler", "descricao": "Consultar programacoes de cuidado da ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000077", "chave": "programacoes:criar", "modulo": "programacoes", "acao": "criar", "descricao": "Criar programacao de cuidado na ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000078", "chave": "programacoes:atualizar", "modulo": "programacoes", "acao": "atualizar", "descricao": "Atualizar ou reconciliar programacao ativa na ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000079", "chave": "programacoes:inativar", "modulo": "programacoes", "acao": "inativar", "descricao": "Cancelar programacao ativa na ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000080", "chave": "ocorrencias:ler", "modulo": "ocorrencias", "acao": "ler", "descricao": "Consultar ocorrencias de cuidado da ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000081", "chave": "ocorrencias:cancelar", "modulo": "ocorrencias", "acao": "cancelar", "descricao": "Cancelar ocorrencia futura sem execucao na ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000082", "chave": "execucoes:ler", "modulo": "execucoes", "acao": "ler", "descricao": "Consultar execucoes de cuidado da ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000083", "chave": "execucoes:criar", "modulo": "execucoes", "acao": "criar", "descricao": "Registrar execucao de cuidado na ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000084", "chave": "execucoes:corrigir", "modulo": "execucoes", "acao": "corrigir", "descricao": "Estornar execucao de cuidado na ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000085", "chave": "plantao:ler", "modulo": "plantao", "acao": "ler", "descricao": "Consultar projecao Meu Plantao da ILPI atual."},
)

PERMISSION_FIELDS = ("id", "modulo", "acao", "chave", "descricao")


def _preflight_connection(bind):
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("014 suporta somente SQLite e PostgreSQL")
    if bind.dialect.name == "sqlite" and bind.exec_driver_sql("PRAGMA foreign_keys").scalar():
        # Changing this pragma inside Alembic's transaction silently does nothing.
        raise RuntimeError("014 exige conexao exclusiva SQLite com foreign_keys=OFF antes da transacao")


def _assert_same_record(row, record, fields, label):
    differences = {f: (row[f], record[f]) for f in fields if row[f] != record[f]}
    if differences:
        raise RuntimeError(f"014 {label} adulterado: {differences}")


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
            raise RuntimeError(f"014 conflito de {label}: {dict(record)} colide com id {hit[0]}")


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
        raise RuntimeError("014 exige o template ilpi_admin da 004; execute as migrations em ordem")
    return row[0]


def _local_clone_ids(bind):
    return [r[0] for r in bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c AND ilpi_id IS NOT NULL"), {"c": TEMPLATE_KEY}).all()]


def _preflight_permissions(bind):
    for permission in NEW_PERMISSIONS:
        record = {f: permission[f] for f in PERMISSION_FIELDS}
        rows = bind.execute(sa.text(
            "SELECT id, modulo, acao, chave, descricao FROM permissoes "
            "WHERE id = :id OR chave = :chave OR (modulo = :modulo AND acao = :acao)"
        ), record).mappings().all()
        if rows and (len(rows) != 1 or dict(rows[0]) != record):
            raise RuntimeError("014 conflito no catalogo da rotina assistencial")


def _preflight_tarefa_legada(bind):
    # Tarefa é legado preservado isolado: inspeciona sem migrar, sem apagar,
    # sem inventar autoria. Executor/responsável texto livre jamais viram
    # User/Funcionario aqui.
    total = bind.execute(sa.text("SELECT COUNT(*) FROM tarefas")).scalar()
    sem_responsavel = bind.execute(sa.text(
        "SELECT COUNT(*) FROM tarefas WHERE residente_id IS NULL")).scalar()
    return {"total": total, "sem_residente": sem_responsavel}


def _partial(name, table, columns, predicate):
    op.create_index(name, table, columns, unique=True,
                    sqlite_where=sa.text(predicate), postgresql_where=sa.text(predicate))


def _create_tables():
    op.create_table(
        "programacoes_cuidado",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("residente_id", sa.String(36), nullable=False),
        sa.Column("plano_id", sa.String(36), nullable=False),
        sa.Column("intervencao_id", sa.String(36), nullable=False),
        sa.Column("autor_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("horarios", sa.JSON(), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("vigencia_inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vigencia_fim", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cobertura_ate", sa.DateTime(timezone=True), nullable=True),
        sa.Column("perfil_responsavel", sa.String(100), nullable=True),
        sa.Column("funcionario_designado_id", sa.String(36), sa.ForeignKey("funcionarios.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("prioridade", sa.String(20), nullable=False, server_default="media"),
        sa.Column("situacao", sa.String(20), nullable=False, server_default="ativa"),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["residente_id", "ilpi_id"], ["residentes.id", "residentes.instituicao_id"], name="fk_progcuidado_residente", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["plano_id", "ilpi_id"], ["planos_cuidados.id", "planos_cuidados.ilpi_id"], name="fk_progcuidado_plano", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["intervencao_id", "ilpi_id", "plano_id"], ["pais_intervencoes.id", "pais_intervencoes.ilpi_id", "pais_intervencoes.plano_id"], name="fk_progcuidado_intervencao", ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "ilpi_id", "residente_id", name="uq_progcuidado_cadeia"),
        sa.CheckConstraint("situacao IN ('ativa','cancelada')", name="ck_progcuidado_situacao"),
    )
    op.create_index("ix_progcuidado_ilpi_residente", "programacoes_cuidado", ["ilpi_id", "residente_id"])
    op.create_index("ix_progcuidado_intervencao", "programacoes_cuidado", ["intervencao_id"])
    op.create_table(
        "ocorrencias_cuidado",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("residente_id", sa.String(36), nullable=False),
        sa.Column("plano_id", sa.String(36), nullable=False),
        sa.Column("intervencao_id", sa.String(36), nullable=False),
        sa.Column("programacao_id", sa.String(36), nullable=False),
        sa.Column("previsto_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("situacao", sa.String(20), nullable=False, server_default="prevista"),
        sa.Column("cancelado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelado_por", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("motivo_cancelamento", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["programacao_id", "ilpi_id", "residente_id"], ["programacoes_cuidado.id", "programacoes_cuidado.ilpi_id", "programacoes_cuidado.residente_id"], name="fk_ocorr_programacao", ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "ilpi_id", "residente_id", "programacao_id", name="uq_ocorr_cadeia"),
        sa.UniqueConstraint("programacao_id", "previsto_em", name="uq_ocorr_programacao_horario"),
        sa.CheckConstraint("situacao IN ('prevista','cancelada')", name="ck_ocorr_situacao"),
        sa.CheckConstraint("(situacao = 'prevista' AND cancelado_em IS NULL AND cancelado_por IS NULL AND motivo_cancelamento IS NULL) OR (situacao = 'cancelada' AND cancelado_em IS NOT NULL AND cancelado_por IS NOT NULL AND motivo_cancelamento IS NOT NULL AND length(trim(motivo_cancelamento)) > 0)", name="ck_ocorr_cancelamento"),
    )
    op.create_index("ix_ocorr_ilpi_residente_previsto", "ocorrencias_cuidado", ["ilpi_id", "residente_id", "previsto_em"])
    op.create_table(
        "execucoes_cuidado",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("residente_id", sa.String(36), nullable=False),
        sa.Column("programacao_id", sa.String(36), nullable=False),
        sa.Column("ocorrencia_id", sa.String(36), nullable=False),
        sa.Column("resultado", sa.String(20), nullable=False),
        sa.Column("ocorrido_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registrado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("executor_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("observacao", sa.Text(), nullable=True),
        sa.Column("justificativa", sa.Text(), nullable=True),
        sa.Column("estornado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estornado_por", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("motivo_estorno", sa.Text(), nullable=True),
        sa.Column("substitui_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["ocorrencia_id", "ilpi_id", "residente_id", "programacao_id"], ["ocorrencias_cuidado.id", "ocorrencias_cuidado.ilpi_id", "ocorrencias_cuidado.residente_id", "ocorrencias_cuidado.programacao_id"], name="fk_exec_ocorrencia", ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "ilpi_id", "residente_id", "programacao_id", "ocorrencia_id", name="uq_exec_cadeia"),
        sa.ForeignKeyConstraint(["substitui_id", "ilpi_id", "residente_id", "programacao_id", "ocorrencia_id"], ["execucoes_cuidado.id", "execucoes_cuidado.ilpi_id", "execucoes_cuidado.residente_id", "execucoes_cuidado.programacao_id", "execucoes_cuidado.ocorrencia_id"], name="fk_exec_substitui", ondelete="RESTRICT"),
        sa.CheckConstraint("resultado IN ('executada','recusada','omitida')", name="ck_exec_resultado"),
        sa.CheckConstraint("resultado = 'executada' OR (justificativa IS NOT NULL AND length(trim(justificativa)) > 0)", name="ck_exec_justificativa"),
        sa.CheckConstraint("(estornado_em IS NULL AND estornado_por IS NULL AND motivo_estorno IS NULL) OR (estornado_em IS NOT NULL AND estornado_por IS NOT NULL AND motivo_estorno IS NOT NULL AND length(trim(motivo_estorno)) > 0)", name="ck_exec_estorno"),
    )
    _partial("uq_exec_ocorrencia_vigente", "execucoes_cuidado", ["ocorrencia_id"], "estornado_em IS NULL")
    _partial("uq_exec_substitui", "execucoes_cuidado", ["substitui_id"], "substitui_id IS NOT NULL")
    op.create_index("ix_exec_ilpi_residente_ocorrido", "execucoes_cuidado", ["ilpi_id", "residente_id", "ocorrido_em"])


def upgrade() -> None:
    bind = op.get_bind()
    _preflight_connection(bind)
    _preflight_permissions(bind)
    _preflight_tarefa_legada(bind)

    _create_tables()

    permission_ids = [_ensure_permission(bind, permission) for permission in NEW_PERMISSIONS]
    template_id = _template_id(bind)
    for permission_id in permission_ids:
        _ensure_link(bind, template_id, permission_id)
    for clone_id in _local_clone_ids(bind):
        for permission_id in permission_ids:
            _ensure_link(bind, clone_id, permission_id)


def downgrade() -> None:
    bind = op.get_bind()
    _preflight_connection(bind)
    for table in ("execucoes_cuidado", "ocorrencias_cuidado", "programacoes_cuidado"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(f"014 recusa downgrade: historico em {table}")

    permission_ids = [p["id"] for p in NEW_PERMISSIONS]
    for permission in NEW_PERMISSIONS:
        row = bind.execute(sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"), {"id": permission["id"]}).mappings().first()
        if row is not None:
            _assert_same_record(row, {f: permission[f] for f in PERMISSION_FIELDS}, PERMISSION_FIELDS, "permissao")
    allowed_profile_ids = set([_template_id(bind)] + _local_clone_ids(bind))
    external = bind.execute(sa.text("SELECT perfil_id, permissao_id FROM perfil_permissoes WHERE permissao_id IN :mids").bindparams(sa.bindparam("mids", expanding=True)), {"mids": permission_ids}).mappings().all()
    foreign = [(e["perfil_id"], e["permissao_id"]) for e in external if e["perfil_id"] not in allowed_profile_ids]
    if foreign:
        raise RuntimeError(f"014 recusa downgrade: vínculos externos às permissões: {sorted(foreign)}")
    for profile_id in allowed_profile_ids:
        for permission_id in permission_ids:
            bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"), {"p": profile_id, "m": permission_id})
    for permission_id in permission_ids:
        bind.execute(sa.text("DELETE FROM permissoes WHERE id = :id"), {"id": permission_id})

    op.drop_index("ix_exec_ilpi_residente_ocorrido", table_name="execucoes_cuidado")
    op.drop_index("uq_exec_substitui", table_name="execucoes_cuidado")
    op.drop_index("uq_exec_ocorrencia_vigente", table_name="execucoes_cuidado")
    op.drop_table("execucoes_cuidado")
    op.drop_index("ix_ocorr_ilpi_residente_previsto", table_name="ocorrencias_cuidado")
    op.drop_table("ocorrencias_cuidado")
    op.drop_index("ix_progcuidado_intervencao", table_name="programacoes_cuidado")
    op.drop_index("ix_progcuidado_ilpi_residente", table_name="programacoes_cuidado")
    op.drop_table("programacoes_cuidado")

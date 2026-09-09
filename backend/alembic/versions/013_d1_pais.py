"""013_d1_pais: PAIS/Plano de Cuidados — fonte única, itens, revisão e versionamento.

Evolui planos_cuidados (estados estáveis, autoria User da sessão,
revisor/aprovador Funcionario, anterior_id/superseded_by, lock_version) e
cria as filhas pais_necessidades / pais_metas / pais_intervencoes como
fonte oficial do planejamento assistencial. Tarefa NÃO é fonte do PAIS.

Adiciona 6 permissões agrupadas planos_cuidados:* (ler/criar/atualizar/
revisar/aprovar/encerrar) ao catálogo e concede ao template ilpi_admin e
clones locais (estratégia conservadora do projeto). Platform superuser
recebe zero grants clínicos. Nenhuma automação clínica entre PAIS e
Avaliações/Grau/Intercorrências/Medicação/Tarefas.

Migrations 001-012 não são modificadas.
"""

import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "013_d1_pais"
down_revision: Union[str, None] = "012_c5_medicacao"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATE_KEY = "ilpi_admin"

NEW_PERMISSIONS = (
    {"id": "fac11000-0000-4000-8000-000000000070", "chave": "planos_cuidados:ler", "modulo": "planos_cuidados", "acao": "ler", "descricao": "Consultar planos de cuidados/PAIS da ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000071", "chave": "planos_cuidados:criar", "modulo": "planos_cuidados", "acao": "criar", "descricao": "Criar plano de cuidados/PAIS na ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000072", "chave": "planos_cuidados:atualizar", "modulo": "planos_cuidados", "acao": "atualizar", "descricao": "Atualizar rascunho do PAIS e gerar nova versao na ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000073", "chave": "planos_cuidados:revisar", "modulo": "planos_cuidados", "acao": "revisar", "descricao": "Registrar revisao tecnica do PAIS na ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000074", "chave": "planos_cuidados:aprovar", "modulo": "planos_cuidados", "acao": "aprovar", "descricao": "Aprovar e ativar vigencia do PAIS na ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000075", "chave": "planos_cuidados:encerrar", "modulo": "planos_cuidados", "acao": "encerrar", "descricao": "Encerrar PAIS vigente na ILPI atual."},
)

PERMISSION_FIELDS = ("id", "modulo", "acao", "chave", "descricao")

PLANO_STATES = ("rascunho", "em_elaboracao", "em_revisao", "aprovado", "vigente", "encerrado", "substituido")

# Mapeamento defensivo do texto livre legado para estados estáveis. O stub
# legado era rascunho operacional; texto desconhecido colapsa para rascunho
# (nunca para estado aprovado/vigente) e nunca inventa revisor/aprovador.
_LEGACY_STATE_MAP = {
    "rascunho": "rascunho",
    "em elaboracao": "em_elaboracao",
    "em elaboração": "em_elaboracao",
    "em elaboracão": "em_elaboracao",
    "em revisao": "em_revisao",
    "em revisão": "em_revisao",
    "aprovado": "aprovado",
    "vigente": "vigente",
    "encerrado": "encerrado",
    "substituido": "substituido",
    "substituído": "substituido",
}


def _normalize_state(value):
    if value is None:
        return "rascunho"
    return _LEGACY_STATE_MAP.get(str(value).strip().lower(), "rascunho")


def _preflight_connection(bind):
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("013 suporta somente SQLite e PostgreSQL")
    if bind.dialect.name == "sqlite" and bind.exec_driver_sql("PRAGMA foreign_keys").scalar():
        # Changing this pragma inside Alembic's transaction silently does nothing.
        raise RuntimeError("013 exige conexao exclusiva SQLite com foreign_keys=OFF antes da transacao")


def _assert_same_record(row, record, fields, label):
    differences = {f: (row[f], record[f]) for f in fields if row[f] != record[f]}
    if differences:
        raise RuntimeError(f"013 {label} adulterado: {differences}")


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
            raise RuntimeError(f"013 conflito de {label}: {dict(record)} colide com id {hit[0]}")


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
        raise RuntimeError("013 exige o template ilpi_admin da 004; execute as migrations em ordem")
    return row[0]


def _local_clone_ids(bind):
    return [r[0] for r in bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c AND ilpi_id IS NOT NULL"), {"c": TEMPLATE_KEY}).all()]


def _preflight_legacy_planos(bind):
    """Valida tenant de todo plano legado antes da primeira mutação.

    Tenant só é preenchido automaticamente quando inequívoco pelo
    Residente. Conflito (ilpi divergente, residente órfão ou sem
    instituicao) PARA a migration com diagnóstico — nunca inventa
    autor/revisor/aprovador para dados antigos.
    """
    institutions = set(bind.execute(sa.text("SELECT id FROM instituicoes")).scalars())
    residents = dict(bind.execute(sa.text("SELECT id, instituicao_id FROM residentes")).all())
    rows = bind.execute(sa.text("SELECT id, residente_id, ilpi_id, situacao FROM planos_cuidados")).mappings().all()
    resolved = []
    for row in rows:
        tenant = residents.get(row["residente_id"])
        if not tenant or tenant not in institutions:
            raise RuntimeError(f"013 plano {row['id']}: residente orfao ou sem tenant valido")
        if row["ilpi_id"] not in (None, tenant):
            raise RuntimeError(f"013 plano {row['id']}: tenant ambiguo (plano x residente)")
        resolved.append({"id": row["id"], "ilpi": tenant, "situacao": _normalize_state(row["situacao"])})
    return resolved


def _partial(name, table, columns, predicate):
    op.create_index(name, table, columns, unique=True,
                    sqlite_where=sa.text(predicate), postgresql_where=sa.text(predicate))


def _create_child_tables():
    op.create_table(
        "pais_necessidades",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("plano_id", sa.String(36), nullable=False),
        sa.Column("categoria", sa.String(100), nullable=True),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("gravidade", sa.String(50), nullable=True),
        sa.Column("evidencias", sa.Text(), nullable=True),
        sa.Column("origem", sa.String(50), nullable=False),
        sa.Column("situacao", sa.String(20), nullable=False, server_default="ativa"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["plano_id", "ilpi_id"], ["planos_cuidados.id", "planos_cuidados.ilpi_id"], name="fk_pais_necessidades_plano", ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "ilpi_id", "plano_id", name="uq_pais_necessidades_cadeia"),
        sa.CheckConstraint("origem IN ('manual','avaliacao','grau_dependencia','intercorrencia')", name="ck_pais_necessidades_origem"),
        sa.CheckConstraint("situacao IN ('ativa','inativa')", name="ck_pais_necessidades_situacao"),
    )
    op.create_index("ix_pais_necessidades_plano", "pais_necessidades", ["plano_id"])
    op.create_index("ix_pais_necessidades_ilpi_plano", "pais_necessidades", ["ilpi_id", "plano_id"])
    op.create_table(
        "pais_metas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("plano_id", sa.String(36), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("indicador", sa.String(255), nullable=True),
        sa.Column("valor_esperado", sa.String(255), nullable=True),
        sa.Column("prazo", sa.Date(), nullable=True),
        sa.Column("responsavel_funcionario_id", sa.String(36), sa.ForeignKey("funcionarios.id"), nullable=True),
        sa.Column("situacao", sa.String(20), nullable=False, server_default="ativa"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["plano_id", "ilpi_id"], ["planos_cuidados.id", "planos_cuidados.ilpi_id"], name="fk_pais_metas_plano", ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "ilpi_id", "plano_id", name="uq_pais_metas_cadeia"),
        sa.CheckConstraint("situacao IN ('ativa','inativa')", name="ck_pais_metas_situacao"),
    )
    op.create_index("ix_pais_metas_plano", "pais_metas", ["plano_id"])
    op.create_index("ix_pais_metas_ilpi_plano", "pais_metas", ["ilpi_id", "plano_id"])
    op.create_table(
        "pais_intervencoes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ilpi_id", sa.String(36), sa.ForeignKey("instituicoes.id"), nullable=False),
        sa.Column("plano_id", sa.String(36), nullable=False),
        sa.Column("necessidade_id", sa.String(36), sa.ForeignKey("pais_necessidades.id"), nullable=True),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("frequencia", sa.String(100), nullable=True),
        sa.Column("horario", sa.String(20), nullable=True),
        sa.Column("perfil_responsavel", sa.String(100), nullable=True),
        sa.Column("profissional_designado_id", sa.String(36), sa.ForeignKey("funcionarios.id"), nullable=True),
        sa.Column("prioridade", sa.String(20), nullable=True),
        sa.Column("instrucoes", sa.Text(), nullable=True),
        sa.Column("situacao", sa.String(20), nullable=False, server_default="ativa"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["plano_id", "ilpi_id"], ["planos_cuidados.id", "planos_cuidados.ilpi_id"], name="fk_pais_intervencoes_plano", ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "ilpi_id", "plano_id", name="uq_pais_intervencoes_cadeia"),
        sa.CheckConstraint("situacao IN ('ativa','inativa')", name="ck_pais_intervencoes_situacao"),
    )
    op.create_index("ix_pais_intervencoes_plano", "pais_intervencoes", ["plano_id"])
    op.create_index("ix_pais_intervencoes_ilpi_plano", "pais_intervencoes", ["ilpi_id", "plano_id"])
    op.create_index("ix_pais_intervencoes_necessidade", "pais_intervencoes", ["necessidade_id"])


def upgrade() -> None:
    bind = op.get_bind()
    _preflight_connection(bind)
    for permission in NEW_PERMISSIONS:
        rows = bind.execute(sa.text(
            "SELECT id, modulo, acao, chave, descricao FROM permissoes "
            "WHERE id = :id OR chave = :chave OR (modulo = :modulo AND acao = :acao)"
        ), {f: permission[f] for f in PERMISSION_FIELDS}).mappings().all()
        if rows and (len(rows) != 1 or dict(rows[0]) != {f: permission[f] for f in PERMISSION_FIELDS}):
            raise RuntimeError("013 conflito no catalogo de planos_cuidados")
    resolved = _preflight_legacy_planos(bind)

    # Every legacy row has been checked before the first mutation.
    for row in resolved:
        bind.execute(sa.text("UPDATE planos_cuidados SET ilpi_id = :ilpi, situacao = :situacao WHERE id = :id"), row)
    bind.execute(sa.text("UPDATE planos_cuidados SET versao = 1 WHERE versao IS NULL"))
    with op.batch_alter_table("planos_cuidados") as batch:
        batch.add_column(sa.Column("autor_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("revisor_funcionario_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("aprovador_funcionario_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("revisado_em", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("aprovado_em", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("motivo_encerramento", sa.Text(), nullable=True))
        batch.add_column(sa.Column("encerrado_em", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("anterior_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("motivo_versao", sa.Text(), nullable=True))
        batch.add_column(sa.Column("superseded_by", sa.String(36), nullable=True))
        batch.add_column(sa.Column("lock_version", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        batch.alter_column("ilpi_id", existing_type=sa.String(36), nullable=False)
        batch.alter_column("versao", existing_type=sa.Integer(), nullable=False, existing_nullable=True)
        batch.create_foreign_key("fk_planos_autor", "users", ["autor_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_planos_revisor", "funcionarios", ["revisor_funcionario_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_planos_aprovador", "funcionarios", ["aprovador_funcionario_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_planos_anterior", "planos_cuidados", ["anterior_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_planos_superseded", "planos_cuidados", ["superseded_by"], ["id"], ondelete="RESTRICT")
        batch.create_unique_constraint("uq_planos_id_ilpi", ["id", "ilpi_id"])
        batch.create_check_constraint("ck_planos_situacao", "situacao IN ('rascunho','em_elaboracao','em_revisao','aprovado','vigente','encerrado','substituido')")
        batch.create_index("ix_planos_ilpi_residente", ["ilpi_id", "residente_id"])
    _partial("uq_planos_vigente_por_residente", "planos_cuidados", ["residente_id"], "situacao = 'vigente'")

    _create_child_tables()

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
    for table in ("pais_necessidades", "pais_metas", "pais_intervencoes"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(f"013 recusa downgrade: historico em {table}")
    new_data = bind.execute(sa.text(
        "SELECT 1 FROM planos_cuidados WHERE autor_id IS NOT NULL "
        "OR revisor_funcionario_id IS NOT NULL OR aprovador_funcionario_id IS NOT NULL "
        "OR revisado_em IS NOT NULL OR aprovado_em IS NOT NULL "
        "OR motivo_encerramento IS NOT NULL OR encerrado_em IS NOT NULL "
        "OR anterior_id IS NOT NULL OR motivo_versao IS NOT NULL OR superseded_by IS NOT NULL "
        "OR lock_version <> 0 OR situacao NOT IN ('rascunho','Rascunho') LIMIT 1"
    )).first()
    if new_data is not None:
        raise RuntimeError("013 recusa downgrade: dados do PAIS sem representacao no schema antigo")

    permission_ids = [p["id"] for p in NEW_PERMISSIONS]
    for permission in NEW_PERMISSIONS:
        row = bind.execute(sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"), {"id": permission["id"]}).mappings().first()
        if row is not None:
            _assert_same_record(row, {f: permission[f] for f in PERMISSION_FIELDS}, PERMISSION_FIELDS, "permissao")
    allowed_profile_ids = set([_template_id(bind)] + _local_clone_ids(bind))
    external = bind.execute(sa.text("SELECT perfil_id, permissao_id FROM perfil_permissoes WHERE permissao_id IN :mids").bindparams(sa.bindparam("mids", expanding=True)), {"mids": permission_ids}).mappings().all()
    foreign = [(e["perfil_id"], e["permissao_id"]) for e in external if e["perfil_id"] not in allowed_profile_ids]
    if foreign:
        raise RuntimeError(f"013 recusa downgrade: vínculos externos às permissões: {sorted(foreign)}")
    for profile_id in allowed_profile_ids:
        for permission_id in permission_ids:
            bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"), {"p": profile_id, "m": permission_id})
    for permission_id in permission_ids:
        bind.execute(sa.text("DELETE FROM permissoes WHERE id = :id"), {"id": permission_id})

    op.drop_index("ix_pais_intervencoes_necessidade", table_name="pais_intervencoes")
    op.drop_index("ix_pais_intervencoes_ilpi_plano", table_name="pais_intervencoes")
    op.drop_index("ix_pais_intervencoes_plano", table_name="pais_intervencoes")
    op.drop_table("pais_intervencoes")
    op.drop_index("ix_pais_metas_ilpi_plano", table_name="pais_metas")
    op.drop_index("ix_pais_metas_plano", table_name="pais_metas")
    op.drop_table("pais_metas")
    op.drop_index("ix_pais_necessidades_ilpi_plano", table_name="pais_necessidades")
    op.drop_index("ix_pais_necessidades_plano", table_name="pais_necessidades")
    op.drop_table("pais_necessidades")

    op.drop_index("uq_planos_vigente_por_residente", table_name="planos_cuidados")
    with op.batch_alter_table("planos_cuidados") as batch:
        batch.drop_index("ix_planos_ilpi_residente")
        batch.drop_constraint("ck_planos_situacao", type_="check")
        batch.drop_constraint("uq_planos_id_ilpi", type_="unique")
        batch.drop_constraint("fk_planos_superseded", type_="foreignkey")
        batch.drop_constraint("fk_planos_anterior", type_="foreignkey")
        batch.drop_constraint("fk_planos_aprovador", type_="foreignkey")
        batch.drop_constraint("fk_planos_revisor", type_="foreignkey")
        batch.drop_constraint("fk_planos_autor", type_="foreignkey")
        batch.drop_column("updated_at")
        batch.drop_column("lock_version")
        batch.drop_column("superseded_by")
        batch.drop_column("motivo_versao")
        batch.drop_column("anterior_id")
        batch.drop_column("encerrado_em")
        batch.drop_column("motivo_encerramento")
        batch.drop_column("aprovado_em")
        batch.drop_column("revisado_em")
        batch.drop_column("aprovador_funcionario_id")
        batch.drop_column("revisor_funcionario_id")
        batch.drop_column("autor_id")
        batch.alter_column("ilpi_id", existing_type=sa.String(36), nullable=True)

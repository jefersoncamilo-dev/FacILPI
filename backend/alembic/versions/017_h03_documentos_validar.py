"""017_h03_documentos_validar: ato dedicado de validacao documental.

Fecha o bypass do PUT generico (DocumentoUpdate.situacao="validado" sem
autoria/timestamp/auditoria dedicados). Adiciona documentos.validado_por
(FK users.id, RESTRICT, nullable) e documentos.validado_em (nullable) para
compatibilidade com documentos legados ja validados antes desta coluna
existir. Adiciona a permissao ``documentos:validar`` ao catalogo, concede-a
ao template ``ilpi_admin`` e replica-a para os clones locais ``ilpi_admin``
ja existentes (casados por chave, nunca por UUID de tenant), seguindo o
mesmo padrao de 007_expandir_rbac_documentos. ``platform_superuser`` recebe
zero grants. Nenhuma migracao/inferencia de documentos legados.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "017_h03_documentos_validar"
down_revision: Union[str, None] = "016_d3_admissao"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATE_KEY = "ilpi_admin"

VALIDAR_PERMISSION = {
    "id": "fac11000-0000-4000-8000-000000000093",
    "chave": "documentos:validar",
    "modulo": "documentos",
    "acao": "validar",
    "descricao": "Validar documento da ILPI atual (ato dedicado, com autoria e auditoria).",
    "escopo_permitido": "ilpi",
}

PERMISSION_FIELDS = ("id", "modulo", "acao", "chave", "descricao")


def _assert_same_record(row, record, fields, label):
    differences = {f: (row[f], record[f]) for f in fields if row[f] != record[f]}
    if differences:
        raise RuntimeError(f"017 {label} adulterado: {differences}")


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
            raise RuntimeError(f"017 conflito de {label}: {dict(record)} colide com id {hit[0]}")


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
        raise RuntimeError("017 exige o template ilpi_admin da 004; execute as migrations em ordem")
    return row[0]


def _local_clone_ids(bind):
    return [r[0] for r in bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c AND ilpi_id IS NOT NULL"), {"c": TEMPLATE_KEY}).all()]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT id FROM permissoes WHERE chave = 'documentos:validar'")).first():
        raise RuntimeError("017 recusa catalogo de documentos:validar preexistente")

    op.add_column("documentos", sa.Column("validado_por", sa.String(36), nullable=True))
    op.add_column("documentos", sa.Column("validado_em", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("documentos") as batch_op:
        batch_op.create_foreign_key(
            "fk_documentos_validado_por", "users", ["validado_por"], ["id"], ondelete="RESTRICT"
        )

    permission_id = _ensure_permission(bind, VALIDAR_PERMISSION)
    template_id = _template_id(bind)
    _ensure_link(bind, template_id, permission_id)
    for clone_id in _local_clone_ids(bind):
        _ensure_link(bind, clone_id, permission_id)


def downgrade() -> None:
    bind = op.get_bind()

    if bind.execute(sa.text("SELECT 1 FROM documentos WHERE validado_por IS NOT NULL")).first():
        raise RuntimeError("017 recusa downgrade: existe evidencia de validacao (documentos.validado_por preenchido)")

    row = bind.execute(sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"), {"id": VALIDAR_PERMISSION["id"]}).mappings().first()
    if row is not None:
        _assert_same_record(row, {f: VALIDAR_PERMISSION[f] for f in PERMISSION_FIELDS}, PERMISSION_FIELDS, "permissao")
        allowed_profile_ids = set([_template_id(bind)] + _local_clone_ids(bind))
        external = bind.execute(
            sa.text("SELECT perfil_id FROM perfil_permissoes WHERE permissao_id = :m"), {"m": VALIDAR_PERMISSION["id"]}
        ).all()
        foreign = [e[0] for e in external if e[0] not in allowed_profile_ids]
        if foreign:
            raise RuntimeError(f"017 recusa downgrade: vinculos externos a documentos:validar: {sorted(foreign)}")
        for profile_id in allowed_profile_ids:
            bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"), {"p": profile_id, "m": VALIDAR_PERMISSION["id"]})
        bind.execute(sa.text("DELETE FROM permissoes WHERE id = :id"), {"id": VALIDAR_PERMISSION["id"]})

    with op.batch_alter_table("documentos") as batch_op:
        batch_op.drop_constraint("fk_documentos_validado_por", type_="foreignkey")
        batch_op.drop_column("validado_em")
        batch_op.drop_column("validado_por")

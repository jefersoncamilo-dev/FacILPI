"""007_expandir_rbac_documentos: permissões documentos (RBAC-only).

Adiciona 4 permissões do módulo ``documentos`` ao catálogo, concede-as ao
template ``ilpi_admin`` e replica-as para os clones locais ``ilpi_admin``
já existentes (casados por chave, nunca por UUID de tenant). Clones futuros
herdam via ``_clone_ilpi_admin_profile`` sem alteração de código.
``platform_superuser`` recebe zero grants de documentos. Nenhum DDL de
documento, nenhum seed de dados, nenhum dado de homologação.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "007_expandir_rbac_documentos"
down_revision: Union[str, None] = "006_catalogo_clinico_rbac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATE_KEY = "ilpi_admin"

DOCUMENT_PERMISSIONS = (
    {"id": "fac11000-0000-4000-8000-000000000041", "chave": "documentos:ler", "modulo": "documentos", "acao": "ler", "descricao": "Consultar documentos da ILPI atual.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000042", "chave": "documentos:criar", "modulo": "documentos", "acao": "criar", "descricao": "Criar documento vinculado a residente da ILPI atual.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000043", "chave": "documentos:atualizar", "modulo": "documentos", "acao": "atualizar", "descricao": "Atualizar dados permitidos do documento.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000044", "chave": "documentos:inativar", "modulo": "documentos", "acao": "inativar", "descricao": "Inativar documento preservando o histórico.", "escopo_permitido": "ilpi"},
)

PERMISSION_FIELDS = ("id", "modulo", "acao", "chave", "descricao")


def _assert_same_record(row, record, fields, label):
    differences = {f: (row[f], record[f]) for f in fields if row[f] != record[f]}
    if differences:
        raise RuntimeError(f"007 {label} adulterado: {differences}")


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
            raise RuntimeError(f"007 conflito de {label}: {dict(record)} colide com id {hit[0]}")


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
        raise RuntimeError("007 exige o template ilpi_admin da 004; execute as migrations em ordem")
    return row[0]


def _local_clone_ids(bind):
    return [r[0] for r in bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c AND ilpi_id IS NOT NULL"), {"c": TEMPLATE_KEY}).all()]


def upgrade() -> None:
    bind = op.get_bind()
    permission_ids = [_ensure_permission(bind, permission) for permission in DOCUMENT_PERMISSIONS]
    template_id = _template_id(bind)
    for permission_id in permission_ids:
        _ensure_link(bind, template_id, permission_id)
    for clone_id in _local_clone_ids(bind):
        for permission_id in permission_ids:
            _ensure_link(bind, clone_id, permission_id)


def downgrade() -> None:
    bind = op.get_bind()
    permission_ids = [p["id"] for p in DOCUMENT_PERMISSIONS]
    for permission in DOCUMENT_PERMISSIONS:
        row = bind.execute(sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"), {"id": permission["id"]}).mappings().first()
        if row is not None:
            _assert_same_record(row, {f: permission[f] for f in PERMISSION_FIELDS}, PERMISSION_FIELDS, "permissao")
    allowed_profile_ids = set([_template_id(bind)] + _local_clone_ids(bind))
    external = bind.execute(sa.text("SELECT perfil_id, permissao_id FROM perfil_permissoes WHERE permissao_id IN :mids").bindparams(sa.bindparam("mids", expanding=True)), {"mids": permission_ids}).mappings().all()
    foreign = [(e["perfil_id"], e["permissao_id"]) for e in external if e["perfil_id"] not in allowed_profile_ids]
    if foreign:
        raise RuntimeError(f"007 recusa downgrade: vínculos externos às permissões de documentos: {sorted(foreign)}")
    for profile_id in allowed_profile_ids:
        for permission_id in permission_ids:
            bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"), {"p": profile_id, "m": permission_id})
    for permission_id in permission_ids:
        bind.execute(sa.text("DELETE FROM permissoes WHERE id = :id"), {"id": permission_id})

"""006_catalogo_clinico_rbac: permissÃµes clÃ­nicas mÃ­nimas (RBAC-only).

Adiciona 14 permissÃµes clÃ­nicas ao catÃ¡logo, concede-as ao template
``ilpi_admin`` e replica-as para os clones locais ``ilpi_admin`` jÃ¡
existentes (casados por chave, nunca por UUID de tenant). Clones futuros
herdam via ``_clone_ilpi_admin_profile`` sem alteraÃ§Ã£o de cÃ³digo.
``platform_superuser`` recebe zero grants clÃ­nicos. Nenhum DDL clÃ­nico,
nenhum seed de dados, nenhum dado de homologaÃ§Ã£o.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "006_catalogo_clinico_rbac"
down_revision: Union[str, None] = "005_fase3a_bootstrap_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATE_KEY = "ilpi_admin"

CLINICAL_PERMISSIONS = (
    {"id": "fac11000-0000-4000-8000-000000000027", "chave": "residentes:ler", "modulo": "residentes", "acao": "ler", "descricao": "Consultar residentes da ILPI atual.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000028", "chave": "residentes:criar", "modulo": "residentes", "acao": "criar", "descricao": "Cadastrar residente na ILPI atual.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000029", "chave": "residentes:atualizar", "modulo": "residentes", "acao": "atualizar", "descricao": "Atualizar dados permitidos do residente.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000030", "chave": "residentes:inativar", "modulo": "residentes", "acao": "inativar", "descricao": "Inativar residente preservando prontuÃ¡rio e histÃ³rico.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000031", "chave": "familiares:ler", "modulo": "familiares", "acao": "ler", "descricao": "Consultar familiares da ILPI atual.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000032", "chave": "familiares:criar", "modulo": "familiares", "acao": "criar", "descricao": "Cadastrar familiar vinculado a residente da ILPI atual.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000033", "chave": "familiares:atualizar", "modulo": "familiares", "acao": "atualizar", "descricao": "Atualizar dados permitidos do familiar.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000034", "chave": "familiares:inativar", "modulo": "familiares", "acao": "inativar", "descricao": "Inativar familiar preservando o histÃ³rico.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000035", "chave": "tarefas:ler", "modulo": "tarefas", "acao": "ler", "descricao": "Consultar tarefas da ILPI atual.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000036", "chave": "tarefas:criar", "modulo": "tarefas", "acao": "criar", "descricao": "Criar tarefa vinculada a residente da ILPI atual.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000037", "chave": "tarefas:atualizar", "modulo": "tarefas", "acao": "atualizar", "descricao": "Atualizar e transitar a situaÃ§Ã£o da tarefa com justificativa quando exigida.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000038", "chave": "tarefas:inativar", "modulo": "tarefas", "acao": "inativar", "descricao": "Cancelar ou inativar tarefa preservando o histÃ³rico.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000039", "chave": "sinais_vitais:ler", "modulo": "sinais_vitais", "acao": "ler", "descricao": "Consultar sinais vitais de residentes da ILPI atual.", "escopo_permitido": "ilpi"},
    {"id": "fac11000-0000-4000-8000-000000000040", "chave": "sinais_vitais:criar", "modulo": "sinais_vitais", "acao": "criar", "descricao": "Registrar sinais vitais de residente da ILPI atual.", "escopo_permitido": "ilpi"},
)

PERMISSION_FIELDS = ("id", "modulo", "acao", "chave", "descricao")


def _assert_same_record(row, record, fields, label):
    differences = {f: (row[f], record[f]) for f in fields if row[f] != record[f]}
    if differences:
        raise RuntimeError(f"006 {label} adulterado: {differences}")


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
            raise RuntimeError(f"006 conflito de {label}: {dict(record)} colide com id {hit[0]}")


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
        raise RuntimeError("006 exige o template ilpi_admin da 004; execute as migrations em ordem")
    return row[0]


def _local_clone_ids(bind):
    return [r[0] for r in bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c AND ilpi_id IS NOT NULL"), {"c": TEMPLATE_KEY}).all()]


def upgrade() -> None:
    bind = op.get_bind()
    permission_ids = [_ensure_permission(bind, permission) for permission in CLINICAL_PERMISSIONS]
    template_id = _template_id(bind)
    for permission_id in permission_ids:
        _ensure_link(bind, template_id, permission_id)
    for clone_id in _local_clone_ids(bind):
        for permission_id in permission_ids:
            _ensure_link(bind, clone_id, permission_id)


def downgrade() -> None:
    bind = op.get_bind()
    permission_ids = [p["id"] for p in CLINICAL_PERMISSIONS]
    for permission in CLINICAL_PERMISSIONS:
        row = bind.execute(sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"), {"id": permission["id"]}).mappings().first()
        if row is not None:
            _assert_same_record(row, {f: permission[f] for f in PERMISSION_FIELDS}, PERMISSION_FIELDS, "permissao")
    allowed_profile_ids = set([_template_id(bind)] + _local_clone_ids(bind))
    external = bind.execute(sa.text("SELECT perfil_id, permissao_id FROM perfil_permissoes WHERE permissao_id IN :mids").bindparams(sa.bindparam("mids", expanding=True)), {"mids": permission_ids}).mappings().all()
    foreign = [(e["perfil_id"], e["permissao_id"]) for e in external if e["perfil_id"] not in allowed_profile_ids]
    if foreign:
        raise RuntimeError(f"006 recusa downgrade: vÃ­nculos externos Ã s permissÃµes clÃ­nicas: {sorted(foreign)}")
    for profile_id in allowed_profile_ids:
        for permission_id in permission_ids:
            bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"), {"p": profile_id, "m": permission_id})
    for permission_id in permission_ids:
        bind.execute(sa.text("DELETE FROM permissoes WHERE id = :id"), {"id": permission_id})
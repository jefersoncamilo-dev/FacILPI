"""018_a3_documentos_arquivo: anexo seguro de arquivo em documentos (Issue #45).

Substitui o upload generico ``POST /uploads/{entity_id}`` por ato dedicado
``POST /documentos/{id}/arquivo``. Adiciona a permissao ``documentos:anexar``
e os metadados do arquivo em ``documentos``.

A coluna historica ``arquivo`` NAO e removida: passa a representar
exclusivamente uma CHAVE RELATIVA controlada pelo backend
(``<ilpi_id>/<documento_id>/<uuid>.<ext>``), nunca caminho absoluto e nunca
definida pelo cliente.

Grants: apenas o template ``ilpi_admin`` e seus clones locais, casados por
chave e nunca por UUID de tenant — mesmo padrao de 007 e 017. Os perfis da
matriz S.1 (015) nao sao tocados: a 015 recusa downgrade quando encontra
"grants customizados em perfil institucional", e a matriz institucional
permite conceder ``documentos:anexar`` em runtime sem nova migration.
``platform_superuser`` recebe zero grants.

Nenhuma migracao/inferencia de documentos legados: o discovery da Issue #45
confirmou zero arquivos enviados e zero linhas com ``arquivo`` preenchido.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "018_a3_documentos_arquivo"
down_revision: Union[str, None] = "017_h03_documentos_validar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATE_KEY = "ilpi_admin"

ANEXAR_PERMISSION = {
    "id": "fac11000-0000-4000-8000-000000000094",
    "chave": "documentos:anexar",
    "modulo": "documentos",
    "acao": "anexar",
    "descricao": "Anexar arquivo a documento da ILPI atual (ato dedicado, com autoria e auditoria).",
    "escopo_permitido": "ilpi",
}

PERMISSION_FIELDS = ("id", "modulo", "acao", "chave", "descricao")

# Metadados do anexo. Todos nullable: documento sem arquivo e estado valido.
ARQUIVO_COLUMNS = (
    ("arquivo_nome_original", sa.String(255)),
    ("arquivo_mime", sa.String(127)),
    ("arquivo_tamanho", sa.Integer()),
    ("arquivo_hash", sa.String(64)),
    ("anexado_por", sa.String(36)),
    ("anexado_em", sa.DateTime(timezone=True)),
)


def _assert_same_record(row, record, fields, label):
    differences = {f: (row[f], record[f]) for f in fields if row[f] != record[f]}
    if differences:
        raise RuntimeError(f"018 {label} adulterado: {differences}")


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
            raise RuntimeError(f"018 conflito de {label}: {dict(record)} colide com id {hit[0]}")


def _ensure_permission(bind, permission):
    record = {f: permission[f] for f in PERMISSION_FIELDS}
    row = bind.execute(
        sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"),
        {"id": record["id"]},
    ).mappings().first()
    if row is not None:
        _assert_same_record(row, record, PERMISSION_FIELDS, "permissao")
        _assert_no_unique_conflicts(bind, "permissoes", record, (("chave",), ("modulo", "acao")), "permissao", exclude_id=record["id"])
        return record["id"]
    _assert_no_unique_conflicts(bind, "permissoes", record, (("chave",), ("modulo", "acao")), "permissao")
    bind.execute(
        sa.text("INSERT INTO permissoes (id, modulo, acao, chave, descricao) VALUES (:id, :modulo, :acao, :chave, :descricao)"),
        record,
    )
    return record["id"]


def _ensure_link(bind, profile_id, permission_id):
    exists = bind.execute(
        sa.text("SELECT 1 FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"),
        {"p": profile_id, "m": permission_id},
    ).first()
    if exists is None:
        bind.execute(
            sa.text("INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:p, :m)"),
            {"p": profile_id, "m": permission_id},
        )


def _template_id(bind):
    row = bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c AND ilpi_id IS NULL"), {"c": TEMPLATE_KEY}).first()
    if row is None:
        raise RuntimeError("018 exige o template ilpi_admin da 004; execute as migrations em ordem")
    return row[0]


def _local_clone_ids(bind):
    return [r[0] for r in bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c AND ilpi_id IS NOT NULL"), {"c": TEMPLATE_KEY}).all()]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT id FROM permissoes WHERE chave = 'documentos:anexar'")).first():
        raise RuntimeError("018 recusa catalogo de documentos:anexar preexistente")

    for name, type_ in ARQUIVO_COLUMNS:
        op.add_column("documentos", sa.Column(name, type_, nullable=True))
    with op.batch_alter_table("documentos") as batch_op:
        batch_op.create_foreign_key(
            "fk_documentos_anexado_por", "users", ["anexado_por"], ["id"], ondelete="RESTRICT"
        )
    # Busca por hash serve deduplicacao e auditoria; nao e unique porque o mesmo
    # conteudo pode legitimamente existir em ILPIs diferentes.
    op.create_index("ix_documentos_arquivo_hash", "documentos", ["arquivo_hash"])

    permission_id = _ensure_permission(bind, ANEXAR_PERMISSION)
    template_id = _template_id(bind)
    _ensure_link(bind, template_id, permission_id)
    for clone_id in _local_clone_ids(bind):
        _ensure_link(bind, clone_id, permission_id)


def downgrade() -> None:
    bind = op.get_bind()

    # Mesma politica da 017: evidencia de ato humano nao e apagada em silencio.
    if bind.execute(sa.text("SELECT 1 FROM documentos WHERE anexado_por IS NOT NULL")).first():
        raise RuntimeError("018 recusa downgrade: existe evidencia de anexo (documentos.anexado_por preenchido)")

    row = bind.execute(
        sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"),
        {"id": ANEXAR_PERMISSION["id"]},
    ).mappings().first()
    if row is not None:
        _assert_same_record(row, {f: ANEXAR_PERMISSION[f] for f in PERMISSION_FIELDS}, PERMISSION_FIELDS, "permissao")
        allowed_profile_ids = set([_template_id(bind)] + _local_clone_ids(bind))
        external = bind.execute(
            sa.text("SELECT perfil_id FROM perfil_permissoes WHERE permissao_id = :m"), {"m": ANEXAR_PERMISSION["id"]}
        ).all()
        foreign = [e[0] for e in external if e[0] not in allowed_profile_ids]
        if foreign:
            raise RuntimeError(f"018 recusa downgrade: vinculos externos a documentos:anexar: {sorted(foreign)}")
        for profile_id in allowed_profile_ids:
            bind.execute(
                sa.text("DELETE FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"),
                {"p": profile_id, "m": ANEXAR_PERMISSION["id"]},
            )
        bind.execute(sa.text("DELETE FROM permissoes WHERE id = :id"), {"id": ANEXAR_PERMISSION["id"]})

    op.drop_index("ix_documentos_arquivo_hash", table_name="documentos")
    with op.batch_alter_table("documentos") as batch_op:
        batch_op.drop_constraint("fk_documentos_anexado_por", type_="foreignkey")
        for name, _ in reversed(ARQUIVO_COLUMNS):
            batch_op.drop_column(name)

"""022_alertas_gestor: central de alertas do Administrador da ILPI (#107).

Os alertas sao PROJECAO: calculados na hora a partir das fontes oficiais
(admissoes, documentos, avaliacoes, grau, PAIS, plantao, intercorrencias,
leitos, ausencias, equipe) e somem quando o problema e resolvido na fonte.
Nenhuma tabela nova; a tabela legada ``alertas`` da 001 e o CRUD
``fail_closed`` de /api/alertas/ ficam intocados.

Esta migration so cria a permissao ``alertas:ler`` e a concede ao template
``ilpi_admin`` e aos clones locais ja existentes (casados por chave, nunca
por UUID de tenant) — mesmo padrao da 017. Decisao do responsavel (26/09):
so o Administrador da ILPI recebe alertas; os perfis institucionais da 015
seguem sem ela, e ``alertas`` continua modulo clinico (fora do catalogo
local), entao o gestor nao a repassa a perfis locais.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "022_alertas_gestor"
down_revision: Union[str, None] = "021_admissoes_ilpi_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATE_KEY = "ilpi_admin"

LER_PERMISSION = {
    "id": "fac11000-0000-4000-8000-000000000095",
    "chave": "alertas:ler",
    "modulo": "alertas",
    "acao": "ler",
    "descricao": "Ver os alertas derivados da ILPI atual (projecao somente leitura).",
}

PERMISSION_FIELDS = ("id", "modulo", "acao", "chave", "descricao")


def _assert_same_record(row, record):
    differences = {f: (row[f], record[f]) for f in PERMISSION_FIELDS if row[f] != record[f]}
    if differences:
        raise RuntimeError(f"022 permissao adulterada: {differences}")


def _template_id(bind):
    row = bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c AND ilpi_id IS NULL"), {"c": TEMPLATE_KEY}).first()
    if row is None:
        raise RuntimeError("022 exige o template ilpi_admin da 004; execute as migrations em ordem")
    return row[0]


def _local_clone_ids(bind):
    return [r[0] for r in bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c AND ilpi_id IS NOT NULL"), {"c": TEMPLATE_KEY}).all()]


def _ensure_permission(bind):
    row = bind.execute(
        sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"), {"id": LER_PERMISSION["id"]}
    ).mappings().first()
    if row is not None:
        _assert_same_record(row, LER_PERMISSION)
        return
    conflito = bind.execute(
        sa.text("SELECT id FROM permissoes WHERE chave = :chave OR (modulo = :modulo AND acao = :acao)"),
        {k: LER_PERMISSION[k] for k in ("chave", "modulo", "acao")},
    ).first()
    if conflito is not None:
        raise RuntimeError(f"022 recusa catalogo de alertas:ler preexistente (id {conflito[0]})")
    bind.execute(
        sa.text("INSERT INTO permissoes (id, modulo, acao, chave, descricao) VALUES (:id, :modulo, :acao, :chave, :descricao)"),
        LER_PERMISSION,
    )


def _ensure_link(bind, profile_id):
    exists = bind.execute(
        sa.text("SELECT 1 FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"),
        {"p": profile_id, "m": LER_PERMISSION["id"]},
    ).first()
    if exists is None:
        bind.execute(
            sa.text("INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:p, :m)"),
            {"p": profile_id, "m": LER_PERMISSION["id"]},
        )


def upgrade() -> None:
    bind = op.get_bind()
    _ensure_permission(bind)
    for profile_id in [_template_id(bind)] + _local_clone_ids(bind):
        _ensure_link(bind, profile_id)


def downgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"), {"id": LER_PERMISSION["id"]}
    ).mappings().first()
    if row is None:
        return
    _assert_same_record(row, LER_PERMISSION)
    permitidos = set([_template_id(bind)] + _local_clone_ids(bind))
    vinculos = bind.execute(
        sa.text("SELECT perfil_id FROM perfil_permissoes WHERE permissao_id = :m"), {"m": LER_PERMISSION["id"]}
    ).all()
    externos = sorted(v[0] for v in vinculos if v[0] not in permitidos)
    if externos:
        raise RuntimeError(f"022 recusa downgrade: vinculos externos a alertas:ler: {externos}")
    bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE permissao_id = :m"), {"m": LER_PERMISSION["id"]})
    bind.execute(sa.text("DELETE FROM permissoes WHERE id = :id"), {"id": LER_PERMISSION["id"]})

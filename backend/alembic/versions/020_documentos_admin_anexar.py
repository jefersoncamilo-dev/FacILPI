"""020_documentos_admin_anexar: emenda S.1 do perfil administrativo.

O fluxo documental estava partido: o perfil institucional ``administrativo``
tem ``documentos:criar`` desde a 015, mas nao consegue anexar o arquivo ao
documento que acabou de criar. A lacuna nao foi esquecimento — quando a 015
criou o perfil, ``documentos:anexar`` nem existia; ela nasceu na 018, que
deliberadamente concedeu apenas ao template ``ilpi_admin``.

Esta migration concede EXCLUSIVAMENTE ``documentos:anexar`` ao template
``administrativo`` e aos seus clones locais. Nada mais: ``documentos:validar``
e ``documentos:inativar`` seguem restritas ao ``ilpi_admin``, e
``responsavel_tecnico`` nao e tocado.

Nenhuma permissao de catalogo e criada — ``documentos:anexar`` existe desde a
018. O catalogo permanece em 94.

Os clones entram junto porque ``_ensure_clone`` (matriz.py:57-71) copia as
permissoes do template NO MOMENTO em que o clone e criado; clone existente nao
recebe mudanca posterior de template. Tocar so o template deixaria as ILPIs ja
provisionadas sem a capacidade.

O downgrade remove exatamente o vinculo concedido aqui. E obrigatorio, nao
cosmetico: a 018 recusa downgrade quando encontra "vinculos externos a
documentos:anexar" e a 015 recusa quando o conjunto de grants de um perfil
institucional difere do que ela criou. Sem esta limpeza, ambas travariam.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "020_documentos_admin_anexar"
down_revision: Union[str, None] = "019_b1_intercorrencias_ocorrido"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATE_KEY = "administrativo"

# Ja existente na 018. Esta migration concede vinculo; nao cria catalogo.
ANEXAR_PERMISSION = {
    "id": "fac11000-0000-4000-8000-000000000094",
    "chave": "documentos:anexar",
}

# Permanecem FORA do administrativo, por decisao explicita.
NAO_CONCEDIDAS = ("documentos:validar", "documentos:inativar")


def _permission_id(bind):
    """A permissao precisa vir da 018, com id e chave casando."""
    row = bind.execute(
        sa.text("SELECT chave FROM permissoes WHERE id = :id"), {"id": ANEXAR_PERMISSION["id"]}
    ).first()
    if row is None:
        raise RuntimeError("020 exige a permissao documentos:anexar da 018; execute as migrations em ordem")
    if row[0] != ANEXAR_PERMISSION["chave"]:
        raise RuntimeError(
            f"020 catalogo adulterado: {ANEXAR_PERMISSION['id']} deveria ser "
            f"{ANEXAR_PERMISSION['chave']}, e {row[0]}"
        )
    return ANEXAR_PERMISSION["id"]


def _profile_ids(bind):
    """Template institucional de administrativo mais os clones locais.

    Casamento por chave, nunca por UUID de tenant — mesmo padrao de 007/017/018/019.
    """
    rows = bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c"), {"c": TEMPLATE_KEY}).all()
    if not rows:
        raise RuntimeError("020 exige o template administrativo da 015; execute as migrations em ordem")
    return [r[0] for r in rows]


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


def upgrade() -> None:
    bind = op.get_bind()
    permission_id = _permission_id(bind)
    for profile_id in _profile_ids(bind):
        _ensure_link(bind, profile_id, permission_id)


def downgrade() -> None:
    bind = op.get_bind()
    # Remove somente o que a 020 concedeu, e somente em perfis `administrativo`.
    # Vinculo em perfil que nao e administrativo nao pertence a esta migration:
    # apaga-lo seria destruir decisao de outra origem.
    for profile_id in _profile_ids(bind):
        bind.execute(
            sa.text("DELETE FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"),
            {"p": profile_id, "m": ANEXAR_PERMISSION["id"]},
        )

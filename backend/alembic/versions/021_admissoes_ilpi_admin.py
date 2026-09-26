"""021_admissoes_ilpi_admin: o Administrador da ILPI conduz admissões (#103).

A 016 criou ``admissoes:*`` sem grants, prevendo atribuição explícita S.1.
Nenhum perfil-modelo recebeu essas permissões, e o gestor não consegue
concedê-las (Admissões é módulo clínico, fora do catálogo local, e a S.1
barra escalada). Em ambiente real ninguém conduzia admissão — achado ao
preparar a demonstração no ambiente publicado (26/09).

Decisão do responsável (26/09): o Administrador da ILPI conduz admissões.
Esta migration concede as 7 permissões ``admissoes:*`` ao template
``ilpi_admin`` e aos seus clones locais. Nada mais: os perfis institucionais
da 015 (cuidador, enfermagem, medico, responsavel_tecnico, administrativo)
seguem sem admissões, e nenhuma permissão de catálogo é criada.

Os clones entram junto porque o clone copia as permissões do template no
momento em que é criado (``_clone_ilpi_admin_profile``); clone existente não
recebe mudança posterior de template — mesmo motivo da 020.

O downgrade remove exatamente os vínculos de ``admissoes:*`` dos perfis
``ilpi_admin``. É obrigatório: a 016 recusa downgrade quando encontra grants
de admissões.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "021_admissoes_ilpi_admin"
down_revision: Union[str, None] = "020_documentos_admin_anexar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATE_KEY = "ilpi_admin"
ACOES = ("ler", "criar", "atualizar", "avancar", "reabrir", "concluir", "cancelar")


def _permission_ids(bind):
    """As 7 permissões precisam vir da 016, com as chaves esperadas."""
    rows = bind.execute(sa.text("SELECT id, chave FROM permissoes WHERE modulo = 'admissoes'")).all()
    chaves = {r[1] for r in rows}
    esperadas = {f"admissoes:{a}" for a in ACOES}
    if not rows:
        raise RuntimeError("021 exige as permissoes admissoes:* da 016; execute as migrations em ordem")
    if chaves != esperadas:
        raise RuntimeError(f"021 catalogo de admissoes adulterado: {sorted(chaves)}")
    return [r[0] for r in rows]


def _profile_ids(bind):
    """Template ilpi_admin (ilpi_id nulo) mais os clones locais, por chave."""
    rows = bind.execute(sa.text("SELECT id FROM perfis WHERE chave = :c"), {"c": TEMPLATE_KEY}).all()
    if not rows:
        raise RuntimeError("021 exige o template ilpi_admin; execute as migrations em ordem")
    return [r[0] for r in rows]


def upgrade() -> None:
    bind = op.get_bind()
    permissoes = _permission_ids(bind)
    for perfil in _profile_ids(bind):
        for permissao in permissoes:
            existe = bind.execute(
                sa.text("SELECT 1 FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"),
                {"p": perfil, "m": permissao},
            ).first()
            if existe is None:
                bind.execute(
                    sa.text("INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:p, :m)"),
                    {"p": perfil, "m": permissao},
                )


def downgrade() -> None:
    bind = op.get_bind()
    permissoes = _permission_ids(bind)
    for perfil in _profile_ids(bind):
        for permissao in permissoes:
            bind.execute(
                sa.text("DELETE FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"),
                {"p": perfil, "m": permissao},
            )

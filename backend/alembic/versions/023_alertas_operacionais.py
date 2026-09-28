"""023_alertas_operacionais: alertas para os perfis operacionais (#117).

Camada Operacional, Fase 1 (ROADMAP §16). A 022 criou ``alertas:ler`` so para
o Administrador da ILPI. Decisao do responsavel (28/09): os perfis
institucionais da 015 (cuidador, enfermagem, medico, responsavel_tecnico,
administrativo) tambem recebem a central. Ter ``alertas:ler`` nao abre todos
os alertas: cada regra continua exigindo a leitura do modulo de origem
(RBAC por origem, ``application/alertas.py``).

Concede ao template (``ilpi_id`` nulo) e aos clones locais ja existentes,
casados por chave, nunca por UUID de tenant: clone existente nao recebe
mudanca posterior de template (mesmo motivo da 020/021/022). Nenhuma
permissao nova e criada. ``platform_superuser`` nao e tocado.

O downgrade remove exatamente estes vinculos. E obrigatorio: o downgrade da
022 recusa vinculos de ``alertas:ler`` fora de ``ilpi_admin`` e o da 015
recusa grants customizados nos templates institucionais.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "023_alertas_operacionais"
down_revision: Union[str, None] = "022_alertas_gestor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHAVE = "alertas:ler"
PERFIS = ("cuidador", "enfermagem", "medico", "responsavel_tecnico", "administrativo")


def _permission_ids(bind):
    """A permissao precisa vir da 022, com a chave esperada."""
    rows = bind.execute(sa.text("SELECT id FROM permissoes WHERE chave = :c"), {"c": CHAVE}).all()
    if not rows:
        raise RuntimeError("023 exige alertas:ler da 022; execute as migrations em ordem")
    return [r[0] for r in rows]


def _profile_ids(bind):
    """Templates institucionais da 015 (ilpi_id nulo) mais os clones locais, por chave."""
    rows = bind.execute(
        sa.text("SELECT id, chave, ilpi_id FROM perfis WHERE chave IN :chaves").bindparams(sa.bindparam("chaves", expanding=True)),
        {"chaves": list(PERFIS)},
    ).all()
    templates = {r[1] for r in rows if r[2] is None}
    if templates != set(PERFIS):
        raise RuntimeError(f"023 exige os templates institucionais da 015; ausentes: {sorted(set(PERFIS) - templates)}")
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

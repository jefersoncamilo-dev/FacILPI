"""C.4: grant minimal Intercorrencias RBAC; no clinical data or DDL changes.

Baseline catalog/admin/platform: 56/52/15 -> 59/55/15.
Existing ilpi_admin clones receive the same three grants as the template.
"""

from alembic import op
import sqlalchemy as sa

revision = "011_f5a4a_intercorrencias_rbac"
down_revision = "010_f5a3a2_grau_dependencia"
branch_labels = None
depends_on = None

NEW_PERMISSIONS = (
    {"id": "fac11000-0000-4000-8000-000000000057", "modulo": "intercorrencias", "acao": "ler", "chave": "intercorrencias:ler", "descricao": "Consultar intercorrencias da ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000058", "modulo": "intercorrencias", "acao": "criar", "chave": "intercorrencias:criar", "descricao": "Criar intercorrencia na ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000059", "modulo": "intercorrencias", "acao": "atualizar", "chave": "intercorrencias:atualizar", "descricao": "Corrigir intercorrencia aberta ou encerra-la explicitamente na ILPI atual."},
)


def _profiles(bind):
    rows = bind.execute(sa.text(
        "SELECT id, ilpi_id FROM perfis WHERE chave = 'ilpi_admin' AND escopo = 'ilpi'"
    )).mappings().all()
    if not any(row["ilpi_id"] is None for row in rows):
        raise RuntimeError("011 exige o template ilpi_admin")
    return [row["id"] for row in rows]


def upgrade():
    bind = op.get_bind()
    profiles = _profiles(bind)
    for permission in NEW_PERMISSIONS:
        existing = bind.execute(sa.text(
            "SELECT id, modulo, acao, chave, descricao FROM permissoes "
            "WHERE id = :id OR chave = :chave OR (modulo = :modulo AND acao = :acao)"
        ), permission).mappings().all()
        if existing and (len(existing) != 1 or dict(existing[0]) != permission):
            raise RuntimeError("011 conflito no catalogo de intercorrencias")
        if not existing:
            bind.execute(sa.text(
                "INSERT INTO permissoes (id, modulo, acao, chave, descricao) "
                "VALUES (:id, :modulo, :acao, :chave, :descricao)"
            ), permission)
        for profile_id in profiles:
            params = {"p": profile_id, "m": permission["id"]}
            if not bind.execute(sa.text(
                "SELECT 1 FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"
            ), params).first():
                bind.execute(sa.text(
                    "INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:p, :m)"
                ), params)


def downgrade():
    bind = op.get_bind()
    profiles = set(_profiles(bind))
    # Validate every permission/link before removing anything.
    for permission in NEW_PERMISSIONS:
        row = bind.execute(sa.text(
            "SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"
        ), permission).mappings().first()
        if row is not None and dict(row) != permission:
            raise RuntimeError("011 catalogo adulterado")
        links = bind.execute(sa.text(
            "SELECT perfil_id FROM perfil_permissoes WHERE permissao_id = :id"
        ), permission).scalars().all()
        if set(links) - profiles:
            raise RuntimeError("011 recusa downgrade: vinculos externos as permissoes")
    for permission in NEW_PERMISSIONS:
        bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE permissao_id = :id"), permission)
        bind.execute(sa.text("DELETE FROM permissoes WHERE id = :id"), permission)

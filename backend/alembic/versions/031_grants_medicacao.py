"""031 — grants de medicacao (M10, D1).

D1 (24/10/2026): enfermagem e responsavel_tecnico cadastram medicamento e
transcrevem receita externa (``medicamentos:criar/atualizar`` e
``prescricoes:criar/atualizar``). O medico mantem ``prescricoes:*`` concedido
antes; cuidador e ilpi_admin nao recebem. Templates e clones por chave;
profissao nao concede.

O catalogo pertence a 012: aqui so e validado (recusa ausencia ou adulteracao).
Downgrade recusa vinculos externos e remove so os vinculos desta migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "031_grants_medicacao"
down_revision: Union[str, None] = "030_saida_residente"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSOES = (
    {"id": "fac11000-0000-4000-8000-000000000061", "chave": "medicamentos:criar", "modulo": "medicamentos",
     "acao": "criar", "descricao": "Criar medicamento na ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000062", "chave": "medicamentos:atualizar", "modulo": "medicamentos",
     "acao": "atualizar", "descricao": "Atualizar medicamento da ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000064", "chave": "prescricoes:criar", "modulo": "prescricoes",
     "acao": "criar", "descricao": "Criar versao de prescricao na ILPI atual."},
    {"id": "fac11000-0000-4000-8000-000000000065", "chave": "prescricoes:atualizar", "modulo": "prescricoes",
     "acao": "atualizar", "descricao": "Transicionar prescricao da ILPI atual."},
)
CHAVES = tuple(p["chave"] for p in PERMISSOES)
GRANTS = {
    "enfermagem": CHAVES,
    "responsavel_tecnico": CHAVES,
}
# Vinculos anteriores a 031 que o downgrade preserva (012/015).
PREEXISTENTES = {
    "medico": ("prescricoes:criar", "prescricoes:atualizar"),
}
CAMPOS = ("id", "modulo", "acao", "chave", "descricao")


def _id_da_chave(chave):
    return next(p["id"] for p in PERMISSOES if p["chave"] == chave)


def _perfis(bind, chave):
    rows = bind.execute(sa.text("SELECT id, ilpi_id FROM perfis WHERE chave = :c"), {"c": chave}).all()
    if not any(r[1] is None for r in rows):
        raise RuntimeError(f"031 exige o template {chave}; execute as migrations em ordem")
    return [r[0] for r in rows]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("031 suporta somente SQLite e PostgreSQL")
    for registro in PERMISSOES:
        row = bind.execute(sa.text("SELECT id, modulo, acao, chave, descricao FROM permissoes WHERE id = :id"),
                           {"id": registro["id"]}).mappings().first()
        if row is None:
            raise RuntimeError(f"031 exige a permissao {registro['chave']} da 012; execute as migrations em ordem")
        diferencas = {f: (row[f], registro[f]) for f in CAMPOS if row[f] != registro[f]}
        if diferencas:
            raise RuntimeError(f"031 permissao adulterada: {diferencas}")
    for chave_perfil, chaves in GRANTS.items():
        for perfil in _perfis(bind, chave_perfil):
            for chave in chaves:
                permissao = _id_da_chave(chave)
                if bind.execute(sa.text("SELECT 1 FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"),
                                {"p": perfil, "m": permissao}).first() is None:
                    bind.execute(sa.text("INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:p, :m)"),
                                 {"p": perfil, "m": permissao})


def downgrade() -> None:
    bind = op.get_bind()
    concedidos: dict[str, set] = {p["id"]: set() for p in PERMISSOES}
    for chave_perfil, chaves in GRANTS.items():
        perfis = _perfis(bind, chave_perfil)
        for chave in chaves:
            concedidos[_id_da_chave(chave)].update(perfis)
    permitidos = {k: set(v) for k, v in concedidos.items()}
    for chave_perfil, chaves in PREEXISTENTES.items():
        perfis = _perfis(bind, chave_perfil)
        for chave in chaves:
            permitidos[_id_da_chave(chave)].update(perfis)
    for permissao, perfis in permitidos.items():
        vinculos = {r[0] for r in bind.execute(sa.text("SELECT perfil_id FROM perfil_permissoes WHERE permissao_id = :m"),
                                               {"m": permissao}).all()}
        externos = sorted(vinculos - perfis)
        if externos:
            raise RuntimeError(f"031 recusa downgrade: vinculos externos a {permissao}: {externos}")
    for permissao, perfis in concedidos.items():
        for perfil in perfis:
            bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"),
                         {"p": perfil, "m": permissao})

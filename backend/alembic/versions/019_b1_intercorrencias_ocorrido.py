"""019_b1_intercorrencias_ocorrido_em: hora real do evento + emenda S.1 do cuidador.

`data` continua sendo o timestamp TECNICO de criacao do registro
(``server_default`` desde a 001) e NAO e renomeada neste BUILD. A coluna nova
``ocorrido_em`` responde "quando a intercorrencia realmente aconteceu",
adotando o par ocorrido_em/registrado_em que ExecucaoCuidado e Administracao
ja usam desde D.2/C.5.

Backfill: registros historicos recebem ``ocorrido_em = data``. Onde ``data``
for NULL — a coluna nasceu nullable na 001 — cai em CURRENT_TIMESTAMP, que
existe nos dois bancos suportados.

Emenda a matriz S.1 (015): o perfil institucional ``cuidador`` passa a ter
``intercorrencias:ler`` e ``intercorrencias:criar``. ``intercorrencias:atualizar``
segue NEGADA: corrigir e encerrar continuam restritos a enfermagem e
responsavel tecnico. Nenhuma permissao nova e criada — as tres existem desde
a 011; esta migration concede vinculos.

Os grants vao ao template ``cuidador`` e aos seus clones locais, casados por
chave e nunca por UUID de tenant, como em 007/017/018. Clonagem copia as
permissoes do template no momento da criacao do perfil local
(fase3a._clone_ilpi_admin_profile e equivalentes), entao tocar apenas o
template deixaria as ILPIs ja provisionadas sem a capacidade.

O downgrade remove exatamente os vinculos concedidos aqui. Isso e obrigatorio,
nao cosmetico: a 011 recusa downgrade quando encontra "vinculos externos" as
permissoes de intercorrencias, e a 015 recusa quando o conjunto de grants de
um perfil institucional difere do que ela criou. Sem esta limpeza, ambas
travariam.

NAO ha guard de dados na remocao de ``ocorrido_em``. Os guards de 017/018
protegem AUTORIA de ato humano (``validado_por``, ``anexado_por``); aqui nao
ha autoria atrelada a coluna. Um guard por diferenca entre ``ocorrido_em`` e
``data`` seria instavel: o relogio da aplicacao (ocorrido_em omitido) e o do
banco (server_default de ``data``) divergem por milissegundos em qualquer
direcao. O downgrade descarta a hora real do evento; isso esta declarado.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# alembic_version.version_num e VARCHAR(32): o SQLite ignora o limite, o
# PostgreSQL recusa. O id fica em 31 caracteres de proposito.
revision: str = "019_b1_intercorrencias_ocorrido"
down_revision: Union[str, None] = "018_a3_documentos_arquivo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATE_KEY = "cuidador"
INDEX_NAME = "ix_intercorrencias_ilpi_residente_ocorrido"

# Ja existentes na 011. Esta migration concede vinculos; nao cria catalogo.
# `intercorrencias:atualizar` (…059) fica deliberadamente de fora.
CUIDADOR_GRANTS = (
    {"id": "fac11000-0000-4000-8000-000000000057", "chave": "intercorrencias:ler"},
    {"id": "fac11000-0000-4000-8000-000000000058", "chave": "intercorrencias:criar"},
)
GRANT_NEGADO = {"id": "fac11000-0000-4000-8000-000000000059", "chave": "intercorrencias:atualizar"}


def _assert_catalog(bind):
    """As permissoes precisam vir da 011, com id e chave casando."""
    for permission in CUIDADOR_GRANTS:
        row = bind.execute(
            sa.text("SELECT chave FROM permissoes WHERE id = :id"), {"id": permission["id"]}
        ).first()
        if row is None:
            raise RuntimeError(f"019 exige a permissao {permission['chave']} da 011; execute as migrations em ordem")
        if row[0] != permission["chave"]:
            raise RuntimeError(f"019 catalogo adulterado: {permission['id']} deveria ser {permission['chave']}, e {row[0]}")


def _profile_ids(bind):
    """Template institucional de cuidador mais os clones locais ja provisionados."""
    rows = bind.execute(
        sa.text("SELECT id FROM perfis WHERE chave = :c"), {"c": TEMPLATE_KEY}
    ).all()
    if not rows:
        raise RuntimeError("019 exige o template cuidador da 015; execute as migrations em ordem")
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

    op.add_column("intercorrencias", sa.Column("ocorrido_em", sa.DateTime(timezone=True), nullable=True))
    # Historico: a hora conhecida do evento e a unica registrada ate aqui.
    bind.execute(sa.text("UPDATE intercorrencias SET ocorrido_em = data WHERE ocorrido_em IS NULL AND data IS NOT NULL"))
    # `data` nasceu nullable na 001; sem este segundo passo o NOT NULL abaixo falharia.
    bind.execute(sa.text("UPDATE intercorrencias SET ocorrido_em = CURRENT_TIMESTAMP WHERE ocorrido_em IS NULL"))
    # batch_alter_table recria a tabela no SQLite e emite ALTER direto no PostgreSQL.
    # A FK composta (residente_id, ilpi_id) da 003 precisa sobreviver a recriacao;
    # ha teste dedicado para isso.
    with op.batch_alter_table("intercorrencias") as batch:
        batch.alter_column("ocorrido_em", existing_type=sa.DateTime(timezone=True), nullable=False)
    op.create_index(INDEX_NAME, "intercorrencias", ["ilpi_id", "residente_id", "ocorrido_em"])

    _assert_catalog(bind)
    for profile_id in _profile_ids(bind):
        for permission in CUIDADOR_GRANTS:
            _ensure_link(bind, profile_id, permission["id"])


def downgrade() -> None:
    bind = op.get_bind()

    # Remove somente o que a 019 concedeu, e somente em perfis `cuidador`.
    # Vinculo em perfil que nao e cuidador nao pertence a esta migration:
    # apagar seria destruir decisao de outra origem.
    for profile_id in _profile_ids(bind):
        for permission in CUIDADOR_GRANTS:
            bind.execute(
                sa.text("DELETE FROM perfil_permissoes WHERE perfil_id = :p AND permissao_id = :m"),
                {"p": profile_id, "m": permission["id"]},
            )

    op.drop_index(INDEX_NAME, table_name="intercorrencias")
    with op.batch_alter_table("intercorrencias") as batch:
        batch.drop_column("ocorrido_em")

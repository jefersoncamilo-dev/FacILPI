"""004_catalogo_permissoes_rbac: catalogo administrativo deterministico.

Only the approved permission catalog, the two system profile templates, and
their exact permission links are inserted. No tenant, user, employee, or
clinical data is created here.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "004_catalogo_permissoes_rbac"
down_revision: Union[str, None] = "003_correcoes_fase1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISSION_CATALOG = (
    {
        "id": "fac11000-0000-4000-8000-000000000001",
        "chave": "ilpis:ler",
        "modulo": "ilpis",
        "acao": "ler",
        "descricao": "Consultar ILPIs conforme o contexto; contexto institucional enxerga somente a própria ILPI.",
        "escopo_permitido": "global/ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000002",
        "chave": "ilpis:criar",
        "modulo": "ilpis",
        "acao": "criar",
        "descricao": "Criar uma ILPI inicialmente em situação de rascunho.",
        "escopo_permitido": "global",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000003",
        "chave": "ilpis:atualizar",
        "modulo": "ilpis",
        "acao": "atualizar",
        "descricao": "Atualizar dados cadastrais permitidos sem alterar diretamente a situação.",
        "escopo_permitido": "global/ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000004",
        "chave": "ilpis:ativar",
        "modulo": "ilpis",
        "acao": "ativar",
        "descricao": "Ativar ILPI após todas as validações obrigatórias.",
        "escopo_permitido": "global",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000005",
        "chave": "ilpis:suspender",
        "modulo": "ilpis",
        "acao": "suspender",
        "descricao": "Suspender uma ILPI sem excluir seus registros.",
        "escopo_permitido": "global",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000006",
        "chave": "ilpis:inativar",
        "modulo": "ilpis",
        "acao": "inativar",
        "descricao": "Inativar logicamente uma ILPI, preservando histórico e auditoria.",
        "escopo_permitido": "global",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000007",
        "chave": "usuarios:ler",
        "modulo": "usuarios",
        "acao": "ler",
        "descricao": "Consultar usuários dentro do contexto autorizado.",
        "escopo_permitido": "global/ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000008",
        "chave": "usuarios:criar",
        "modulo": "usuarios",
        "acao": "criar",
        "descricao": "Criar usuário no contexto atual, sem cadastro público.",
        "escopo_permitido": "global/ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000009",
        "chave": "usuarios:atualizar",
        "modulo": "usuarios",
        "acao": "atualizar",
        "descricao": "Atualizar dados permitidos de um usuário do contexto atual.",
        "escopo_permitido": "global/ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000010",
        "chave": "usuarios:inativar",
        "modulo": "usuarios",
        "acao": "inativar",
        "descricao": "Inativar usuário e futuramente revogar suas sessões.",
        "escopo_permitido": "global/ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000011",
        "chave": "usuarios:redefinir_senha",
        "modulo": "usuarios",
        "acao": "redefinir_senha",
        "descricao": "Realizar redefinição administrativa e auditada de senha.",
        "escopo_permitido": "global/ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000012",
        "chave": "usuarios:atribuir_perfil",
        "modulo": "usuarios",
        "acao": "atribuir_perfil",
        "descricao": "Atribuir ou remover perfil compatível com o mesmo escopo.",
        "escopo_permitido": "global/ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000013",
        "chave": "funcionarios:ler",
        "modulo": "funcionarios",
        "acao": "ler",
        "descricao": "Consultar funcionários da ILPI atual.",
        "escopo_permitido": "ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000014",
        "chave": "funcionarios:criar",
        "modulo": "funcionarios",
        "acao": "criar",
        "descricao": "Cadastrar funcionário na ILPI atual.",
        "escopo_permitido": "ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000015",
        "chave": "funcionarios:atualizar",
        "modulo": "funcionarios",
        "acao": "atualizar",
        "descricao": "Atualizar dados funcionais permitidos.",
        "escopo_permitido": "ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000016",
        "chave": "funcionarios:inativar",
        "modulo": "funcionarios",
        "acao": "inativar",
        "descricao": "Inativar funcionário preservando o histórico.",
        "escopo_permitido": "ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000017",
        "chave": "funcionarios:vincular_usuario",
        "modulo": "funcionarios",
        "acao": "vincular_usuario",
        "descricao": "Vincular ou desvincular funcionário e usuário no mesmo tenant.",
        "escopo_permitido": "ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000018",
        "chave": "perfis:ler",
        "modulo": "perfis",
        "acao": "ler",
        "descricao": "Consultar perfis disponíveis no contexto.",
        "escopo_permitido": "global/ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000019",
        "chave": "perfis:criar",
        "modulo": "perfis",
        "acao": "criar",
        "descricao": "Criar perfil institucional personalizado.",
        "escopo_permitido": "ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000020",
        "chave": "perfis:atualizar",
        "modulo": "perfis",
        "acao": "atualizar",
        "descricao": "Atualizar somente perfis institucionais não protegidos.",
        "escopo_permitido": "ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000021",
        "chave": "perfis:inativar",
        "modulo": "perfis",
        "acao": "inativar",
        "descricao": "Inativar perfil institucional não protegido.",
        "escopo_permitido": "ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000022",
        "chave": "perfis:atribuir_permissao",
        "modulo": "perfis",
        "acao": "atribuir_permissao",
        "descricao": "Atribuir ou remover permissões permitidas de perfil institucional.",
        "escopo_permitido": "ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000023",
        "chave": "permissoes:ler",
        "modulo": "permissoes",
        "acao": "ler",
        "descricao": "Consultar o catálogo de permissões mantido por release.",
        "escopo_permitido": "global/ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000024",
        "chave": "configuracoes:ler",
        "modulo": "configuracoes",
        "acao": "ler",
        "descricao": "Consultar configurações institucionais permitidas.",
        "escopo_permitido": "ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000025",
        "chave": "configuracoes:atualizar",
        "modulo": "configuracoes",
        "acao": "atualizar",
        "descricao": "Atualizar configurações institucionais permitidas e auditadas; não altera catálogo regulatório do sistema.",
        "escopo_permitido": "ilpi",
    },
    {
        "id": "fac11000-0000-4000-8000-000000000026",
        "chave": "auditoria:ler",
        "modulo": "auditoria",
        "acao": "ler",
        "descricao": "Consultar auditoria conforme o escopo, com proteção de segredos e dados clínicos sensíveis.",
        "escopo_permitido": "global/ilpi",
    },
)


PROFILE_CATALOG = (
    {
        "id": "fac10000-0000-4000-8000-000000000001",
        "chave": "platform_superuser",
        "nome": "Superusuário da Plataforma",
        "descricao": "Perfil global gerenciado pelo sistema, sem permissões clínicas.",
        "escopo": "global",
        "ilpi_id": None,
        "situacao": "ativo",
    },
    {
        "id": "fac10000-0000-4000-8000-000000000002",
        "chave": "ilpi_admin",
        "nome": "Administrador da ILPI",
        "descricao": "Template institucional gerenciado pelo sistema; requer vínculo com uma ILPI.",
        "escopo": "ilpi",
        "ilpi_id": None,
        "situacao": "ativo",
    },
)


PROFILE_PERMISSION_KEYS = {
    "platform_superuser": (
        "ilpis:ler",
        "ilpis:criar",
        "ilpis:atualizar",
        "ilpis:ativar",
        "ilpis:suspender",
        "ilpis:inativar",
        "usuarios:ler",
        "usuarios:criar",
        "usuarios:atualizar",
        "usuarios:inativar",
        "usuarios:redefinir_senha",
        "usuarios:atribuir_perfil",
        "perfis:ler",
        "permissoes:ler",
        "auditoria:ler",
    ),
    "ilpi_admin": (
        "ilpis:ler",
        "ilpis:atualizar",
        "usuarios:ler",
        "usuarios:criar",
        "usuarios:atualizar",
        "usuarios:inativar",
        "usuarios:redefinir_senha",
        "usuarios:atribuir_perfil",
        "funcionarios:ler",
        "funcionarios:criar",
        "funcionarios:atualizar",
        "funcionarios:inativar",
        "funcionarios:vincular_usuario",
        "perfis:ler",
        "perfis:criar",
        "perfis:atualizar",
        "perfis:inativar",
        "perfis:atribuir_permissao",
        "permissoes:ler",
        "configuracoes:ler",
        "configuracoes:atualizar",
        "auditoria:ler",
    ),
}


PERMISSION_FIELDS = ("id", "modulo", "acao", "chave", "descricao")
PROFILE_FIELDS = ("id", "ilpi_id", "nome", "chave", "descricao", "escopo", "situacao")
TEMPLATE_PROFILE_KEY_INDEX = "uq_perfis_chave_template_ilpi_null"


def _where_equals(fields, values):
    clauses = []
    parameters = {}
    for field in fields:
        value = values[field]
        if value is None:
            clauses.append(f"{field} IS NULL")
        else:
            clauses.append(f"{field} = :{field}")
            parameters[field] = value
    return " AND ".join(clauses), parameters


def _assert_same_record(row, record, fields, label):
    differences = {
        field: (row[field], record[field])
        for field in fields
        if row[field] != record[field]
    }
    if differences:
        raise RuntimeError(f"004 {label} adulterado: {differences}")


def _assert_no_unique_conflicts(bind, table, record, unique_sets, label, exclude_id=None):
    for unique_fields in unique_sets:
        where, parameters = _where_equals(unique_fields, record)
        if exclude_id is not None:
            where += " AND id <> :exclude_id"
            parameters["exclude_id"] = exclude_id
        conflict = bind.execute(
            sa.text(f"SELECT id FROM {table} WHERE {where}"), parameters
        ).mappings().first()
        if conflict is not None:
            joined = ", ".join(unique_fields)
            raise RuntimeError(
                f"004 conflito de {label} em ({joined}); "
                f"esperado id {record['id']}, encontrado {conflict['id']}"
            )


def _ensure_record(bind, table, record, fields, unique_sets, label):
    columns = ", ".join(fields)
    by_id = bind.execute(
        sa.text(f"SELECT {columns} FROM {table} WHERE id = :id"),
        {"id": record["id"]},
    ).mappings().first()
    if by_id is not None:
        _assert_same_record(by_id, record, fields, label)
        _assert_no_unique_conflicts(
            bind, table, record, unique_sets, label, exclude_id=record["id"]
        )
        return

    _assert_no_unique_conflicts(bind, table, record, unique_sets, label)

    values = ", ".join(f":{field}" for field in fields)
    bind.execute(
        sa.text(f"INSERT INTO {table} ({columns}) VALUES ({values})"),
        {field: record[field] for field in fields},
    )


def _permission_records():
    return tuple(
        {field: permission[field] for field in PERMISSION_FIELDS}
        for permission in PERMISSION_CATALOG
    )


def _profile_permission_links():
    permission_ids = {permission["chave"]: permission["id"] for permission in PERMISSION_CATALOG}
    profile_ids = {profile["chave"]: profile["id"] for profile in PROFILE_CATALOG}
    return tuple(
        (profile_ids[profile_key], permission_ids[permission_key])
        for profile_key in ("platform_superuser", "ilpi_admin")
        for permission_key in PROFILE_PERMISSION_KEYS[profile_key]
    )


def _ensure_link(bind, profile_id, permission_id):
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM perfil_permissoes "
            "WHERE perfil_id = :perfil_id AND permissao_id = :permissao_id"
        ),
        {"perfil_id": profile_id, "permissao_id": permission_id},
    ).first()
    if exists is None:
        bind.execute(
            sa.text(
                "INSERT INTO perfil_permissoes (perfil_id, permissao_id) "
                "VALUES (:perfil_id, :permissao_id)"
            ),
            {"perfil_id": profile_id, "permissao_id": permission_id},
        )


def _ensure_template_profile_key_index(bind):
    duplicate = bind.execute(
        sa.text(
            "SELECT chave, COUNT(*) AS quantidade FROM perfis "
            "WHERE ilpi_id IS NULL GROUP BY chave HAVING COUNT(*) > 1"
        )
    ).mappings().first()
    if duplicate is not None:
        raise RuntimeError(
            "004 não pode garantir unicidade de perfil técnico com ilpi_id=NULL: "
            f"chave {duplicate['chave']!r} possui {duplicate['quantidade']} registros"
        )

    index_names = {
        index["name"] for index in sa.inspect(bind).get_indexes("perfis")
    }
    if TEMPLATE_PROFILE_KEY_INDEX not in index_names:
        op.create_index(
            TEMPLATE_PROFILE_KEY_INDEX,
            "perfis",
            ["chave"],
            unique=True,
            postgresql_where=sa.text("ilpi_id IS NULL"),
            sqlite_where=sa.text("ilpi_id IS NULL"),
        )


def upgrade() -> None:
    bind = op.get_bind()

    _ensure_template_profile_key_index(bind)

    for permission in _permission_records():
        _ensure_record(
            bind,
            "permissoes",
            permission,
            PERMISSION_FIELDS,
            (("chave",), ("modulo", "acao")),
            "permissao",
        )

    for profile in PROFILE_CATALOG:
        _ensure_record(
            bind,
            "perfis",
            profile,
            PROFILE_FIELDS,
            (("chave", "ilpi_id"),),
            "perfil",
        )

    for profile_id, permission_id in _profile_permission_links():
        _ensure_link(bind, profile_id, permission_id)


def _validate_existing_records(bind):
    permission_records = _permission_records()
    for permission in permission_records:
        row = bind.execute(
            sa.text(
                "SELECT id, modulo, acao, chave, descricao FROM permissoes "
                "WHERE id = :id"
            ),
            {"id": permission["id"]},
        ).mappings().first()
        if row is not None:
            _assert_same_record(row, permission, PERMISSION_FIELDS, "permissao")
            _assert_no_unique_conflicts(
                bind,
                "permissoes",
                permission,
                (("chave",), ("modulo", "acao")),
                "permissao",
                exclude_id=permission["id"],
            )

    for profile in PROFILE_CATALOG:
        row = bind.execute(
            sa.text(
                "SELECT id, ilpi_id, nome, chave, descricao, escopo, situacao "
                "FROM perfis WHERE id = :id"
            ),
            {"id": profile["id"]},
        ).mappings().first()
        if row is not None:
            _assert_same_record(row, profile, PROFILE_FIELDS, "perfil")
            _assert_no_unique_conflicts(
                bind,
                "perfis",
                profile,
                (("chave", "ilpi_id"),),
                "perfil",
                exclude_id=profile["id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    expected_links = set(_profile_permission_links())
    profile_ids = tuple(profile["id"] for profile in PROFILE_CATALOG)
    permission_ids = tuple(permission["id"] for permission in _permission_records())

    _validate_existing_records(bind)

    links = bind.execute(
        sa.text(
            "SELECT perfil_id, permissao_id FROM perfil_permissoes "
            "WHERE perfil_id IN :profile_ids"
        ).bindparams(sa.bindparam("profile_ids", expanding=True)),
        {"profile_ids": profile_ids},
    ).mappings().all()
    unexpected_links = {
        (link["perfil_id"], link["permissao_id"])
        for link in links
        if (link["perfil_id"], link["permissao_id"]) not in expected_links
    }
    if unexpected_links:
        raise RuntimeError(
            f"004 possui vínculos externos aos registros esperados: {sorted(unexpected_links)}"
        )

    external_links = bind.execute(
        sa.text(
            "SELECT perfil_id, permissao_id FROM perfil_permissoes "
            "WHERE permissao_id IN :permission_ids AND perfil_id NOT IN :profile_ids"
        ).bindparams(
            sa.bindparam("permission_ids", expanding=True),
            sa.bindparam("profile_ids", expanding=True),
        ),
        {"permission_ids": permission_ids, "profile_ids": profile_ids},
    ).mappings().all()
    if external_links:
        raise RuntimeError(
            f"004 possui vínculos externos às permissões: {external_links}"
        )

    for profile_id, permission_id in expected_links:
        bind.execute(
            sa.text(
                "DELETE FROM perfil_permissoes "
                "WHERE perfil_id = :perfil_id AND permissao_id = :permissao_id"
            ),
            {"perfil_id": profile_id, "permissao_id": permission_id},
        )

    for profile in PROFILE_CATALOG:
        bind.execute(
            sa.text("DELETE FROM perfis WHERE id = :id"),
            {"id": profile["id"]},
        )

    for permission in _permission_records():
        bind.execute(
            sa.text("DELETE FROM permissoes WHERE id = :id"),
            {"id": permission["id"]},
        )

    if TEMPLATE_PROFILE_KEY_INDEX in {
        index["name"] for index in sa.inspect(bind).get_indexes("perfis")
    }:
        op.drop_index(TEMPLATE_PROFILE_KEY_INDEX, table_name="perfis")

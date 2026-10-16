"""015_s1_matriz_permissoes: perfis institucionais explícitos.

Cria 5 templates institucionais (ilpi_id NULL, escopo ilpi):
cuidador, enfermagem, medico, responsavel_tecnico, administrativo — com
grants clínicos explícitos por perfil. Profissão/cargo textual NUNCA
concede permissão; atribuição é administrativa explícita (endpoints S.1
com clone-on-assign, anti-escalation e auditoria).

NÃO cria permissões (baseline permanece 85). C.5 segue CATALOG_ONLY.
ilpi_admin preservado temporariamente (remover grants clínicos dele sem
quebrar administração exige coordenação de produção; documentado).
Platform segue sem acesso clínico. Clones locais NÃO são criados em
massa aqui: só via atribuição explícita (sem propagação automática).
TEMPLATE_KEY ilpi_admin e vínculos existentes intocados.

Migrations 001-014 não são modificadas.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "015_s1_matriz_permissoes"
down_revision: Union[str, None] = "014_d2_rotina_assistencial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CUIDADOR = (
    "residentes:ler", "planos_cuidados:ler", "programacoes:ler", "ocorrencias:ler",
    "execucoes:ler", "execucoes:criar", "plantao:ler", "sinais_vitais:ler",
)
ENFERMAGEM = (
    "residentes:ler", "planos_cuidados:ler", "programacoes:ler", "programacoes:atualizar",
    "ocorrencias:ler", "ocorrencias:cancelar", "execucoes:ler", "execucoes:criar",
    "execucoes:corrigir", "plantao:ler", "sinais_vitais:ler", "sinais_vitais:criar",
    "intercorrencias:ler", "intercorrencias:criar", "intercorrencias:atualizar",
    "administracoes:ler", "administracoes:criar", "administracoes:corrigir",
    "prescricoes:ler", "medicamentos:ler", "avaliacoes:ler",
)
MEDICO = (
    "prescricoes:ler", "prescricoes:criar", "prescricoes:atualizar", "medicamentos:ler",
    "administracoes:ler", "doses_previstas:ler", "avaliacoes:ler", "avaliacoes:criar",
    "avaliacoes:atualizar", "planos_cuidados:ler", "sinais_vitais:ler",
    "intercorrencias:ler", "residentes:ler", "plantao:ler",
)
RESPONSAVEL_TECNICO = (
    "planos_cuidados:ler", "planos_cuidados:criar", "planos_cuidados:atualizar",
    "planos_cuidados:revisar", "planos_cuidados:aprovar", "planos_cuidados:encerrar",
    "programacoes:ler", "programacoes:criar", "programacoes:atualizar", "programacoes:inativar",
    "ocorrencias:ler", "ocorrencias:cancelar", "execucoes:ler", "execucoes:criar",
    "execucoes:corrigir", "plantao:ler", "avaliacoes:ler", "avaliacoes:criar",
    "avaliacoes:atualizar", "grau_dependencia:ler", "grau_dependencia:criar",
    "sinais_vitais:ler", "intercorrencias:ler", "intercorrencias:criar",
    "intercorrencias:atualizar", "prescricoes:ler", "medicamentos:ler",
    "administracoes:ler", "residentes:ler", "documentos:ler",
)
ADMINISTRATIVO = (
    "residentes:ler", "residentes:criar", "residentes:atualizar",
    "familiares:ler", "familiares:criar", "familiares:atualizar",
    "documentos:ler", "documentos:criar", "documentos:atualizar",
)

NEW_PROFILES = (
    {"id": "fac10000-0000-4000-8000-000000000003", "chave": "cuidador", "nome": "Cuidador",
     "descricao": "Execução de cuidados cotidianos e rotina operacional, sem medicação nem aprovação clínica.",
     "grants": CUIDADOR},
    {"id": "fac10000-0000-4000-8000-000000000004", "chave": "enfermagem", "nome": "Enfermagem",
     "descricao": "Assistência clínica operacional incluindo administração de medicamentos quando atribuído.",
     "grants": ENFERMAGEM},
    {"id": "fac10000-0000-4000-8000-000000000005", "chave": "medico", "nome": "Médico",
     "descricao": "Capacidades de prescrição e leitura clínica, somente por atribuição explícita.",
     "grants": MEDICO},
    {"id": "fac10000-0000-4000-8000-000000000006", "chave": "responsavel_tecnico", "nome": "Responsável Técnico",
     "descricao": "Supervisão clínica: revisão/aprovação do PAIS e rotina assistencial.",
     "grants": RESPONSAVEL_TECNICO},
    {"id": "fac10000-0000-4000-8000-000000000007", "chave": "administrativo", "nome": "Administrativo",
     "descricao": "Cadastros institucionais administrativos, sem capacidades clínicas.",
     "grants": ADMINISTRATIVO},
)

PROFILE_FIELDS = ("id", "ilpi_id", "nome", "chave", "descricao", "escopo", "situacao")


def _preflight_connection(bind):
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("015 suporta somente SQLite e PostgreSQL")


def _permission_id(bind, chave):
    row = bind.execute(sa.text("SELECT id FROM permissoes WHERE chave = :c"), {"c": chave}).first()
    if row is None:
        raise RuntimeError(f"015 exige permissao de catalogo inexistente: {chave}")
    return row[0]


def _ensure_template(bind, profile):
    record = {"id": profile["id"], "ilpi_id": None, "nome": profile["nome"],
              "chave": profile["chave"], "descricao": profile["descricao"],
              "escopo": "ilpi", "situacao": "ativo"}
    row = bind.execute(sa.text(
        "SELECT id, ilpi_id, nome, chave, descricao, escopo, situacao FROM perfis WHERE id = :id"
    ), {"id": record["id"]}).mappings().first()
    if row is not None:
        differences = {f: (row[f], record[f]) for f in PROFILE_FIELDS if row[f] != record[f]}
        if differences:
            raise RuntimeError(f"015 template adulterado: {differences}")
    else:
        clash = bind.execute(sa.text(
            "SELECT id FROM perfis WHERE chave = :c AND ilpi_id IS NULL AND id != :id"
        ), {"c": record["chave"], "id": record["id"]}).first()
        if clash is not None:
            raise RuntimeError(f"015 conflito de template institucional: {record['chave']}")
        bind.execute(sa.text(
            "INSERT INTO perfis (id, ilpi_id, nome, chave, descricao, escopo, situacao) "
            "VALUES (:id, :ilpi_id, :nome, :chave, :descricao, :escopo, :situacao)"), record)
    expected = {_permission_id(bind, chave) for chave in profile["grants"]}
    current = {row[0] for row in bind.execute(sa.text(
        "SELECT permissao_id FROM perfil_permissoes WHERE perfil_id = :p"), {"p": record["id"]}).all()}
    for permission_id in sorted(expected - current):
        bind.execute(sa.text(
            "INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:p, :m)"),
            {"p": record["id"], "m": permission_id})
    return record["id"], expected


def _s1_profile_ids(bind):
    chaves = [p["chave"] for p in NEW_PROFILES]
    return [row[0] for row in bind.execute(sa.text(
        "SELECT id FROM perfis WHERE chave IN :chaves").bindparams(sa.bindparam("chaves", expanding=True)),
        {"chaves": chaves}).all()]


def upgrade() -> None:
    bind = op.get_bind()
    _preflight_connection(bind)
    for profile in NEW_PROFILES:
        _ensure_template(bind, profile)


def downgrade() -> None:
    bind = op.get_bind()
    _preflight_connection(bind)
    profile_ids = _s1_profile_ids(bind)
    expected = {}
    for profile in NEW_PROFILES:
        record_id = profile["id"]
        if record_id in profile_ids:
            row = bind.execute(sa.text(
                "SELECT id, ilpi_id, nome, chave, descricao, escopo, situacao FROM perfis WHERE id = :id"
            ), {"id": record_id}).mappings().first()
            differences = {f: (row[f], {"id": profile["id"], "ilpi_id": None, "nome": profile["nome"],
                                        "chave": profile["chave"], "descricao": profile["descricao"],
                                        "escopo": "ilpi", "situacao": "ativo"}[f]) for f in PROFILE_FIELDS if row[f] != {
                                            "id": profile["id"], "ilpi_id": None, "nome": profile["nome"],
                                            "chave": profile["chave"], "descricao": profile["descricao"],
                                            "escopo": "ilpi", "situacao": "ativo"}[f]}
            if differences:
                raise RuntimeError(f"015 recusa downgrade: template adulterado: {differences}")
            expected[record_id] = {_permission_id(bind, chave) for chave in profile["grants"]}
    # Vínculos institucionais ativos jamais são apagados silenciosamente.
    if profile_ids:
        links = bind.execute(sa.text(
            "SELECT id FROM usuario_ilpi_perfis WHERE perfil_id IN :pids").bindparams(
                sa.bindparam("pids", expanding=True)), {"pids": profile_ids}).all()
        if links:
            raise RuntimeError(f"015 recusa downgrade: {len(links)} vinculos em perfis institucionais")
        for profile_id in profile_ids:
            current = {row[0] for row in bind.execute(sa.text(
                "SELECT permissao_id FROM perfil_permissoes WHERE perfil_id = :p"), {"p": profile_id}).all()}
            if current != expected.get(profile_id, set()):
                raise RuntimeError("015 recusa downgrade: grants customizados em perfil institucional")
        for profile_id in profile_ids:
            bind.execute(sa.text("DELETE FROM perfil_permissoes WHERE perfil_id = :p"), {"p": profile_id})
        for profile_id in profile_ids:
            bind.execute(sa.text("DELETE FROM perfis WHERE id = :p"), {"p": profile_id})

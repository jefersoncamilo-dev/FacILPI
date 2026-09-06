import uuid
from datetime import datetime, date
import sqlalchemy as sa
from sqlalchemy import String, Boolean, DateTime, Date, Text, Integer, Float, ForeignKey, func, UniqueConstraint, CheckConstraint, Index, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy import Uuid
import uuid as uuid_lib

from .database import Base

# Helper: use String UUID for sqlite compatibility, but sqlalchemy 2 can handle Uuid
# We'll use String(36) for portability across sqlite/postgres.


def gen_uuid():
    return str(uuid_lib.uuid4())


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    exige_troca_senha: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Instituicao(Base):
    __tablename__ = "instituicoes"
    __table_args__ = (
        CheckConstraint(
            "situacao IN ('ativa','rascunho','ILPI_RASCUNHO','ONBOARDING_IN_PROGRESS','READY_FOR_ACTIVATION','ACTIVE','ATIVA','SUSPENSA','INATIVA','suspensa','inativa')",
            name="ck_instituicoes_situacao",
        ),
        CheckConstraint("capacidade IS NULL OR capacidade > 0", name="ck_instituicoes_capacidade_pos"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    razao_social: Mapped[str] = mapped_column(String(255), nullable=False)
    nome_fantasia: Mapped[str] = mapped_column(String(255), nullable=True)
    finalidade: Mapped[str] = mapped_column(String(255), nullable=True)
    cnpj: Mapped[str] = mapped_column(String(18), unique=True, nullable=True)
    endereco: Mapped[str] = mapped_column(Text, nullable=True)
    municipio: Mapped[str] = mapped_column(String(255), nullable=True)
    uf: Mapped[str] = mapped_column(String(2), nullable=True)
    telefone: Mapped[str] = mapped_column(String(20), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=True)
    responsavel_legal: Mapped[str] = mapped_column(String(255), nullable=True)
    responsavel_tecnico: Mapped[str] = mapped_column(String(255), nullable=True)
    capacidade: Mapped[int] = mapped_column(Integer, nullable=True)
    licenca_sanitaria: Mapped[str] = mapped_column(String(100), nullable=True)
    validade_licenca: Mapped[date] = mapped_column(Date, nullable=True)
    fuso_horario: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo")
    situacao: Mapped[str] = mapped_column(String(50), default="ILPI_RASCUNHO", server_default="ILPI_RASCUNHO")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Residente(Base):
    __tablename__ = "residentes"
    __table_args__ = (
        UniqueConstraint("cpf", "instituicao_id", name="uq_residente_cpf_inst"),
        UniqueConstraint("id", "instituicao_id", name="uq_residentes_id_ilpi"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    instituicao_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=True, index=True)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    nome_social: Mapped[str] = mapped_column(String(255), nullable=True)
    cpf: Mapped[str] = mapped_column(String(14), nullable=True)
    rg: Mapped[str] = mapped_column(String(20), nullable=True)
    cns: Mapped[str] = mapped_column(String(15), nullable=True)
    data_nascimento: Mapped[date] = mapped_column(Date, nullable=False)
    sexo: Mapped[str] = mapped_column(String(10), nullable=True)
    foto: Mapped[str] = mapped_column(Text, nullable=True)
    data_admissao: Mapped[date] = mapped_column(Date, nullable=True)
    situacao: Mapped[str] = mapped_column(String(50), default="Em admissao")
    grau_dependencia: Mapped[str] = mapped_column(String(50), nullable=True)
    restricoes: Mapped[str] = mapped_column(Text, nullable=True)
    alergias: Mapped[str] = mapped_column(Text, nullable=True)
    necessidades_especiais: Mapped[str] = mapped_column(Text, nullable=True)
    observacoes: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Familiar(Base):
    __tablename__ = "familiares"
    __table_args__ = (
        Index("ix_familiares_ilpi_id", "ilpi_id"),
        ForeignKeyConstraint(
            ["residente_id", "ilpi_id"],
            ["residentes.id", "residentes.instituicao_id"],
            name="fk_familiares_residente_ilpi",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=False, index=True)
    ilpi_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=True, index=True)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    cpf: Mapped[str] = mapped_column(String(14), nullable=True)
    parentesco: Mapped[str] = mapped_column(String(50), nullable=True)
    telefone: Mapped[str] = mapped_column(String(20), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=True)
    endereco: Mapped[str] = mapped_column(Text, nullable=True)
    tipo_responsabilidade: Mapped[str] = mapped_column(String(50), nullable=True)
    autorizacao_acesso: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Documento(Base):
    __tablename__ = "documentos"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=True, index=True)
    instituicao_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=True)
    tipo: Mapped[str] = mapped_column(String(100), nullable=False)
    numero: Mapped[str] = mapped_column(String(100), nullable=True)
    arquivo: Mapped[str] = mapped_column(Text, nullable=True)
    validade: Mapped[date] = mapped_column(Date, nullable=True)
    obrigatorio: Mapped[bool] = mapped_column(Boolean, default=False)
    situacao: Mapped[str] = mapped_column(String(50), default="pendente")
    responsavel_envio: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuartoLeito(Base):
    __tablename__ = "quartos_leitos"
    __table_args__ = (
        ForeignKeyConstraint(
            ["residente_atual_id", "instituicao_id"],
            ["residentes.id", "residentes.instituicao_id"],
            name="fk_quartos_residente_ilpi",
        ),
        CheckConstraint("capacidade = 1", name="ck_quartos_leitos_capacidade_1"),
        CheckConstraint(
            "situacao IN ('livre','reservado','bloqueado','manutencao','inativo')",
            name="ck_quartos_leitos_situacao",
        ),
        Index(
            "uq_quartos_leitos_inst_quarto_leito",
            "instituicao_id", "quarto", "leito",
            unique=True,
            sqlite_where=sa.text("unidade IS NULL"),
            postgresql_where=sa.text("unidade IS NULL"),
        ),
        UniqueConstraint(
            "instituicao_id", "unidade", "quarto", "leito",
            name="uq_quartos_leitos_inst_unidade_quarto_leito",
        ),
        Index(
            "uq_quartos_leitos_residente_ativo",
            "instituicao_id", "residente_atual_id",
            unique=True,
            sqlite_where=sa.text("residente_atual_id IS NOT NULL"),
            postgresql_where=sa.text("residente_atual_id IS NOT NULL"),
        ),
        Index("ix_quartos_leitos_ilpi_id", "instituicao_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    instituicao_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=False)
    unidade: Mapped[str] = mapped_column(String(100), nullable=True)
    quarto: Mapped[str] = mapped_column(String(50), nullable=False)
    leito: Mapped[str] = mapped_column(String(50), nullable=False)
    capacidade: Mapped[int] = mapped_column(Integer, default=1)
    acessibilidade: Mapped[str] = mapped_column(String(100), nullable=True)
    residente_atual_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=True)
    situacao: Mapped[str] = mapped_column(String(50), default="livre")
    data_ocupacao: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OcupacaoHistorico(Base):
    __tablename__ = "ocupacao_historico"
    __table_args__ = (
        ForeignKeyConstraint(
            ["residente_id", "instituicao_id"],
            ["residentes.id", "residentes.instituicao_id"],
            name="fk_ocupacao_hist_residente_ilpi",
        ),
        ForeignKeyConstraint(
            ["quarto_leito_id", "instituicao_id"],
            ["quartos_leitos.id", "quartos_leitos.instituicao_id"],
            name="fk_ocupacao_hist_leito_ilpi",
        ),
        Index("ix_ocupacao_hist_ilpi_residente", "instituicao_id", "residente_id"),
        Index("ix_ocupacao_hist_ilpi_leito", "instituicao_id", "quarto_leito_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    instituicao_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=False)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=False)
    quarto_leito_id: Mapped[str] = mapped_column(String(36), ForeignKey("quartos_leitos.id"), nullable=False)
    data_entrada: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_saida: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    tipo_movimentacao: Mapped[str] = mapped_column(String(50), nullable=False)
    motivo: Mapped[str] = mapped_column(Text, nullable=True)
    usuario_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Ausencia(Base):
    __tablename__ = "ausencias"
    __table_args__ = (
        ForeignKeyConstraint(
            ["residente_id", "instituicao_id"],
            ["residentes.id", "residentes.instituicao_id"],
            name="fk_ausencias_residente_ilpi",
        ),
        CheckConstraint(
            "tipo IN ('hospitalizacao','saida_temporaria')",
            name="ck_ausencias_tipo",
        ),
        Index(
            "uq_ausencias_ativa_por_residente",
            "instituicao_id", "residente_id",
            unique=True,
            sqlite_where=sa.text("data_fim IS NULL"),
            postgresql_where=sa.text("data_fim IS NULL"),
        ),
        Index("ix_ausencias_ilpi_residente", "instituicao_id", "residente_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    instituicao_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=False)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=False)
    quarto_leito_id: Mapped[str] = mapped_column(String(36), ForeignKey("quartos_leitos.id"), nullable=True)
    tipo: Mapped[str] = mapped_column(String(50), nullable=False)
    data_inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_fim: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    observacoes: Mapped[str] = mapped_column(Text, nullable=True)
    usuario_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Avaliacao(Base):
    __tablename__ = "avaliacoes"
    __table_args__ = (
        Index("ix_avaliacoes_ilpi_id", "ilpi_id"),
        ForeignKeyConstraint(
            ["residente_id", "ilpi_id"],
            ["residentes.id", "residentes.instituicao_id"],
            name="fk_avaliacoes_residente_ilpi",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=False, index=True)
    ilpi_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=True, index=True)
    tipo: Mapped[str] = mapped_column(String(50), nullable=False)  # Katz, Lawton, etc
    instrumento: Mapped[str] = mapped_column(String(100), nullable=True)
    profissional: Mapped[str] = mapped_column(String(255), nullable=True)
    respostas: Mapped[str] = mapped_column(Text, nullable=True)  # JSON string
    pontuacao: Mapped[float] = mapped_column(Float, nullable=True)
    classificacao: Mapped[str] = mapped_column(String(100), nullable=True)
    data: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    validade: Mapped[date] = mapped_column(Date, nullable=True)
    observacoes: Mapped[str] = mapped_column(Text, nullable=True)


class PlanoCuidados(Base):
    __tablename__ = "planos_cuidados"
    __table_args__ = (
        Index("ix_planos_cuidados_ilpi_id", "ilpi_id"),
        ForeignKeyConstraint(
            ["residente_id", "ilpi_id"],
            ["residentes.id", "residentes.instituicao_id"],
            name="fk_planos_residente_ilpi",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=False, index=True)
    ilpi_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=True, index=True)
    versao: Mapped[int] = mapped_column(Integer, default=1)
    objetivos: Mapped[str] = mapped_column(Text, nullable=True)
    data_inicial: Mapped[date] = mapped_column(Date, nullable=False)
    data_final: Mapped[date] = mapped_column(Date, nullable=True)
    situacao: Mapped[str] = mapped_column(String(50), default="Rascunho")
    responsaveis: Mapped[str] = mapped_column(Text, nullable=True)
    revisor: Mapped[str] = mapped_column(String(255), nullable=True)
    aprovador: Mapped[str] = mapped_column(String(255), nullable=True)
    data_aprovacao: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Tarefa(Base):
    __tablename__ = "tarefas"
    __table_args__ = (
        Index("ix_tarefas_ilpi_id", "ilpi_id"),
        ForeignKeyConstraint(
            ["residente_id", "ilpi_id"],
            ["residentes.id", "residentes.instituicao_id"],
            name="fk_tarefas_residente_ilpi",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=False, index=True)
    ilpi_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=True, index=True)
    plano_id: Mapped[str] = mapped_column(String(36), ForeignKey("planos_cuidados.id"), nullable=True)
    descricao: Mapped[str] = mapped_column(String(500), nullable=False)
    horario_previsto: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    horario_realizado: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    prioridade: Mapped[str] = mapped_column(String(20), default="media")
    responsavel: Mapped[str] = mapped_column(String(255), nullable=True)
    executor: Mapped[str] = mapped_column(String(255), nullable=True)
    situacao: Mapped[str] = mapped_column(String(50), default="Pendente")  # Pendente, Concluída, etc
    justificativa: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Medicamento(Base):
    __tablename__ = "medicamentos"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    principio_ativo: Mapped[str] = mapped_column(String(255), nullable=True)
    apresentacao: Mapped[str] = mapped_column(String(100), nullable=True)
    concentracao: Mapped[str] = mapped_column(String(100), nullable=True)
    unidade: Mapped[str] = mapped_column(String(50), nullable=True)
    lote: Mapped[str] = mapped_column(String(50), nullable=True)
    validade: Mapped[date] = mapped_column(Date, nullable=True)
    fabricante: Mapped[str] = mapped_column(String(255), nullable=True)
    situacao: Mapped[str] = mapped_column(String(50), default="ativo")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Prescricao(Base):
    __tablename__ = "prescricoes"
    __table_args__ = (
        Index("ix_prescricoes_ilpi_id", "ilpi_id"),
        ForeignKeyConstraint(
            ["residente_id", "ilpi_id"],
            ["residentes.id", "residentes.instituicao_id"],
            name="fk_prescricoes_residente_ilpi",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=False, index=True)
    ilpi_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=True, index=True)
    medicamento_id: Mapped[str] = mapped_column(String(36), ForeignKey("medicamentos.id"), nullable=False)
    prescritor: Mapped[str] = mapped_column(String(255), nullable=False)
    dose: Mapped[str] = mapped_column(String(50), nullable=False)
    via: Mapped[str] = mapped_column(String(50), nullable=True)
    frequencia: Mapped[str] = mapped_column(String(50), nullable=True)
    horarios: Mapped[str] = mapped_column(String(255), nullable=True)
    inicio: Mapped[date] = mapped_column(Date, nullable=False)
    termino: Mapped[date] = mapped_column(Date, nullable=True)
    orientacoes: Mapped[str] = mapped_column(Text, nullable=True)
    situacao: Mapped[str] = mapped_column(String(50), default="ativa")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SinalVital(Base):
    __tablename__ = "sinais_vitais"
    __table_args__ = (
        Index("ix_sinais_vitais_ilpi_id", "ilpi_id"),
        ForeignKeyConstraint(
            ["residente_id", "ilpi_id"],
            ["residentes.id", "residentes.instituicao_id"],
            name="fk_sinais_residente_ilpi",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=False, index=True)
    ilpi_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=True, index=True)
    temperatura: Mapped[float] = mapped_column(Float, nullable=True)
    pressao_sistolica: Mapped[int] = mapped_column(Integer, nullable=True)
    pressao_diastolica: Mapped[int] = mapped_column(Integer, nullable=True)
    frequencia_cardiaca: Mapped[int] = mapped_column(Integer, nullable=True)
    frequencia_respiratoria: Mapped[int] = mapped_column(Integer, nullable=True)
    saturacao: Mapped[int] = mapped_column(Integer, nullable=True)
    glicemia: Mapped[float] = mapped_column(Float, nullable=True)
    peso: Mapped[float] = mapped_column(Float, nullable=True)
    profissional: Mapped[str] = mapped_column(String(255), nullable=True)
    data: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    observacao: Mapped[str] = mapped_column(Text, nullable=True)


class Intercorrencia(Base):
    __tablename__ = "intercorrencias"
    __table_args__ = (
        Index("ix_intercorrencias_ilpi_id", "ilpi_id"),
        ForeignKeyConstraint(
            ["residente_id", "ilpi_id"],
            ["residentes.id", "residentes.instituicao_id"],
            name="fk_intercorrencias_residente_ilpi",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=False, index=True)
    ilpi_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=True, index=True)
    tipo: Mapped[str] = mapped_column(String(100), nullable=False)
    gravidade: Mapped[str] = mapped_column(String(50), nullable=True)
    situacao: Mapped[str] = mapped_column(String(50), default="Aberta")
    sbar_situacao: Mapped[str] = mapped_column(Text, nullable=True)
    sbar_contexto: Mapped[str] = mapped_column(Text, nullable=True)
    sbar_avaliacao: Mapped[str] = mapped_column(Text, nullable=True)
    sbar_recomendacao: Mapped[str] = mapped_column(Text, nullable=True)
    providencia: Mapped[str] = mapped_column(Text, nullable=True)
    desfecho: Mapped[str] = mapped_column(Text, nullable=True)
    responsavel: Mapped[str] = mapped_column(String(255), nullable=True)
    data: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Alerta(Base):
    __tablename__ = "alertas"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    instituicao_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=True)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=True)
    origem: Mapped[str] = mapped_column(String(100), nullable=True)
    tipo: Mapped[str] = mapped_column(String(50), nullable=False)
    gravidade: Mapped[str] = mapped_column(String(20), nullable=True)
    mensagem: Mapped[str] = mapped_column(Text, nullable=False)
    responsavel: Mapped[str] = mapped_column(String(255), nullable=True)
    prazo: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    situacao: Mapped[str] = mapped_column(String(50), default="Ativo")
    resolucao: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ===== FASE 1 — Novos modelos multi-tenant / auditoria / tokens =====

class BootstrapState(Base):
    __tablename__ = "bootstrap_state"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('UNINITIALIZED','PLATFORM_BOOTSTRAPPED','FIRST_PASSWORD_CHANGED','ILPI_CREATED','ONBOARDING_IN_PROGRESS','ONBOARDING_COMPLETED')",
            name="ck_bootstrap_estado",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    estado: Mapped[str] = mapped_column(String(40), nullable=False, default="UNINITIALIZED")
    platform_bootstrapped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    first_password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    ilpi_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    onboarding_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    onboarding_completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    atualizado_por: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Perfil(Base):
    __tablename__ = "perfis"
    __table_args__ = (
        UniqueConstraint("chave", "ilpi_id", name="uq_perfil_chave_ilpi"),
        CheckConstraint("escopo IN ('global','ilpi')", name="ck_perfil_escopo"),
        CheckConstraint("situacao IN ('ativo','inativo')", name="ck_perfil_situacao"),
        Index("ix_perfis_ilpi_id", "ilpi_id"),
        Index("ix_perfis_chave", "chave"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    ilpi_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=True, index=True)
    nome: Mapped[str] = mapped_column(String(100), nullable=False)
    chave: Mapped[str] = mapped_column(String(100), nullable=False)
    descricao: Mapped[str] = mapped_column(Text, nullable=True)
    escopo: Mapped[str] = mapped_column(String(10), nullable=False, default="ilpi")
    situacao: Mapped[str] = mapped_column(String(20), nullable=False, default="ativo")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Permissao(Base):
    __tablename__ = "permissoes"
    __table_args__ = (
        UniqueConstraint("chave", name="uq_permissao_chave"),
        UniqueConstraint("modulo", "acao", name="uq_permissao_modulo_acao"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    modulo: Mapped[str] = mapped_column(String(100), nullable=False)
    acao: Mapped[str] = mapped_column(String(100), nullable=False)
    chave: Mapped[str] = mapped_column(String(200), nullable=False)
    descricao: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PerfilPermissao(Base):
    __tablename__ = "perfil_permissoes"
    perfil_id: Mapped[str] = mapped_column(String(36), ForeignKey("perfis.id", ondelete="CASCADE"), primary_key=True)
    permissao_id: Mapped[str] = mapped_column(String(36), ForeignKey("permissoes.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Funcionario(Base):
    __tablename__ = "funcionarios"
    __table_args__ = (
        UniqueConstraint("cpf", "ilpi_id", name="uq_funcionario_cpf_ilpi"),
        UniqueConstraint("ilpi_id", "usuario_id", name="uq_funcionario_ilpi_usuario"),
        CheckConstraint("situacao IN ('ativo','afastado','inativo')", name="ck_funcionario_situacao"),
        Index("ix_funcionarios_ilpi_id", "ilpi_id"),
        Index("ix_funcionarios_usuario_id", "usuario_id"),
        Index("ix_funcionarios_cpf", "cpf"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    ilpi_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=False, index=True)
    usuario_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    cpf: Mapped[str] = mapped_column(String(14), nullable=True)
    telefone: Mapped[str] = mapped_column(String(20), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=True)
    cargo: Mapped[str] = mapped_column(String(100), nullable=True)
    profissao: Mapped[str] = mapped_column(String(100), nullable=True)
    conselho_profissional: Mapped[str] = mapped_column(String(50), nullable=True)
    numero_conselho: Mapped[str] = mapped_column(String(50), nullable=True)
    uf_conselho: Mapped[str] = mapped_column(String(2), nullable=True)
    situacao: Mapped[str] = mapped_column(String(20), nullable=False, default="ativo")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UsuarioIlpiPerfil(Base):
    __tablename__ = "usuario_ilpi_perfis"
    __table_args__ = (
        UniqueConstraint("usuario_id", "ilpi_id", "perfil_id", name="uq_usuario_ilpi_perfil"),
        CheckConstraint("situacao IN ('ativo','inativo')", name="ck_usuario_ilpi_perfil_situacao"),
        Index("ix_usuario_ilpi_perfis_usuario", "usuario_id"),
        Index("ix_usuario_ilpi_perfis_ilpi", "ilpi_id"),
        Index("ix_usuario_ilpi_perfis_perfil", "perfil_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    usuario_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ilpi_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id", ondelete="CASCADE"), nullable=True, index=True)
    perfil_id: Mapped[str] = mapped_column(String(36), ForeignKey("perfis.id", ondelete="CASCADE"), nullable=False, index=True)
    situacao: Mapped[str] = mapped_column(String(20), nullable=False, default="ativo")
    data_inicial: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    data_final: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Auditoria(Base):
    __tablename__ = "auditoria"
    __table_args__ = (
        Index("ix_auditoria_ilpi_entidade", "ilpi_id", "entidade"),
        Index("ix_auditoria_created_at", "created_at"),
        Index("ix_auditoria_usuario", "usuario_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    ilpi_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=True, index=True)
    usuario_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    acao: Mapped[str] = mapped_column(String(100), nullable=False)
    entidade: Mapped[str] = mapped_column(String(100), nullable=True)
    registro_id: Mapped[str] = mapped_column(String(36), nullable=True)
    valores_anteriores: Mapped[str] = mapped_column(Text, nullable=True)  # JSON string, Text para compat SQLite/PG
    valores_posteriores: Mapped[str] = mapped_column(Text, nullable=True)
    ip: Mapped[str] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_token_hash"),
        UniqueConstraint("jti", name="uq_refresh_jti"),
        Index("ix_refresh_user_family", "user_id", "token_family"),
        Index("ix_refresh_expires", "expires_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    jti: Mapped[str] = mapped_column(String(36), nullable=False)
    token_family: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    ilpi_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=True, index=True)
    perfil_id: Mapped[str] = mapped_column(String(36), ForeignKey("perfis.id"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by: Mapped[str] = mapped_column(String(36), ForeignKey("refresh_tokens.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ip: Mapped[str] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str] = mapped_column(Text, nullable=True)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_password_reset_token_hash"),
        Index("ix_pwd_reset_user", "user_id"),
        Index("ix_pwd_reset_expires", "expires_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

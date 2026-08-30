import uuid
from datetime import datetime, date
from sqlalchemy import String, Boolean, DateTime, Date, Text, Integer, Float, ForeignKey, func, UniqueConstraint
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Instituicao(Base):
    __tablename__ = "instituicoes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    razao_social: Mapped[str] = mapped_column(String(255), nullable=False)
    nome_fantasia: Mapped[str] = mapped_column(String(255), nullable=True)
    cnpj: Mapped[str] = mapped_column(String(18), unique=True, nullable=True)
    endereco: Mapped[str] = mapped_column(Text, nullable=True)
    municipio: Mapped[str] = mapped_column(String(255), nullable=True)
    telefone: Mapped[str] = mapped_column(String(20), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=True)
    responsavel_legal: Mapped[str] = mapped_column(String(255), nullable=True)
    responsavel_tecnico: Mapped[str] = mapped_column(String(255), nullable=True)
    capacidade: Mapped[int] = mapped_column(Integer, nullable=True)
    licenca_sanitaria: Mapped[str] = mapped_column(String(100), nullable=True)
    validade_licenca: Mapped[date] = mapped_column(Date, nullable=True)
    fuso_horario: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo")
    situacao: Mapped[str] = mapped_column(String(50), default="ativa")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Residente(Base):
    __tablename__ = "residentes"
    __table_args__ = (UniqueConstraint("cpf", "instituicao_id", name="uq_residente_cpf_inst"),)
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
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=False, index=True)
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
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    instituicao_id: Mapped[str] = mapped_column(String(36), ForeignKey("instituicoes.id"), nullable=False)
    unidade: Mapped[str] = mapped_column(String(100), nullable=True)
    quarto: Mapped[str] = mapped_column(String(50), nullable=False)
    leito: Mapped[str] = mapped_column(String(50), nullable=False)
    capacidade: Mapped[int] = mapped_column(Integer, default=1)
    acessibilidade: Mapped[str] = mapped_column(String(100), nullable=True)
    residente_atual_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=True)
    situacao: Mapped[str] = mapped_column(String(50), default="livre")  # livre, ocupado, reservado, bloqueado, manutencao
    data_ocupacao: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Avaliacao(Base):
    __tablename__ = "avaliacoes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=False, index=True)
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
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=False, index=True)
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
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=False, index=True)
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
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=False, index=True)
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
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=False, index=True)
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
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    residente_id: Mapped[str] = mapped_column(String(36), ForeignKey("residentes.id"), nullable=False, index=True)
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

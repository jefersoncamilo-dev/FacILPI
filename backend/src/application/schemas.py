from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from datetime import date, datetime
import re
from ..domain.validators import validate_cpf, validate_cnpj, validate_cns, validate_password

# ---- User / Auth ----
class UserRegister(BaseModel):
    nome: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8)

    @field_validator("password")
    @classmethod
    def pwd_strength(cls, v):
        ok, msg = validate_password(v)
        if not ok:
            raise ValueError(msg)
        return v

    @field_validator("email")
    @classmethod
    def lower_email(cls, v):
        return v.lower().strip()

class UserLogin(BaseModel):
    email: EmailStr
    password: str
    scope: Optional[str] = None
    ilpi_id: Optional[str] = None
    perfil_id: Optional[str] = None

    @field_validator("email")
    @classmethod
    def lower_email(cls, v):
        return v.lower().strip()

class UserResponse(BaseModel):
    id: str
    nome: str
    email: str
    ativo: bool = True
    is_superuser: bool = False
    exige_troca_senha: bool = False
    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    exige_troca_senha: bool = False

class ContextSelection(BaseModel):
    scope: str
    ilpi_id: Optional[str] = None
    perfil_id: Optional[str] = None

class PrimeiroAcessoUpdate(BaseModel):
    nova_senha: str = Field(..., min_length=8)
    confirmar: str = Field(..., min_length=8)

    @field_validator("nova_senha")
    @classmethod
    def pwd_strength(cls, v):
        ok, msg = validate_password(v)
        if not ok:
            raise ValueError(msg)
        return v

class PasswordUpdate(BaseModel):
    nova_senha: str = Field(..., min_length=8)
    confirmar_senha: str = Field(..., min_length=8)

    @field_validator("nova_senha")
    @classmethod
    def pwd_strength(cls, v):
        ok, msg = validate_password(v)
        if not ok:
            raise ValueError(msg)
        return v

# ---- Instituicao ----
class InstituicaoCreate(BaseModel):
    razao_social: str = Field(..., min_length=2)
    nome_fantasia: Optional[str] = None
    finalidade: Optional[str] = None
    cnpj: Optional[str] = None
    endereco: Optional[str] = None
    municipio: Optional[str] = None
    uf: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[EmailStr] = None
    responsavel_legal: Optional[str] = None
    responsavel_tecnico: Optional[str] = None
    capacidade: Optional[int] = Field(None, ge=0)
    licenca_sanitaria: Optional[str] = None
    validade_licenca: Optional[date] = None
    fuso_horario: Optional[str] = "America/Sao_Paulo"
    situacao: Optional[str] = "ativa"

    @field_validator("cnpj")
    @classmethod
    def validate_cnpj_field(cls, v):
        if v is None or v.strip()=="":
            return v
        if not validate_cnpj(v):
            raise ValueError("CNPJ inválido")
        return re.sub(r"\D","",v)

    @field_validator("uf")
    @classmethod
    def validate_uf_field(cls, v):
        if v is None or v.strip() == "":
            return None
        value = v.strip().upper()
        if value not in UF_VALIDAS:
            raise ValueError("UF inválida")
        return value

class InstituicaoUpdate(BaseModel):
    razao_social: Optional[str] = None
    nome_fantasia: Optional[str] = None
    finalidade: Optional[str] = None
    cnpj: Optional[str] = None
    endereco: Optional[str] = None
    municipio: Optional[str] = None
    uf: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[EmailStr] = None
    responsavel_legal: Optional[str] = None
    responsavel_tecnico: Optional[str] = None
    capacidade: Optional[int] = None
    licenca_sanitaria: Optional[str] = None
    validade_licenca: Optional[date] = None
    fuso_horario: Optional[str] = None
    situacao: Optional[str] = None

    @field_validator("cnpj")
    @classmethod
    def validate_cnpj_field(cls, v):
        if v is None or v.strip() == "":
            return v
        if not validate_cnpj(v):
            raise ValueError("CNPJ inválido")
        return re.sub(r"\D", "", v)

    @field_validator("uf")
    @classmethod
    def validate_uf_field(cls, v):
        if v is None or v.strip() == "":
            return None
        value = v.strip().upper()
        if value not in UF_VALIDAS:
            raise ValueError("UF inválida")
        return value

class InstituicaoResponse(InstituicaoCreate):
    id: str
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class OnboardingStart(BaseModel):
    usar_usuario_atual_como_admin: bool

class UsuarioAdminCreate(BaseModel):
    nome: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    perfil_id: Optional[str] = None

    @field_validator("email")
    @classmethod
    def lower_email(cls, v):
        return v.lower().strip()

class UsuarioAdminResponse(UserResponse):
    senha_temporaria: str

class FuncionarioAdminCreate(BaseModel):
    nome: str = Field(..., min_length=2, max_length=255)
    cpf: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[EmailStr] = None
    cargo: Optional[str] = None
    profissao: Optional[str] = None
    conselho_profissional: Optional[str] = None
    numero_conselho: Optional[str] = None
    uf_conselho: Optional[str] = None

    @field_validator("cpf")
    @classmethod
    def cpf_valid(cls, v):
        if v is None or v.strip() == "":
            return None
        if not validate_cpf(v):
            raise ValueError("CPF inválido")
        return re.sub(r"\D", "", v)

class FuncionarioResponse(FuncionarioAdminCreate):
    id: str
    ilpi_id: str
    usuario_id: Optional[str] = None
    situacao: str = "ativo"
    class Config:
        from_attributes = True

class VincularUsuarioFuncionario(BaseModel):
    usuario_id: str

class UsuarioPerfilAssign(BaseModel):
    perfil_id: str

class PerfilAdminCreate(BaseModel):
    nome: str = Field(..., min_length=2, max_length=100)
    chave: str = Field(..., min_length=2, max_length=100)
    descricao: Optional[str] = None

class PerfilResponse(PerfilAdminCreate):
    id: str
    ilpi_id: Optional[str] = None
    escopo: str
    situacao: str
    class Config:
        from_attributes = True

class PerfilPermissoesUpdate(BaseModel):
    permissoes: list[str]

class ResetPasswordResponse(BaseModel):
    senha_temporaria: str


UF_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}

# ---- Residente ----
class ResidenteCreate(BaseModel):
    instituicao_id: Optional[str] = None
    nome: str = Field(..., min_length=2)
    nome_social: Optional[str] = None
    cpf: Optional[str] = None
    rg: Optional[str] = None
    cns: Optional[str] = None
    data_nascimento: date
    sexo: Optional[str] = None
    foto: Optional[str] = None
    data_admissao: Optional[date] = None
    situacao: Optional[str] = "Em admissao"
    grau_dependencia: Optional[str] = None
    restricoes: Optional[str] = None
    alergias: Optional[str] = None
    necessidades_especiais: Optional[str] = None
    observacoes: Optional[str] = None

    @field_validator("cpf")
    @classmethod
    def cpf_valid(cls, v):
        if v is None or v.strip()=="":
            return v
        if not validate_cpf(v):
            raise ValueError("CPF inválido")
        return re.sub(r"\D","",v)

    @field_validator("cns")
    @classmethod
    def cns_valid(cls, v):
        if v is None or v.strip()=="":
            return v
        if not validate_cns(v):
            raise ValueError("CNS inválido")
        return re.sub(r"\D","",v)

    @field_validator("data_nascimento")
    @classmethod
    def birth_not_future(cls, v):
        if v and v > date.today():
            raise ValueError("Data de nascimento não pode ser futura")
        return v

class ResidenteUpdate(BaseModel):
    nome: Optional[str] = None
    nome_social: Optional[str] = None
    cpf: Optional[str] = None
    rg: Optional[str] = None
    cns: Optional[str] = None
    data_nascimento: Optional[date] = None
    sexo: Optional[str] = None
    foto: Optional[str] = None
    data_admissao: Optional[date] = None
    situacao: Optional[str] = None
    grau_dependencia: Optional[str] = None
    restricoes: Optional[str] = None
    alergias: Optional[str] = None
    necessidades_especiais: Optional[str] = None
    observacoes: Optional[str] = None

class ResidenteResponse(ResidenteCreate):
    id: str
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

# ---- Familiar ----
class FamiliarCreate(BaseModel):
    residente_id: str
    nome: str
    cpf: Optional[str] = None
    parentesco: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[str] = None
    endereco: Optional[str] = None
    tipo_responsabilidade: Optional[str] = None
    autorizacao_acesso: Optional[bool] = False

class FamiliarResponse(FamiliarCreate):
    id: str
    class Config:
        from_attributes = True

# ---- Medicamento ----
class MedicamentoCreate(BaseModel):
    nome: str
    principio_ativo: Optional[str] = None
    apresentacao: Optional[str] = None
    concentracao: Optional[str] = None
    unidade: Optional[str] = None
    lote: Optional[str] = None
    validade: Optional[date] = None
    fabricante: Optional[str] = None
    situacao: Optional[str] = "ativo"

class MedicamentoResponse(MedicamentoCreate):
    id: str
    class Config:
        from_attributes = True

class MedicamentoUpdate(BaseModel):
    nome: Optional[str] = None
    principio_ativo: Optional[str] = None
    apresentacao: Optional[str] = None
    concentracao: Optional[str] = None
    unidade: Optional[str] = None
    lote: Optional[str] = None
    validade: Optional[date] = None
    fabricante: Optional[str] = None
    situacao: Optional[str] = None

# ---- Prescricao ----
class PrescricaoCreate(BaseModel):
    residente_id: str
    medicamento_id: str
    prescritor: str
    dose: str
    via: Optional[str] = None
    frequencia: Optional[str] = None
    horarios: Optional[str] = None
    inicio: date
    termino: Optional[date] = None
    orientacoes: Optional[str] = None
    situacao: Optional[str] = "ativa"

class PrescricaoResponse(PrescricaoCreate):
    id: str
    class Config:
        from_attributes = True

# ---- Tarefa ----
class TarefaCreate(BaseModel):
    residente_id: str
    plano_id: Optional[str] = None
    descricao: str
    horario_previsto: Optional[datetime] = None
    prioridade: Optional[str] = "media"
    responsavel: Optional[str] = None
    situacao: Optional[str] = "Pendente"
    justificativa: Optional[str] = None

class TarefaUpdate(BaseModel):
    descricao: Optional[str] = None
    horario_previsto: Optional[datetime] = None
    horario_realizado: Optional[datetime] = None
    prioridade: Optional[str] = None
    responsavel: Optional[str] = None
    executor: Optional[str] = None
    situacao: Optional[str] = None
    justificativa: Optional[str] = None

class TarefaResponse(TarefaCreate):
    id: str
    horario_realizado: Optional[datetime] = None
    executor: Optional[str] = None
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

# ---- Sinal Vital ----
class SinalVitalCreate(BaseModel):
    residente_id: str
    temperatura: Optional[float] = None
    pressao_sistolica: Optional[int] = None
    pressao_diastolica: Optional[int] = None
    frequencia_cardiaca: Optional[int] = None
    frequencia_respiratoria: Optional[int] = None
    saturacao: Optional[int] = Field(None, ge=0, le=100)
    glicemia: Optional[float] = Field(None, ge=0)
    peso: Optional[float] = Field(None, ge=0)
    profissional: Optional[str] = None
    observacao: Optional[str] = None

class SinalVitalResponse(SinalVitalCreate):
    id: str
    data: Optional[datetime] = None
    class Config:
        from_attributes = True

# ---- Intercorrencia ----
class IntercorrenciaCreate(BaseModel):
    residente_id: str
    tipo: str
    gravidade: Optional[str] = None
    situacao: Optional[str] = "Aberta"
    sbar_situacao: Optional[str] = None
    sbar_contexto: Optional[str] = None
    sbar_avaliacao: Optional[str] = None
    sbar_recomendacao: Optional[str] = None
    providencia: Optional[str] = None
    desfecho: Optional[str] = None
    responsavel: Optional[str] = None

class IntercorrenciaResponse(IntercorrenciaCreate):
    id: str
    data: Optional[datetime] = None
    class Config:
        from_attributes = True

# ---- Alerta ----
class AlertaCreate(BaseModel):
    instituicao_id: Optional[str] = None
    residente_id: Optional[str] = None
    origem: Optional[str] = None
    tipo: str
    gravidade: Optional[str] = None
    mensagem: str
    responsavel: Optional[str] = None
    prazo: Optional[datetime] = None
    situacao: Optional[str] = "Ativo"

class AlertaResponse(AlertaCreate):
    id: str
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

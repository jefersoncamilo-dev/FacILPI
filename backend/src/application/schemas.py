from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from typing import Literal, Optional
from datetime import date, datetime
import re
from decimal import Decimal, InvalidOperation
from typing import Annotated
from unicodedata import normalize
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import AwareDatetime, ConfigDict
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

class UsuarioAdminUpdate(BaseModel):
    nome: Optional[str] = Field(None, min_length=2, max_length=255)

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
    criar_usuario: bool = False
    perfil_id: Optional[str] = None

    @field_validator("cpf")
    @classmethod
    def cpf_valid(cls, v):
        if v is None or v.strip() == "":
            return None
        if not validate_cpf(v):
            raise ValueError("CPF inválido")
        return re.sub(r"\D", "", v)

    @field_validator("uf_conselho")
    @classmethod
    def uf_conselho_valid(cls, v):
        if v is None or v.strip() == "":
            return None
        value = v.strip().upper()
        if value not in UF_VALIDAS:
            raise ValueError("UF do conselho inválida")
        return value

class FuncionarioUpdate(BaseModel):
    nome: Optional[str] = Field(None, min_length=2, max_length=255)
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

    @field_validator("uf_conselho")
    @classmethod
    def uf_conselho_valid(cls, v):
        if v is None or v.strip() == "":
            return None
        value = v.strip().upper()
        if value not in UF_VALIDAS:
            raise ValueError("UF do conselho inválida")
        return value

class FuncionarioResponse(BaseModel):
    id: str
    ilpi_id: str
    usuario_id: Optional[str] = None
    nome: str
    cpf: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[str] = None
    cargo: Optional[str] = None
    profissao: Optional[str] = None
    conselho_profissional: Optional[str] = None
    numero_conselho: Optional[str] = None
    uf_conselho: Optional[str] = None
    situacao: str = "ativo"
    senha_temporaria: Optional[str] = None
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
    # F5A-3A2: grau_dependencia REMOVIDO do contrato de escrita. O campo
    # legado em Residente é congelado (sem escrita, sem sincronização);
    # a fonte oficial é GrauDependencia. Extras enviados são ignorados.
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
    # F5A-3A2: sem grau_dependencia no update (legado congelado).
    restricoes: Optional[str] = None
    alergias: Optional[str] = None
    necessidades_especiais: Optional[str] = None
    observacoes: Optional[str] = None

class ResidenteResponse(ResidenteCreate):
    id: str
    # F5A-3A2: leitura do legado mantida por compatibilidade; escrita
    # bloqueada (ausente em Create/Update). Fonte oficial: GrauDependencia.
    grau_dependencia: Optional[str] = None
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

class FamiliarUpdate(BaseModel):
    # F5A-2B: update nunca controla tenant (ilpi_id/instituicao_id ausentes
    # por construção) e nunca transfere vínculo (residente_id imutável por
    # decisão oficial; eventual troca exige fluxo próprio, auditável).
    nome: Optional[str] = None
    cpf: Optional[str] = None
    parentesco: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[str] = None
    endereco: Optional[str] = None
    tipo_responsabilidade: Optional[str] = None
    autorizacao_acesso: Optional[bool] = None

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

# ---- C5: independent contracts; legacy schemas above remain unchanged ----
C5Text = Annotated[str, Field(min_length=1, max_length=255)]
C5ShortText = Annotated[str, Field(min_length=1, max_length=50)]


class C5Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class C5MedicamentoCreate(C5Input):
    nome: C5Text
    principio_ativo: Optional[C5Text] = None
    apresentacao: Optional[Annotated[str, Field(min_length=1, max_length=100)]] = None
    concentracao: Optional[Annotated[str, Field(min_length=1, max_length=100)]] = None
    unidade: Optional[C5ShortText] = None
    fabricante: Optional[C5Text] = None
    situacao: Literal["ativo", "inativo"] = "ativo"


class C5MedicamentoPatch(C5Input):
    nome: Optional[C5Text] = None
    principio_ativo: Optional[C5Text] = None
    apresentacao: Optional[Annotated[str, Field(min_length=1, max_length=100)]] = None
    concentracao: Optional[Annotated[str, Field(min_length=1, max_length=100)]] = None
    unidade: Optional[C5ShortText] = None
    fabricante: Optional[C5Text] = None
    situacao: Optional[Literal["ativo", "inativo"]] = None

    @model_validator(mode="after")
    def required_when_present(self):
        for key in ("nome", "situacao"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f"{key} nao pode ser nulo")
        return self


class C5PrescricaoCreate(C5Input):
    residente_id: C5ShortText
    medicamento_id: C5ShortText
    prescritor_nome: C5Text
    prescritor_categoria: C5ShortText
    prescritor_conselho: Optional[C5ShortText] = None
    prescritor_numero: Optional[C5ShortText] = None
    prescritor_uf: Optional[Annotated[str, Field(min_length=2, max_length=2)]] = None
    dose: C5ShortText
    unidade: C5ShortText
    via: C5ShortText
    frequencia: Optional[C5ShortText] = None
    inicio: date
    termino: Optional[date] = None
    orientacoes: Optional[str] = None

    @field_validator("dose")
    @classmethod
    def positive_dose(cls, value):
        try:
            number = Decimal(value)
        except InvalidOperation:
            raise ValueError("Dose deve ser decimal positivo")
        if not number.is_finite() or number <= 0:
            raise ValueError("Dose deve ser decimal positivo")
        return value

    @field_validator("frequencia")
    @classmethod
    def supported_frequency(cls, value):
        if value:
            text = normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
            if re.search(r"\b(prn|sos)\b|se\s+necessari|\d\s*/\s*\d|\b(?:a\s+)?cada\s+\d|\b\d+\s*(?:h|horas?)\b", text):
                raise ValueError("PRN/SOS e intervalos nao suportados; informe horarios fixos na ativacao")
        return value

    @model_validator(mode="after")
    def clinical_fields(self):
        council = (self.prescritor_conselho, self.prescritor_numero, self.prescritor_uf)
        if any(council) and not all(council):
            raise ValueError("Informe conselho, numero e UF juntos")
        if self.termino is not None and self.termino < self.inicio:
            raise ValueError("Termino anterior ao inicio")
        if self.termino == date.max:
            raise ValueError("Termino fora do intervalo suportado")
        return self


class C5Ativacao(C5Input):
    horarios: list[Annotated[str, Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")]] = Field(min_length=1, max_length=1440)
    timezone: Annotated[str, Field(min_length=1, max_length=100)]
    vigencia_inicio: AwareDatetime
    vigencia_fim: Optional[AwareDatetime] = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Timezone IANA indisponivel ou invalida")
        return value

    @model_validator(mode="after")
    def valid_schedule(self):
        if len(set(self.horarios)) != len(self.horarios):
            raise ValueError("Horarios duplicados")
        if self.vigencia_fim is not None and self.vigencia_fim <= self.vigencia_inicio:
            raise ValueError("Fim deve ser posterior ao inicio")
        return self


class C5Motivo(C5Input):
    motivo: Annotated[str, Field(min_length=1)]


class C5Substituicao(C5Motivo):
    prescricao: C5PrescricaoCreate
    programacao: C5Ativacao


class C5Resultado(C5Input):
    resultado: Literal["administrada", "recusada", "omitida"]
    ocorrido_em: AwareDatetime
    quantidade_realizada: Optional[Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=4)]] = None
    justificativa: Optional[Annotated[str, Field(min_length=1)]] = None
    observacao: Optional[str] = None

    @model_validator(mode="after")
    def outcome_fields(self):
        if self.resultado == "administrada" and self.quantidade_realizada is None:
            raise ValueError("Quantidade realizada obrigatoria")
        if self.resultado != "administrada" and not self.justificativa:
            raise ValueError("Justificativa obrigatoria para recusa ou omissao")
        return self


class C5AdministracaoCreate(C5Resultado):
    dose_prevista_id: C5ShortText


class C5Estorno(C5Motivo):
    substituto: Optional[C5Resultado] = None


class C5MedicamentoResponse(C5MedicamentoCreate):
    model_config = ConfigDict(from_attributes=True, extra="ignore")
    id: str
    ilpi_id: str
    autor_id: Optional[str] = None
    created_at: datetime


class C5ProgramacaoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ilpi_id: str
    residente_id: str
    prescricao_id: str
    horarios: list[str]
    timezone: str
    vigencia_inicio: datetime
    vigencia_fim: Optional[datetime]
    cobertura_ate: Optional[datetime]
    situacao: str
    autor_id: str
    created_at: datetime


class C5PrescricaoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ilpi_id: str
    residente_id: str
    medicamento_id: str
    autor_id: Optional[str]
    prescritor: str
    prescritor_nome: Optional[str]
    prescritor_categoria: Optional[str]
    prescritor_conselho: Optional[str]
    prescritor_numero: Optional[str]
    prescritor_uf: Optional[str]
    dose: str
    unidade: Optional[str]
    via: Optional[str]
    frequencia: Optional[str]
    inicio: date
    termino: Optional[date]
    orientacoes: Optional[str]
    medicamento_snapshot: Optional[dict]
    situacao: str
    anterior_id: Optional[str]
    motivo_versao: Optional[str]
    ativado_por: Optional[str]
    ativado_em: Optional[datetime]
    suspenso_por: Optional[str]
    suspenso_em: Optional[datetime]
    motivo_suspensao: Optional[str]
    encerrado_por: Optional[str]
    encerrado_em: Optional[datetime]
    motivo_encerramento: Optional[str]
    substituido_em: Optional[datetime]
    created_at: datetime
    programacao: Optional[C5ProgramacaoResponse] = None


class C5DoseResponse(BaseModel):
    id: str
    ilpi_id: str
    residente_id: str
    prescricao_id: str
    programacao_id: str
    previsto_em: datetime
    situacao: str
    pendente: bool
    cancelado_em: Optional[datetime]
    cancelado_por: Optional[str]
    motivo_cancelamento: Optional[str]
    created_at: datetime


class C5AdministracaoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ilpi_id: str
    residente_id: str
    prescricao_id: str
    dose_prevista_id: str
    resultado: str
    ocorrido_em: datetime
    registrado_em: datetime
    executor_id: str
    quantidade_realizada: Optional[Decimal] = None
    justificativa: Optional[str] = None
    observacao: Optional[str] = None
    estornado_em: Optional[datetime] = None
    estornado_por: Optional[str] = None
    motivo_estorno: Optional[str] = None
    substitui_id: Optional[str] = None
    substituto: Optional["C5AdministracaoResponse"] = None

    @field_validator("quantidade_realizada", mode="before")
    @classmethod
    def _normalize_qty(cls, v):
        if isinstance(v, Decimal):
            # Strip trailing zeros but keep at least one decimal normalization via normalize.
            # Quantize to remove fixed scale 4 from Numeric(14,4).
            try:
                normalized = v.normalize()
                # normalize() may use exponent; force plain fixed string then back to Decimal
                return Decimal(format(normalized, "f"))
            except Exception:
                return v
        return v


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

# ---- Sinal Vital (C.3: registro mínimo seguro, histórico imutável) ----
# Modelo colunar mantido (temperatura, pressao_*, frequencias, saturacao,
# glicemia, peso). Unidades implícitas por campo. Correção = novo INSERT;
# sem PUT, sem DELETE. Tenant/autoria vêm da sessão; o payload nunca decide.
class SinalVitalCreate(BaseModel):
    residente_id: str
    temperatura: Optional[float] = None
    pressao_sistolica: Optional[int] = Field(None, ge=0)
    pressao_diastolica: Optional[int] = Field(None, ge=0)
    frequencia_cardiaca: Optional[int] = Field(None, ge=0)
    frequencia_respiratoria: Optional[int] = Field(None, ge=0)
    saturacao: Optional[int] = Field(None, ge=0, le=100)
    glicemia: Optional[float] = Field(None, ge=0)
    peso: Optional[float] = Field(None, ge=0)
    data: Optional[datetime] = None
    observacao: Optional[str] = None

    @model_validator(mode="after")
    def pelo_menos_um_sinal(self):
        vitais = (
            self.temperatura,
            self.pressao_sistolica,
            self.pressao_diastolica,
            self.frequencia_cardiaca,
            self.frequencia_respiratoria,
            self.saturacao,
            self.glicemia,
            self.peso,
        )
        if all(v is None for v in vitais):
            raise ValueError("Informe pelo menos um sinal vital")
        return self

class SinalVitalResponse(SinalVitalCreate):
    id: str
    profissional: Optional[str] = None
    data: Optional[datetime] = None
    class Config:
        from_attributes = True

# ---- Intercorrencia ----
class IntercorrenciaCreate(BaseModel):
    residente_id: str = Field(min_length=1, max_length=36)
    tipo: str = Field(min_length=1, max_length=100)
    gravidade: Literal["leve", "moderada", "grave"]
    situacao: Literal["aberta"] = "aberta"
    sbar_situacao: Optional[str] = None
    sbar_contexto: Optional[str] = None
    sbar_avaliacao: Optional[str] = None
    sbar_recomendacao: Optional[str] = None
    providencia: Optional[str] = None
    desfecho: None = None

    @field_validator("tipo")
    @classmethod
    def tipo_nao_vazio(cls, value):
        if not value.strip():
            raise ValueError("Tipo obrigatorio")
        return value.strip()


class IntercorrenciaUpdate(BaseModel):
    tipo: Optional[str] = Field(default=None, min_length=1, max_length=100)
    gravidade: Optional[Literal["leve", "moderada", "grave"]] = None
    sbar_situacao: Optional[str] = None
    sbar_contexto: Optional[str] = None
    sbar_avaliacao: Optional[str] = None
    sbar_recomendacao: Optional[str] = None
    providencia: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def correcao_controlada(cls, data):
        if isinstance(data, dict):
            if {"residente_id", "situacao", "desfecho"} & data.keys():
                raise ValueError("Residente imutavel; encerramento exige operacao explicita")
            for key in ("tipo", "gravidade"):
                if key in data and (data[key] is None or not str(data[key]).strip()):
                    raise ValueError(f"{key} nao pode ser vazio")
        return data


class IntercorrenciaEncerrar(BaseModel):
    desfecho: str = Field(min_length=1)

    @field_validator("desfecho")
    @classmethod
    def desfecho_nao_vazio(cls, value):
        if not value.strip():
            raise ValueError("Desfecho obrigatorio")
        return value.strip()

class IntercorrenciaResponse(IntercorrenciaCreate):
    id: str
    situacao: Literal["aberta", "encerrada"]
    desfecho: Optional[str] = None
    responsavel: Optional[str] = None
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

# ---- Documento (F5A-2C) ----
class DocumentoCreate(BaseModel):
    residente_id: str
    tipo: str
    numero: Optional[str] = None
    arquivo: Optional[str] = None
    validade: Optional[date] = None
    obrigatorio: Optional[bool] = False
    responsavel_envio: Optional[str] = None

class DocumentoUpdate(BaseModel):
    tipo: Optional[str] = None
    numero: Optional[str] = None
    arquivo: Optional[str] = None
    validade: Optional[date] = None
    obrigatorio: Optional[bool] = None
    situacao: Optional[str] = None
    responsavel_envio: Optional[str] = None

class DocumentoResponse(BaseModel):
    id: str
    residente_id: Optional[str] = None
    tipo: str
    numero: Optional[str] = None
    arquivo: Optional[str] = None
    validade: Optional[date] = None
    obrigatorio: Optional[bool] = None
    situacao: Optional[str] = None
    responsavel_envio: Optional[str] = None
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True


# ---- QuartoLeito (F5A-2D) ----
class QuartoLeitoCreate(BaseModel):
    unidade: Optional[str] = None
    quarto: str = Field(..., min_length=1, max_length=50)
    leito: str = Field(..., min_length=1, max_length=50)
    acessibilidade: Optional[str] = None
    situacao: Optional[str] = "livre"

    @field_validator("situacao")
    @classmethod
    def validate_situacao(cls, v):
        allowed = {"livre", "reservado", "bloqueado", "manutencao", "inativo"}
        if v not in allowed:
            raise ValueError(f"situacao deve ser uma de: {sorted(allowed)}")
        return v

class QuartoLeitoUpdate(BaseModel):
    unidade: Optional[str] = None
    quarto: Optional[str] = Field(None, min_length=1, max_length=50)
    leito: Optional[str] = Field(None, min_length=1, max_length=50)
    acessibilidade: Optional[str] = None
    situacao: Optional[str] = None

    @field_validator("situacao")
    @classmethod
    def validate_situacao(cls, v):
        if v is None:
            return v
        allowed = {"livre", "reservado", "bloqueado", "manutencao", "inativo"}
        if v not in allowed:
            raise ValueError(f"situacao deve ser uma de: {sorted(allowed)}")
        return v

class QuartoLeitoResponse(BaseModel):
    id: str
    instituicao_id: str
    unidade: Optional[str] = None
    quarto: str
    leito: str
    capacidade: int
    acessibilidade: Optional[str] = None
    residente_atual_id: Optional[str] = None
    situacao: str
    data_ocupacao: Optional[datetime] = None
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class QuartoLeitoAlocar(BaseModel):
    residente_id: str

class QuartoLeitoLiberar(BaseModel):
    pass

class TransferenciaRequest(BaseModel):
    residente_id: str
    novo_leito_id: str
    motivo: Optional[str] = None


# ---- OcupacaoHistorico (F5A-2D) ----
class OcupacaoHistoricoResponse(BaseModel):
    id: str
    instituicao_id: str
    residente_id: str
    quarto_leito_id: str
    data_entrada: datetime
    data_saida: Optional[datetime] = None
    tipo_movimentacao: str
    motivo: Optional[str] = None
    usuario_id: str
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True


# ---- Ausencia (F5A-2D) ----
class AusenciaCreate(BaseModel):
    residente_id: str
    quarto_leito_id: Optional[str] = None
    tipo: str
    motivo: str = Field(..., min_length=1)
    observacoes: Optional[str] = None

    @field_validator("tipo")
    @classmethod
    def validate_tipo(cls, v):
        allowed = {"hospitalizacao", "saida_temporaria"}
        if v not in allowed:
            raise ValueError(f"tipo deve ser uma de: {sorted(allowed)}")
        return v

class AusenciaUpdate(BaseModel):
    quarto_leito_id: Optional[str] = None
    motivo: Optional[str] = None
    observacoes: Optional[str] = None

class AusenciaEncerrar(BaseModel):
    pass

class AusenciaResponse(BaseModel):
    id: str
    instituicao_id: str
    residente_id: str
    quarto_leito_id: Optional[str] = None
    tipo: str
    data_inicio: datetime
    data_fim: Optional[datetime] = None
    motivo: str
    observacoes: Optional[str] = None
    usuario_id: str
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True


# ---- Avaliacao (F5A-3A1) ----
class AvaliacaoCreate(BaseModel):
    residente_id: str
    tipo: str = Field(..., min_length=1)
    instrumento: Optional[str] = None
    respostas: Optional[str] = None
    pontuacao: Optional[float] = None
    classificacao: Optional[str] = None
    data: Optional[datetime] = None
    validade: Optional[date] = None
    observacoes: Optional[str] = None


class AvaliacaoUpdate(BaseModel):
    instrumento: Optional[str] = None
    respostas: Optional[str] = None
    pontuacao: Optional[float] = None
    classificacao: Optional[str] = None
    validade: Optional[date] = None
    observacoes: Optional[str] = None


class AvaliacaoResponse(AvaliacaoCreate):
    id: str
    profissional: Optional[str] = None
    data: Optional[datetime] = None
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True


# ---- GrauDependencia (F5A-3A2: fonte única oficial) ----
GRAU_CLASSIFICACOES = ("Grau I", "Grau II", "Grau III")

class GrauDependenciaCreate(BaseModel):
    # Confirmação humana explícita. confirmado_por/ilpi_id NUNCA vêm do
    # payload: derivados de SecurityContext. origem=migracao rejeitada.
    residente_id: str
    classificacao: Literal["Grau I", "Grau II", "Grau III"]
    origem: Literal["avaliacao", "manual"]
    avaliacao_id: Optional[str] = None
    validade: Optional[date] = None
    justificativa: str = Field(..., min_length=1)

    @field_validator("justificativa")
    @classmethod
    def justificativa_nao_vazia(cls, v):
        texto = (v or "").strip()
        if not texto:
            raise ValueError("Justificativa obrigatória")
        return texto

    @model_validator(mode="after")
    def coerencia_origem_avaliacao(self):
        if self.origem == "avaliacao" and not self.avaliacao_id:
            raise ValueError("origem=avaliacao exige avaliacao_id")
        if self.origem == "manual" and self.avaliacao_id:
            raise ValueError("origem=manual não aceita avaliacao_id")
        return self


class GrauDependenciaRevogar(BaseModel):
    motivo: str = Field(..., min_length=1)

    @field_validator("motivo")
    @classmethod
    def motivo_nao_vazio(cls, v):
        texto = (v or "").strip()
        if not texto:
            raise ValueError("Motivo da revogação obrigatório")
        return texto


class GrauDependenciaResponse(BaseModel):
    id: str
    ilpi_id: str
    residente_id: str
    classificacao: str
    sugestao_classificacao: Optional[str] = None
    origem: str
    avaliacao_id: Optional[str] = None
    justificativa: str
    confirmado_por: Optional[str] = None
    confirmado_em: Optional[datetime] = None
    validade: Optional[date] = None
    situacao: str
    superseded_by: Optional[str] = None
    motivo_revogacao: Optional[str] = None
    class Config:
        from_attributes = True


# ---- PAIS / Plano de Cuidados (D.1) ----
# Fonte única: planos_cuidados + pais_necessidades/metas/intervencoes.
# Tenant e autoria vêm da sessão; payload nunca decide ilpi/autor.
class D1Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PlanoCuidadosCreate(D1Input):
    residente_id: str
    data_inicial: date
    data_final: Optional[date] = None
    objetivos: Optional[str] = None

    @model_validator(mode="after")
    def datas_coerentes(self):
        if self.data_final is not None and self.data_final < self.data_inicial:
            raise ValueError("data_final anterior a data_inicial")
        return self


class PlanoCuidadosPatch(D1Input):
    # Edição controlada de rascunho/em_elaboracao. situacao aqui só permite
    # a promoção rascunho -> em_elaboracao; demais transições são ações.
    data_inicial: Optional[date] = None
    data_final: Optional[date] = None
    objetivos: Optional[str] = None
    situacao: Optional[Literal["em_elaboracao"]] = None


class FuncionarioRef(D1Input):
    funcionario_id: Annotated[str, Field(min_length=1, max_length=36)]


class MotivoEncerramento(D1Input):
    motivo: Annotated[str, Field(min_length=1)]
    funcionario_id: Annotated[str, Field(min_length=1, max_length=36)]


class NovaVersao(D1Input):
    motivo: Annotated[str, Field(min_length=1)]


class NecessidadeCreate(D1Input):
    descricao: Annotated[str, Field(min_length=1)]
    categoria: Optional[Annotated[str, Field(max_length=100)]] = None
    gravidade: Optional[Annotated[str, Field(max_length=50)]] = None
    evidencias: Optional[str] = None
    origem: Literal["manual", "avaliacao", "grau_dependencia", "intercorrencia"] = "manual"
    referencia_id: Optional[str] = None

    @model_validator(mode="after")
    def referencia_coerente(self):
        if self.origem == "manual" and self.referencia_id:
            raise ValueError("origem=manual não aceita referencia_id")
        if self.origem != "manual" and not self.referencia_id:
            raise ValueError("origem referenciada exige referencia_id")
        return self


class NecessidadePatch(D1Input):
    descricao: Optional[Annotated[str, Field(min_length=1)]] = None
    categoria: Optional[Annotated[str, Field(max_length=100)]] = None
    gravidade: Optional[Annotated[str, Field(max_length=50)]] = None
    evidencias: Optional[str] = None
    situacao: Optional[Literal["ativa", "inativa"]] = None


class MetaCreate(D1Input):
    descricao: Annotated[str, Field(min_length=1)]
    indicador: Optional[Annotated[str, Field(max_length=255)]] = None
    valor_esperado: Optional[Annotated[str, Field(max_length=255)]] = None
    prazo: Optional[date] = None
    responsavel_funcionario_id: Optional[str] = None


class MetaPatch(D1Input):
    descricao: Optional[Annotated[str, Field(min_length=1)]] = None
    indicador: Optional[Annotated[str, Field(max_length=255)]] = None
    valor_esperado: Optional[Annotated[str, Field(max_length=255)]] = None
    prazo: Optional[date] = None
    responsavel_funcionario_id: Optional[str] = None
    situacao: Optional[Literal["ativa", "inativa"]] = None


class IntervencaoCreate(D1Input):
    descricao: Annotated[str, Field(min_length=1)]
    necessidade_id: Optional[str] = None
    frequencia: Optional[Annotated[str, Field(max_length=100)]] = None
    horario: Optional[Annotated[str, Field(max_length=20)]] = None
    perfil_responsavel: Optional[Annotated[str, Field(max_length=100)]] = None
    profissional_designado_id: Optional[str] = None
    prioridade: Optional[Annotated[str, Field(max_length=20)]] = None
    instrucoes: Optional[str] = None


class IntervencaoPatch(D1Input):
    descricao: Optional[Annotated[str, Field(min_length=1)]] = None
    necessidade_id: Optional[str] = None
    frequencia: Optional[Annotated[str, Field(max_length=100)]] = None
    horario: Optional[Annotated[str, Field(max_length=20)]] = None
    perfil_responsavel: Optional[Annotated[str, Field(max_length=100)]] = None
    profissional_designado_id: Optional[str] = None
    prioridade: Optional[Annotated[str, Field(max_length=20)]] = None
    instrucoes: Optional[str] = None
    situacao: Optional[Literal["ativa", "inativa"]] = None


class NecessidadeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ilpi_id: str
    plano_id: str
    categoria: Optional[str] = None
    descricao: str
    gravidade: Optional[str] = None
    evidencias: Optional[str] = None
    origem: str
    situacao: str
    created_at: Optional[datetime] = None


class MetaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ilpi_id: str
    plano_id: str
    descricao: str
    indicador: Optional[str] = None
    valor_esperado: Optional[str] = None
    prazo: Optional[date] = None
    responsavel_funcionario_id: Optional[str] = None
    situacao: str
    created_at: Optional[datetime] = None


class IntervencaoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ilpi_id: str
    plano_id: str
    necessidade_id: Optional[str] = None
    descricao: str
    frequencia: Optional[str] = None
    horario: Optional[str] = None
    perfil_responsavel: Optional[str] = None
    profissional_designado_id: Optional[str] = None
    prioridade: Optional[str] = None
    instrucoes: Optional[str] = None
    situacao: str
    created_at: Optional[datetime] = None


class PlanoCuidadosResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ilpi_id: str
    residente_id: str
    versao: int
    objetivos: Optional[str] = None
    data_inicial: date
    data_final: Optional[date] = None
    situacao: str
    autor_id: Optional[str] = None
    revisor_funcionario_id: Optional[str] = None
    aprovador_funcionario_id: Optional[str] = None
    revisado_em: Optional[datetime] = None
    aprovado_em: Optional[datetime] = None
    motivo_encerramento: Optional[str] = None
    encerrado_em: Optional[datetime] = None
    anterior_id: Optional[str] = None
    motivo_versao: Optional[str] = None
    superseded_by: Optional[str] = None
    lock_version: int = 0
    created_at: Optional[datetime] = None
    necessidades: list[NecessidadeResponse] = []
    metas: list[MetaResponse] = []
    intervencoes: list[IntervencaoResponse] = []


# ---- Rotina assistencial (D.2) ----
# Programação nasce SOMENTE de ação humana explícita sobre Intervenção do
# PAIS vigente. Tenant/autor/executor vêm da sessão; payload nunca decide.
class D2Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProgramacaoCreate(D2Input):
    plano_id: str
    intervencao_id: str
    horarios: list[Annotated[str, Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")]] = Field(min_length=1, max_length=48)
    timezone: Annotated[str, Field(min_length=1, max_length=100)]
    vigencia_inicio: AwareDatetime
    vigencia_fim: Optional[AwareDatetime] = None
    perfil_responsavel: Optional[Annotated[str, Field(max_length=100)]] = None
    funcionario_designado_id: Optional[str] = None
    prioridade: Literal["baixa", "media", "alta"] = "media"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Timezone IANA indisponivel ou invalida")
        return value

    @model_validator(mode="after")
    def valid_schedule(self):
        if len(set(self.horarios)) != len(self.horarios):
            raise ValueError("Horarios duplicados")
        if self.vigencia_fim is not None and self.vigencia_fim <= self.vigencia_inicio:
            raise ValueError("Fim deve ser posterior ao inicio")
        return self


class ProgramacaoPatch(D2Input):
    # Edição controlada da programacao ativa. horarios/timezone são
    # imutáveis após a criação (nova programação em vez de reescrita).
    vigencia_fim: Optional[AwareDatetime] = None
    perfil_responsavel: Optional[Annotated[str, Field(max_length=100)]] = None
    funcionario_designado_id: Optional[str] = None
    prioridade: Optional[Literal["baixa", "media", "alta"]] = None


class ProgramacaoCancel(D2Input):
    motivo: Annotated[str, Field(min_length=1)]


class OcorrenciaCancel(D2Input):
    motivo: Annotated[str, Field(min_length=1)]


class ExecucaoCreate(D2Input):
    ocorrencia_id: str
    resultado: Literal["executada", "recusada", "omitida"]
    ocorrido_em: AwareDatetime
    observacao: Optional[str] = None
    justificativa: Optional[Annotated[str, Field(min_length=1)]] = None

    @model_validator(mode="after")
    def outcome_fields(self):
        if self.resultado != "executada" and not self.justificativa:
            raise ValueError("Justificativa obrigatoria para recusa ou omissao")
        return self


class ExecucaoEstorno(D2Input):
    motivo: Annotated[str, Field(min_length=1)]
    substituto: Optional[ExecucaoCreate] = None


class ProgramacaoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ilpi_id: str
    residente_id: str
    plano_id: str
    intervencao_id: str
    autor_id: str
    horarios: list[str]
    timezone: str
    vigencia_inicio: datetime
    vigencia_fim: Optional[datetime] = None
    cobertura_ate: Optional[datetime] = None
    perfil_responsavel: Optional[str] = None
    funcionario_designado_id: Optional[str] = None
    prioridade: str
    situacao: str
    lock_version: int = 0
    created_at: Optional[datetime] = None


class OcorrenciaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ilpi_id: str
    residente_id: str
    plano_id: str
    intervencao_id: str
    programacao_id: str
    previsto_em: datetime
    situacao: str
    pendente: bool = True
    cancelado_em: Optional[datetime] = None
    cancelado_por: Optional[str] = None
    motivo_cancelamento: Optional[str] = None
    created_at: Optional[datetime] = None


class ExecucaoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ilpi_id: str
    residente_id: str
    programacao_id: str
    ocorrencia_id: str
    resultado: str
    ocorrido_em: datetime
    registrado_em: datetime
    executor_id: str
    observacao: Optional[str] = None
    justificativa: Optional[str] = None
    estornado_em: Optional[datetime] = None
    estornado_por: Optional[str] = None
    motivo_estorno: Optional[str] = None
    substitui_id: Optional[str] = None
    substituto: Optional["ExecucaoResponse"] = None
    created_at: Optional[datetime] = None


class PlantaoItem(BaseModel):
    origem: Literal["cuidado", "medicacao", "intercorrencia"]
    registro_id: str
    residente_id: str
    descricao: str
    previsto_em: Optional[datetime] = None
    prioridade: Optional[str] = None

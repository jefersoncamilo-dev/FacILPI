export interface Funcionario {
  id: string
  ilpi_id: string
  usuario_id: string | null
  nome: string
  cpf: string | null
  telefone: string | null
  email: string | null
  cargo: string | null
  profissao: string | null
  conselho_profissional: string | null
  numero_conselho: string | null
  uf_conselho: string | null
  situacao: 'ativo' | 'afastado' | 'inativo'
  senha_temporaria?: string | null
}

export interface FuncionarioCreate {
  nome: string
  cpf?: string
  telefone?: string
  email?: string
  cargo?: string
  profissao?: string
  conselho_profissional?: string
  numero_conselho?: string
  uf_conselho?: string
  criar_usuario?: boolean
  perfil_id?: string
}

export interface FuncionarioUpdate {
  nome?: string
  cpf?: string
  telefone?: string
  email?: string
  cargo?: string
  profissao?: string
  conselho_profissional?: string
  numero_conselho?: string
  uf_conselho?: string
}

export interface User {
  id: string
  nome: string
  email: string
  ativo: boolean
  is_superuser: boolean
  exige_troca_senha: boolean
}

export interface UsuarioAdminCreate {
  nome: string
  email: string
  perfil_id?: string
}

export interface UsuarioAdminUpdate {
  nome?: string
}

export interface Perfil {
  id: string
  ilpi_id: string | null
  nome: string
  chave: string
  descricao: string | null
  escopo: 'global' | 'ilpi'
  situacao: 'ativo' | 'inativo'
}

export interface PerfilAdminCreate {
  nome: string
  chave: string
  descricao?: string
}

export interface Permissao {
  id: string
  modulo: string
  acao: string
  chave: string
  descricao: string | null
}

export interface ResetPasswordResponse {
  senha_temporaria: string
}

export const UF_VALIDAS = [
  'AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS',
  'MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC',
  'SP','SE','TO',
] as const

export const REGULATED_PROFESSIONS = [
  'assistente social',
  'enfermeiro',
  'farmaceutico',
  'farmacêutico',
  'fisioterapeuta',
  'fonoaudiologo',
  'fonoaudiólogo',
  'medico',
  'médico',
  'nutricionista',
  'psicologo',
  'psicólogo',
  'terapeuta ocupacional',
] as const

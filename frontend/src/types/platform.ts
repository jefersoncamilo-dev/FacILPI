import { TOKEN_KEY, decodeJwt } from './context'
import type { ActiveContext } from './context'

/**
 * Espelha InstituicaoCreate/InstituicaoUpdate/InstituicaoResponse
 * (backend/src/application/schemas.py) e o roteador de plataforma
 * (backend/src/application/platform.py).
 *
 * `situacao` NUNCA é enviada pelo cliente: nasce ILPI_RASCUNHO no servidor e só
 * muda por ativar/inativar, que têm validação própria. O backend descarta o
 * campo no PUT.
 */

export const SITUACAO_RASCUNHO = 'ILPI_RASCUNHO'
export const SITUACAO_ATIVA = 'ATIVA'
export const SITUACAO_INATIVA = 'INATIVA'

export interface Instituicao {
  id: string
  razao_social: string
  nome_fantasia?: string | null
  finalidade?: string | null
  cnpj?: string | null
  endereco?: string | null
  municipio?: string | null
  uf?: string | null
  telefone?: string | null
  email?: string | null
  responsavel_legal?: string | null
  responsavel_tecnico?: string | null
  capacidade?: number | null
  licenca_sanitaria?: string | null
  validade_licenca?: string | null
  fuso_horario?: string | null
  situacao: string
  created_at?: string | null
}

export interface InstituicaoPayload {
  razao_social: string
  nome_fantasia?: string
  finalidade?: string
  cnpj?: string
  endereco?: string
  municipio?: string
  uf?: string
  telefone?: string
  email?: string
  responsavel_legal?: string
  responsavel_tecnico?: string
  capacidade?: number
}

export interface PrimeiroGestorPayload {
  nome: string
  email: string
  cpf?: string
  telefone?: string
  cargo?: string
}

/** Resposta de UsuarioAdminResponse. `senha_temporaria` chega uma única vez. */
export interface PrimeiroGestorCriado {
  id: string
  nome: string
  email: string
  ativo: boolean
  is_superuser: boolean
  exige_troca_senha: boolean
  senha_temporaria: string
}

/**
 * O CHECK de `instituicoes.situacao` aceita 'ativa' e 'ATIVA' — grafias
 * diferentes convivem no banco. Comparar sem normalizar faria a mesma
 * instituição aparecer ora ativa, ora não.
 */
function normalizar(situacao?: string | null): string {
  return (situacao || '').trim().toUpperCase()
}

export function ehAtiva(situacao?: string | null): boolean {
  return normalizar(situacao) === SITUACAO_ATIVA
}

export function ehInativa(situacao?: string | null): boolean {
  return normalizar(situacao) === SITUACAO_INATIVA
}

export function rotuloSituacao(situacao?: string | null): string {
  const valor = normalizar(situacao)
  if (valor === SITUACAO_ATIVA) return 'Ativa'
  if (valor === SITUACAO_INATIVA) return 'Inativa'
  if (valor === SITUACAO_RASCUNHO || valor === 'RASCUNHO') return 'Em configuração'
  return situacao || '—'
}

/**
 * Discriminador de ROTEAMENTO — não de autorização. O backend segue exigindo
 * platform_superuser em escopo global em toda rota de /api/platform.
 *
 * As duas condições são necessárias. `contextFromToken` devolve
 * `{scope: 'global'}` como fallback para QUALQUER token que não seja de ILPI,
 * inclusive o de um gestor em primeiro acesso — que recebe `scope: None` do
 * backend. Sem checar `is_superuser`, esse gestor entraria na Central.
 */
export function ehOperadorDaPlataforma(activeContext: ActiveContext | null): boolean {
  if (activeContext?.scope !== 'global') return false
  return decodeJwt(localStorage.getItem(TOKEN_KEY))?.is_superuser === true
}

/**
 * Espelho de `UF_VALIDAS` (backend/src/application/schemas.py:326). O backend
 * normaliza com `.strip().upper()` antes de comparar, então só a sigla vale —
 * "Paraná" vira "PARANÁ" e não pertence ao conjunto.
 *
 * Ordenado alfabeticamente para a lista; o conjunto é o mesmo do servidor.
 */
export const UF_VALIDAS = [
  'AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS',
  'MT', 'PA', 'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RO', 'RR', 'RS', 'SC',
  'SE', 'SP', 'TO',
] as const

export function ufEhValida(valor: string): boolean {
  return (UF_VALIDAS as readonly string[]).includes(valor.trim().toUpperCase())
}

/**
 * Espelho de `validate_cnpj` (backend/src/domain/validators.py:21).
 *
 * Existe para evitar uma ida ao servidor que já se sabe perdida, NÃO para
 * substituir o backend, que continua sendo a autoridade: o POST segue enviando
 * o que o usuário digitou e um 422 do servidor continua sendo exibido.
 *
 * A pontuação é irrelevante — o backend também descarta tudo que não é dígito.
 * O que reprova é o dígito verificador.
 */
export function somenteDigitos(valor: string): string {
  return (valor || '').replace(/\D/g, '')
}

const CNPJ_PESOS_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
const CNPJ_PESOS_2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

function digitoCnpj(base: string, pesos: readonly number[]): string {
  const soma = pesos.reduce((acc, peso, i) => acc + Number(base[i]) * peso, 0)
  const resto = soma % 11
  return resto < 2 ? '0' : String(11 - resto)
}

export function cnpjEhValido(valor: string): boolean {
  const d = somenteDigitos(valor)
  if (d.length !== 14) return false
  // Mesma recusa do backend: 00000000000000, 11111111111111, etc.
  if (d === d[0].repeat(14)) return false
  const base = d.slice(0, 12)
  const comPrimeiro = base + digitoCnpj(base, CNPJ_PESOS_1)
  return d === comPrimeiro + digitoCnpj(comPrimeiro, CNPJ_PESOS_2)
}

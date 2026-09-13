import axios from 'axios'

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'

// Garante que baseURL termina com /api e serviços não dupliquem
export const api = axios.create({
  baseURL,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('facilpi_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('facilpi_token')
      localStorage.removeItem('facilpi_user')
      // evita loop se já em /login
      if (window.location.pathname !== '/login' && window.location.pathname !== '/register') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

// `detail` chega da API em três formas, todas em uso:
//   - string        -> HTTPException(detail="Intervalo de consulta invalido")
//   - {code, message} -> erros de negócio (PERMISSION_DENIED, AUTH_CONTEXT_REQUIRED, ...)
//   - [{loc, msg, ...}] -> validação automática do FastAPI (422)
// Entregar objeto ou array direto ao JSX faz o React lançar "Objects are not valid as a
// React child" e, sem error boundary, derruba a aplicação inteira.
// Este normalizador é o único ponto autorizado a converter erro de API em texto de tela.
export const ERRO_SEM_RESPOSTA = 'Não foi possível falar com o servidor. Verifique sua conexão e tente novamente.'

export function mensagemDeErro(e: unknown, padrao: string): string {
  const resposta = (e as { response?: { data?: { detail?: unknown } } })?.response
  // Sem resposta: rede, CORS ou servidor fora. Não é credencial inválida e não deve dizer que é.
  if (!resposta) return ERRO_SEM_RESPOSTA

  const detail = resposta.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail

  if (Array.isArray(detail)) {
    const msgs = detail
      .map(item => (typeof item === 'string' ? item : (item as { msg?: unknown })?.msg))
      .filter((m): m is string => typeof m === 'string' && m.trim().length > 0)
    return msgs.length ? msgs.join('; ') : padrao
  }

  if (detail && typeof detail === 'object') {
    // Só `message` vai para a tela; `code` é identificador técnico.
    const message = (detail as { message?: unknown }).message
    if (typeof message === 'string' && message.trim()) return message
  }

  return padrao
}

export const formatCurrency = (v: number) =>
  new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(v || 0)

// O backend serializa colunas `Date` como "YYYY-MM-DD", sem hora, e o JS interpreta essa forma
// como meia-noite UTC (ES2015+). Formatar esse instante em São Paulo (UTC−3) cai às 21:00 do dia
// anterior e imprime o dia errado — era o defeito da Issue #35.
const SOMENTE_DATA = /^\d{4}-\d{2}-\d{2}$/

export const formatDate = (iso?: string | null) => {
  if (!iso) return '—'
  try {
    // Uma data de calendário — nascimento, admissão, validade — é a mesma em qualquer fuso, então
    // 'UTC' aqui não converte: neutraliza a conversão e devolve o dia que veio na string. O outro
    // ramo continua necessário porque Dashboard.tsx passa um instante completo
    // (new Date().toISOString()), em que converter para São Paulo é o comportamento correto.
    const timeZone = SOMENTE_DATA.test(iso) ? 'UTC' : 'America/Sao_Paulo'
    return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeZone }).format(new Date(iso))
  } catch { return iso }
}
export const formatDateTime = (iso?: string | null) => {
  if (!iso) return '—'
  try {
    return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo' }).format(new Date(iso))
  } catch { return iso }
}

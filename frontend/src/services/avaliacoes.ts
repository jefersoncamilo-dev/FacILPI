import { api } from './api'

/**
 * Espelha Avaliações (backend/src/main.py, avaliacoes_router; schemas
 * Avaliacao*) e Grau de dependência (graus_router; GrauDependencia*) — UX-06 / #79.
 *
 * Avaliação é fato registrado: `tipo`, `instrumento`, `classificacao` são texto
 * livre e `pontuacao` é número livre. Não há catálogo de escalas nem faixa de
 * pontuação aprovada, então a tela não calcula, não classifica e não sugere
 * escala: registra e mostra o que foi informado. O profissional vem da sessão.
 *
 * O grau de dependência oficial é outra fonte: só existe por confirmação
 * humana explícita (Grau I/II/III + justificativa). A classificação da
 * avaliação entra apenas como sugestão gravada pelo backend.
 */
export interface Avaliacao {
  id: string
  residente_id: string
  tipo: string
  instrumento: string | null
  respostas: string | null
  pontuacao: number | null
  classificacao: string | null
  data: string | null
  validade: string | null
  observacoes: string | null
  profissional: string | null
  created_at: string | null
}

export interface NovaAvaliacao {
  residente_id: string
  tipo: string
  instrumento?: string
  pontuacao?: number
  classificacao?: string
  data?: string
  validade?: string
  observacoes?: string
}

export const GRAUS = ['Grau I', 'Grau II', 'Grau III'] as const
export type Grau = (typeof GRAUS)[number]

export interface GrauDependencia {
  id: string
  residente_id: string
  classificacao: string
  sugestao_classificacao: string | null
  origem: string
  avaliacao_id: string | null
  justificativa: string
  confirmado_em: string | null
  situacao: string
  validade: string | null
}

export const avaliacoesApi = {
  listar: () => api.get<Avaliacao[]>('/avaliacoes/', { params: { limit: 500 } }).then(r => r.data),
  criar: (dados: NovaAvaliacao) => api.post<Avaliacao>('/avaliacoes/', dados).then(r => r.data),
}

export const grausApi = {
  listar: (residente_id: string) => api.get<GrauDependencia[]>('/graus-dependencia/', { params: { residente_id } }).then(r => r.data),
  confirmarPorAvaliacao: (dados: { residente_id: string; avaliacao_id: string; classificacao: Grau; justificativa: string; validade?: string }) =>
    api.post<GrauDependencia>('/graus-dependencia/', { ...dados, origem: 'avaliacao' }).then(r => r.data),
}

/** Data local (YYYY-MM-DD): comparar validade com a data UTC erraria à noite. */
export function hojeLocal(agora = new Date()): string {
  const d = (n: number) => String(n).padStart(2, '0')
  return `${agora.getFullYear()}-${d(agora.getMonth() + 1)}-${d(agora.getDate())}`
}

/** Validade é data: vencida só quando já passou. Sem validade, não se afirma nada. */
export function situacaoValidade(validade: string | null, hoje = hojeLocal()): 'vigente' | 'vencida' | null {
  if (!validade) return null
  return validade.slice(0, 10) < hoje ? 'vencida' : 'vigente'
}

/**
 * `respostas` é texto (JSON quando veio de instrumento estruturado). Mostra
 * pares chave/valor quando for um objeto JSON plano; senão, o texto como está.
 */
export function lerRespostas(respostas: string | null): { pares: [string, string][] } | { texto: string } | null {
  if (!respostas?.trim()) return null
  try {
    const obj = JSON.parse(respostas)
    if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
      const pares = Object.entries(obj).filter(([, v]) => v === null || typeof v !== 'object').map(([k, v]) => [k, v === null ? '—' : String(v)] as [string, string])
      if (pares.length === Object.keys(obj).length) return { pares }
    }
  } catch { /* não é JSON: mostra o texto */ }
  return { texto: respostas }
}

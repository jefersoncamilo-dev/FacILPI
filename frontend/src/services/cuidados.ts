import { api } from './api'

/**
 * Cuidados programados (M12 / #185) sobre o backend de rotina já existente
 * (`/programacoes-cuidado`, `/ocorrencias-cuidado`). Programação não é
 * execução: aqui só se cria a agenda e se cancela ocorrência prevista; a
 * execução continua no Meu Plantão. O backend materializa as ocorrências no
 * horizonte G1 e é a autoridade de RBAC e tenant.
 */
export type Prioridade = 'baixa' | 'media' | 'alta'

export interface Programacao {
  id: string
  residente_id: string
  plano_id: string
  intervencao_id: string
  horarios: string[]
  timezone: string
  vigencia_inicio: string
  vigencia_fim: string | null
  perfil_responsavel: string | null
  prioridade: Prioridade
  situacao: string
}

export interface Ocorrencia {
  id: string
  residente_id: string
  programacao_id: string
  intervencao_id: string
  previsto_em: string
  situacao: string
  pendente: boolean
  motivo_cancelamento: string | null
}

export interface ProgramacaoNova {
  plano_id: string
  intervencao_id: string
  horarios: string[]
  timezone: string
  vigencia_inicio: string
  vigencia_fim?: string
  perfil_responsavel?: string
  prioridade: Prioridade
}

export const ROTULO_PRIORIDADE: Record<Prioridade, string> = { baixa: 'Baixa', media: 'Média', alta: 'Alta' }

export function timezoneLocal() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'America/Sao_Paulo'
  } catch {
    return 'America/Sao_Paulo'
  }
}

export const cuidadosApi = {
  criar: async (dados: ProgramacaoNova) => (await api.post<Programacao>('/programacoes-cuidado/', dados)).data,
  listar: async () => (await api.get<Programacao[]>('/programacoes-cuidado/', { params: { limit: 500 } })).data,
  ocorrencias: async (desde: string, ate: string) =>
    (await api.get<Ocorrencia[]>('/ocorrencias-cuidado/', { params: { desde, ate, limit: 500 } })).data,
  cancelarOcorrencia: async (id: string, motivo: string) =>
    (await api.post<Ocorrencia>(`/ocorrencias-cuidado/${id}/cancelar`, { motivo })).data,
}

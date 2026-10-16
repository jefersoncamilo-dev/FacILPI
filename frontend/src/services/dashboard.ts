import { api } from './api'

/**
 * Espelha DashboardResumoResponse (backend/src/application/schemas.py) e
 * GET /dashboard/resumo (backend/src/application/dashboard.py) — UX-02 / #85.
 *
 * Bloco `null` = a sessão não lê aquele módulo: a tela não o exibe.
 * Zero é contagem real. Nenhum número aqui é calculado no navegador.
 */
export interface DashboardResumo {
  gerado_em: string
  residentes_total: number | null
  ocupacao: { leitos_ativos: number; ocupados: number; livres: number; indisponiveis: number } | null
  ausencias_ativas: { total: number; hospitalizacoes: number } | null
  intercorrencias_abertas: number | null
  admissoes_em_andamento: number | null
  planos: { vigentes: number; em_revisao: number; em_elaboracao: number; aprovados_aguardando_vigencia: number } | null
  equipe: { ativos: number; afastados: number } | null
}

export async function getResumoDashboard(): Promise<DashboardResumo> {
  const { data } = await api.get<DashboardResumo>('/dashboard/resumo')
  return data
}

import { api } from './api'
import type { Alerta } from './alertas'
import { plantoesApi, type Escala, type Plantao } from './escala'

/**
 * Meu Plantão (#126) — espelha backend/src/application/meu_plantao.py.
 * Agregador de apresentação: cada bloco vem nulo quando a sessão não tem a
 * leitura correspondente ou quando não há plantão ativo em alguma área.
 */
export interface ResidenteDoTurno {
  id: string
  nome: string
  local: string | null
  em_atencao: boolean
  motivos: string[]
}

export interface AtividadeDoTurno {
  origem: 'cuidado' | 'medicacao'
  registro_id: string
  residente_id: string
  residente_nome: string | null
  descricao: string
  previsto_em: string | null
}

export interface MeuPlantaoResumo {
  gerado_em: string
  plantao: Plantao | null
  escalas_pendentes: Escala[]
  areas: { id: string; nome: string }[]
  residentes: ResidenteDoTurno[] | null
  prioridades: Alerta[] | null
  atividades: { atrasadas: AtividadeDoTurno[]; proximas: AtividadeDoTurno[] } | null
  passagens_a_receber: number | null
}

export const meuPlantaoApi = {
  // async: qualquer falha (inclusive síncrona) vira rejeição tratada pela tela.
  resumo: async () => (await api.get<MeuPlantaoResumo>('/meu-plantao/')).data,
}

/**
 * Para onde ir depois do login (#126): com plantão ativo, Meu Plantão é o
 * destino operacional; sem plantão (ou se a consulta falhar), o Início de sempre.
 */
export async function destinoAposLogin(): Promise<string> {
  try {
    const atual = await plantoesApi.atual()
    return atual?.plantao ? '/plantao' : '/'
  } catch {
    return '/'
  }
}

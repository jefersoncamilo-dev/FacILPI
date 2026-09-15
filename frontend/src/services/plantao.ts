import { api } from './api'

// Espelha PlantaoItem de backend/src/application/schemas.py e a projeção de
// backend/src/application/rotina.py. `/plantao/` é READ-ONLY: nenhuma linha é
// criada ali. Toda escrita vai para o endpoint oficial do fato subjacente.
export type PlantaoOrigem = 'cuidado' | 'medicacao' | 'intercorrencia'

export interface PlantaoItem {
  origem: PlantaoOrigem
  registro_id: string
  residente_id: string
  descricao: string
  // Intercorrência aberta não tem horário previsto; a projeção envia null e
  // ordena esses itens por último.
  previsto_em?: string | null
  // Só `cuidado` carrega prioridade (vem da ProgramacaoCuidado).
  prioridade?: string | null
}

export interface PlantaoConsultaParams {
  a_partir_de?: string
  ate?: string
  residente_id?: string
  limit?: number
}

// Mesmo default do backend (rotina.py). Declarado aqui para que a tela saiba
// quando a projeção pode ter sido truncada e avise, em vez de omitir em silêncio.
export const PLANTAO_LIMIT_PADRAO = 200

export const PLANTAO_ORIGENS: { value: PlantaoOrigem; label: string }[] = [
  { value: 'cuidado', label: 'Cuidados' },
  { value: 'medicacao', label: 'Medicação' },
  { value: 'intercorrencia', label: 'Intercorrências' },
]

export async function getPlantao(params: PlantaoConsultaParams = {}): Promise<PlantaoItem[]> {
  const { data } = await api.get<PlantaoItem[]>('/plantao/', { params })
  return data
}

// ---- Escrita: cada origem tem seu endpoint oficial ----

// ExecucaoCreate: justificativa é obrigatória quando o resultado não é "executada".
export type ResultadoCuidado = 'executada' | 'recusada' | 'omitida'

export interface ExecucaoCuidadoPayload {
  ocorrencia_id: string
  resultado: ResultadoCuidado
  ocorrido_em: string
  observacao?: string
  justificativa?: string
}

export async function registrarExecucaoCuidado(payload: ExecucaoCuidadoPayload) {
  const { data } = await api.post('/execucoes-cuidado/', payload)
  return data
}

// C5AdministracaoCreate: quantidade obrigatória quando "administrada";
// justificativa obrigatória nos demais resultados.
export type ResultadoDose = 'administrada' | 'recusada' | 'omitida'

export interface AdministracaoPayload {
  dose_prevista_id: string
  resultado: ResultadoDose
  ocorrido_em: string
  quantidade_realizada?: number
  justificativa?: string
  observacao?: string
}

export async function registrarAdministracao(payload: AdministracaoPayload) {
  const { data } = await api.post('/administracoes/', payload)
  return data
}

// IntercorrenciaEncerrar: desfecho não pode ser vazio.
export async function encerrarIntercorrencia(intercorrenciaId: string, desfecho: string) {
  const { data } = await api.post(`/intercorrencias/${intercorrenciaId}/encerrar`, { desfecho })
  return data
}

// Nome do residente não vem na projeção, só o id. A busca é auxiliar: se falhar,
// a tela mostra o id — degradar o rótulo é aceitável, esconder pendência não é.
export interface ResidenteResumo {
  id: string
  nome: string
}

export async function getResidentesResumo(): Promise<ResidenteResumo[]> {
  const { data } = await api.get<ResidenteResumo[]>('/residentes/')
  return data
}

import { api } from './api'

// N2 (#171): espelha backend/src/application/saida_residente.py.
export type TipoSaida = 'obito' | 'transferencia' | 'desligamento' | 'retorno_familia'

export const TIPOS_SAIDA: { value: TipoSaida; label: string }[] = [
  { value: 'obito', label: 'Óbito' },
  { value: 'transferencia', label: 'Transferência' },
  { value: 'desligamento', label: 'Desligamento' },
  { value: 'retorno_familia', label: 'Retorno à família' },
]

export const MOTIVOS_DESLIGAMENTO = [
  { value: 'fim_contrato', label: 'Fim de contrato' },
  { value: 'pedido_familia', label: 'A pedido da família' },
  { value: 'pedido_residente', label: 'A pedido do residente' },
  { value: 'pedido_ilpi', label: 'A pedido da ILPI' },
] as const

export interface SaidaPayload {
  tipo: TipoSaida
  ocorrido_em: string
  local_obito?: 'ilpi' | 'hospital'
  destino_tipo?: 'instituicao' | 'hospital'
  destino_descricao?: string
  motivo_desligamento?: string
  observacao?: string
  liberar_leito: boolean
}

export interface Pendencia {
  origem: string
  registro_id: string
  descricao: string
  link?: string | null
}

export interface PendenciasSaida {
  pendencias: Pendencia[]
  origens_sem_leitura: string[]
}

export async function getPendenciasSaida(residenteId: string): Promise<PendenciasSaida> {
  const { data } = await api.get<PendenciasSaida>(`/residentes/${residenteId}/saida/pendencias`)
  return data
}

export async function registrarSaida(residenteId: string, payload: SaidaPayload) {
  const { data } = await api.post(`/residentes/${residenteId}/saida`, payload)
  return data
}

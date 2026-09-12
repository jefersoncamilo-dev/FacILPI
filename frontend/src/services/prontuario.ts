import { api } from './api'

export type ProntuarioOrigem =
  | 'avaliacao'
  | 'grau_dependencia'
  | 'sinal_vital'
  | 'intercorrencia'
  | 'prescricao'
  | 'administracao'
  | 'pais'
  | 'execucao_cuidado'
  | 'ocupacao'
  | 'ausencia'

export type ProntuarioCategoria = 'clinico' | 'assistencia' | 'medicacao' | 'administrativo'

// Espelha ORIGEM_PERMISSION/ORIGEM_CATEGORIA de backend/src/application/prontuario.py.
// Não adicionar origem/categoria aqui sem confirmar antes no backend.
export const PRONTUARIO_ORIGENS: { value: ProntuarioOrigem; label: string; categoria: ProntuarioCategoria }[] = [
  { value: 'avaliacao', label: 'Avaliação', categoria: 'clinico' },
  { value: 'sinal_vital', label: 'Sinais vitais', categoria: 'clinico' },
  { value: 'intercorrencia', label: 'Intercorrência', categoria: 'clinico' },
  { value: 'grau_dependencia', label: 'Grau de dependência', categoria: 'assistencia' },
  { value: 'pais', label: 'Plano de cuidados (PAIS)', categoria: 'assistencia' },
  { value: 'execucao_cuidado', label: 'Execução de cuidado', categoria: 'assistencia' },
  { value: 'prescricao', label: 'Prescrição', categoria: 'medicacao' },
  { value: 'administracao', label: 'Administração', categoria: 'medicacao' },
  { value: 'ocupacao', label: 'Ocupação', categoria: 'administrativo' },
  { value: 'ausencia', label: 'Ausência', categoria: 'administrativo' },
]

export const PRONTUARIO_CATEGORIAS: { value: ProntuarioCategoria; label: string }[] = [
  { value: 'clinico', label: 'Clínico' },
  { value: 'assistencia', label: 'Assistência' },
  { value: 'medicacao', label: 'Medicação' },
  { value: 'administrativo', label: 'Administrativo' },
]

export interface ProntuarioEvento {
  origem: ProntuarioOrigem
  categoria: ProntuarioCategoria
  tipo: string
  registro_id: string
  residente_id: string
  ocorrido_em: string
  registrado_em?: string | null
  autor_id?: string | null
  resumo: string
  situacao?: string | null
  estornado: boolean
  substituido: boolean
  substituido_por?: string | null
  substituto: boolean
  substitui_id?: string | null
  motivo_estorno?: string | null
  link?: string | null
}

export interface ProntuarioResponse {
  items: ProntuarioEvento[]
  next_cursor: string | null
  has_more: boolean
}

export interface ProntuarioConsultaParams {
  origem?: ProntuarioOrigem
  categoria?: ProntuarioCategoria
  desde?: string
  ate?: string
  situacao?: string
  incluir_movimentacoes?: boolean
  limit?: number
  cursor?: string
}

export async function getProntuario(
  residenteId: string,
  params: ProntuarioConsultaParams = {},
): Promise<ProntuarioResponse> {
  const { data } = await api.get<ProntuarioResponse>(`/residentes/${residenteId}/prontuario`, { params })
  return data
}

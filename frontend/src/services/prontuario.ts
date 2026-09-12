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

// `situacao` existe no endpoint, mas é texto livre com vocabulário diferente por origem e, para
// sinais vitais, elimina a origem inteira. Expor um filtro global omitiria registros em silêncio,
// então o parâmetro fica fora do contrato até o backend oferecer vocabulário por origem.
export interface ProntuarioConsultaParams {
  origem?: ProntuarioOrigem
  categoria?: ProntuarioCategoria
  desde?: string
  ate?: string
  incluir_movimentacoes?: boolean
  limit?: number
  cursor?: string
}

// A timeline exibe e agrupa os dias em America/Sao_Paulo, mas o backend interpreta datetime sem
// fuso como UTC. Enviar o dia "cru" do input deslocaria a janela em algumas horas e omitiria
// registros sem aviso, então o dia escolhido é convertido para o instante UTC correspondente.
export const TIMEZONE_PRONTUARIO = 'America/Sao_Paulo'

// Offset derivado do próprio Intl, não fixado: a exibição já resolve o fuso por Intl e uma
// constante criaria uma segunda fonte de verdade, divergente em datas com horário de verão.
function offsetMinutos(instante: Date): number {
  const nome = new Intl.DateTimeFormat('en-US', {
    timeZone: TIMEZONE_PRONTUARIO,
    timeZoneName: 'longOffset',
  })
    .formatToParts(instante)
    .find(p => p.type === 'timeZoneName')?.value
  const partes = nome?.match(/GMT([+-])(\d{2}):(\d{2})/)
  if (!partes) return 0
  return (partes[1] === '-' ? -1 : 1) * (Number(partes[2]) * 60 + Number(partes[3]))
}

function instanteUTC(data: string, hora: number, minuto: number, segundo: number, ms: number): string {
  const [ano, mes, dia] = data.split('-').map(Number)
  const local = Date.UTC(ano, mes - 1, dia, hora, minuto, segundo, ms)
  // Duas passagens: a segunda corrige o dia que cai em transição de fuso.
  const aproximado = local - offsetMinutos(new Date(local)) * 60_000
  return new Date(local - offsetMinutos(new Date(aproximado)) * 60_000).toISOString()
}

export function inicioDoDiaISO(data: string): string {
  return instanteUTC(data, 0, 0, 0, 0)
}

export function fimDoDiaISO(data: string): string {
  return instanteUTC(data, 23, 59, 59, 999)
}

export async function getProntuario(
  residenteId: string,
  params: ProntuarioConsultaParams = {},
): Promise<ProntuarioResponse> {
  const { data } = await api.get<ProntuarioResponse>(`/residentes/${residenteId}/prontuario`, { params })
  return data
}

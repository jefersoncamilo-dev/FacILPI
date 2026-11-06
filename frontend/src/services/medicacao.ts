import { api } from './api'

// Espelha os schemas C5 de backend/src/application/schemas.py e as rotas de
// backend/src/application/medicacao.py. Sem PRN, estoque ou lote (DOMAIN_RULES,
// seção Medicação). Tenant e autoria vêm da sessão; nada disso é enviado daqui.

export type SituacaoPrescricao = 'rascunho' | 'ativa' | 'suspensa' | 'encerrada' | 'substituida'

export interface Medicamento {
  id: string
  nome: string
  principio_ativo?: string | null
  concentracao?: string | null
  apresentacao?: string | null
  situacao: 'ativo' | 'inativo'
}

export interface Programacao {
  id: string
  horarios: string[]
  timezone: string
  vigencia_inicio: string
  vigencia_fim?: string | null
  situacao: string
}

export interface Prescricao {
  id: string
  residente_id: string
  medicamento_id: string
  prescritor: string
  prescritor_nome?: string | null
  prescritor_categoria?: string | null
  prescritor_conselho?: string | null
  prescritor_numero?: string | null
  prescritor_uf?: string | null
  dose: string
  unidade?: string | null
  via?: string | null
  frequencia?: string | null
  inicio: string
  termino?: string | null
  orientacoes?: string | null
  medicamento_snapshot?: { nome?: string } | null
  situacao: SituacaoPrescricao | string
  anterior_id?: string | null
  motivo_suspensao?: string | null
  motivo_encerramento?: string | null
  motivo_versao?: string | null
  programacao?: Programacao | null
}

export interface DosePrevista {
  id: string
  residente_id: string
  prescricao_id: string
  previsto_em: string
  situacao: string
  pendente: boolean
}

export interface PrescricaoNova {
  residente_id: string
  medicamento_id: string
  prescritor_nome: string
  prescritor_categoria: string
  prescritor_conselho?: string
  prescritor_numero?: string
  prescritor_uf?: string
  dose: string
  unidade: string
  via: string
  frequencia?: string
  inicio: string
  orientacoes?: string
}

export interface Ativacao {
  horarios: string[]
  timezone: string
  vigencia_inicio: string
}

export const SITUACOES: { value: SituacaoPrescricao; label: string }[] = [
  { value: 'ativa', label: 'Ativas' },
  { value: 'rascunho', label: 'Rascunhos' },
  { value: 'suspensa', label: 'Suspensas' },
  { value: 'encerrada', label: 'Encerradas' },
  { value: 'substituida', label: 'Substituídas' },
]

/** "08:00, 20:00" → ["08:00", "20:00"]; ordena e remove vazios. */
export function lerHorarios(texto: string): string[] {
  return texto.split(/[\s,;]+/).map(h => h.trim()).filter(Boolean).sort()
}

export function fusoLocal(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'America/Sao_Paulo'
  } catch {
    return 'America/Sao_Paulo'
  }
}

export async function getMedicamentos(): Promise<Medicamento[]> {
  const { data } = await api.get<Medicamento[]>('/medicamentos/', { params: { limit: 500 } })
  return data
}

export async function criarMedicamento(nome: string): Promise<Medicamento> {
  const { data } = await api.post<Medicamento>('/medicamentos/', { nome })
  return data
}

export async function getPrescricoes(residenteId: string): Promise<Prescricao[]> {
  const { data } = await api.get<Prescricao[]>('/prescricoes/', { params: { residente_id: residenteId, limit: 500 } })
  return data
}

export async function criarPrescricao(payload: PrescricaoNova): Promise<Prescricao> {
  const { data } = await api.post<Prescricao>('/prescricoes/', payload)
  return data
}

export async function ativarPrescricao(id: string, payload: Ativacao): Promise<Prescricao> {
  const { data } = await api.post<Prescricao>(`/prescricoes/${id}/ativar`, payload)
  return data
}

export async function suspenderPrescricao(id: string, motivo: string): Promise<Prescricao> {
  const { data } = await api.post<Prescricao>(`/prescricoes/${id}/suspender`, { motivo })
  return data
}

export async function encerrarPrescricao(id: string, motivo: string): Promise<Prescricao> {
  const { data } = await api.post<Prescricao>(`/prescricoes/${id}/encerrar`, { motivo })
  return data
}

export async function substituirPrescricao(
  id: string, payload: { motivo: string; prescricao: PrescricaoNova; programacao: Ativacao },
): Promise<Prescricao> {
  const { data } = await api.post<Prescricao>(`/prescricoes/${id}/substituir`, payload)
  return data
}

export async function getDosesDoDia(residenteId: string, dia = new Date()): Promise<DosePrevista[]> {
  const desde = new Date(dia.getFullYear(), dia.getMonth(), dia.getDate())
  const ate = new Date(desde.getTime() + 24 * 60 * 60 * 1000 - 1)
  const { data } = await api.get<DosePrevista[]>('/doses-previstas/', {
    params: { residente_id: residenteId, desde: desde.toISOString(), ate: ate.toISOString(), limit: 500 },
  })
  return data
}

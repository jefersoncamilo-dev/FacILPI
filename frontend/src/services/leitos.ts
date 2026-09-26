import { api } from './api'

/**
 * Espelha fase5a2d (backend/src/application/fase5a2d.py) — UX-08 / #81.
 *
 * Ocupado não é uma situação: é `residente_atual_id` preenchido (a situação
 * de um leito ocupado continua "livre"). Registrar ausência NÃO libera o
 * leito — o que acontece com o leito durante uma hospitalização é decisão
 * funcional ainda pendente, e a tela só mostra o fato.
 */
export type SituacaoLeito = 'livre' | 'reservado' | 'bloqueado' | 'manutencao' | 'inativo'

export const ROTULO_SITUACAO_LEITO: Record<SituacaoLeito, string> = {
  livre: 'Livre',
  reservado: 'Reservado',
  bloqueado: 'Bloqueado',
  manutencao: 'Em manutenção',
  inativo: 'Inativo',
}

/** Situações que um leito VAZIO pode assumir por edição (inativar tem ação própria). */
export const SITUACOES_EDITAVEIS: SituacaoLeito[] = ['livre', 'reservado', 'bloqueado', 'manutencao']

export interface Leito {
  id: string
  unidade: string | null
  quarto: string
  leito: string
  capacidade: number
  acessibilidade: string | null
  residente_atual_id: string | null
  situacao: SituacaoLeito
  data_ocupacao: string | null
}

export type EstadoLeito = 'ocupado' | 'livre' | 'indisponivel' | 'inativo'

export function estadoDoLeito(l: Leito): EstadoLeito {
  if (l.residente_atual_id) return 'ocupado'
  if (l.situacao === 'inativo') return 'inativo'
  if (l.situacao === 'livre') return 'livre'
  return 'indisponivel'
}

export function nomeDoLeito(l: Pick<Leito, 'quarto' | 'leito'>): string {
  return `Quarto ${l.quarto} · Leito ${l.leito}`
}

export type TipoAusencia = 'hospitalizacao' | 'saida_temporaria'

export const ROTULO_AUSENCIA: Record<TipoAusencia, string> = {
  hospitalizacao: 'Hospitalização',
  saida_temporaria: 'Saída temporária',
}

export interface Ausencia {
  id: string
  residente_id: string
  quarto_leito_id: string | null
  tipo: TipoAusencia
  data_inicio: string
  data_fim: string | null
  motivo: string
  observacoes: string | null
}

export interface MovimentacaoLeito {
  id: string
  residente_id: string
  quarto_leito_id: string
  data_entrada: string
  data_saida: string | null
  tipo_movimentacao: string
  motivo: string | null
}

export const leitosApi = {
  listar: () => api.get<Leito[]>('/quartos_leitos/', { params: { limit: 500 } }).then(r => r.data),
  criar: (dados: { unidade?: string; quarto: string; leito: string; acessibilidade?: string }) =>
    api.post<Leito>('/quartos_leitos/', dados).then(r => r.data),
  alterarSituacao: (id: string, situacao: SituacaoLeito) =>
    api.put<Leito>(`/quartos_leitos/${id}`, { situacao }).then(r => r.data),
  inativar: (id: string) => api.post<Leito>(`/quartos_leitos/${id}/inativar`, {}).then(r => r.data),
  alocar: (id: string, residente_id: string) =>
    api.post<Leito>(`/quartos_leitos/${id}/alocar`, { residente_id }).then(r => r.data),
  liberar: (id: string) => api.post<Leito>(`/quartos_leitos/${id}/liberar`, {}).then(r => r.data),
  transferir: (residente_id: string, novo_leito_id: string, motivo?: string) =>
    api.post<Leito>('/quartos_leitos/transferencia', motivo ? { residente_id, novo_leito_id, motivo } : { residente_id, novo_leito_id }).then(r => r.data),
  historico: (quarto_leito_id: string) =>
    api.get<MovimentacaoLeito[]>('/ocupacao_historico/', { params: { quarto_leito_id } }).then(r => r.data),
}

export const ausenciasApi = {
  listar: () => api.get<Ausencia[]>('/ausencias/', { params: { limit: 500 } }).then(r => r.data),
  registrar: (dados: { residente_id: string; tipo: TipoAusencia; motivo: string; observacoes?: string; quarto_leito_id?: string }) =>
    api.post<Ausencia>('/ausencias/', dados).then(r => r.data),
  encerrar: (id: string) => api.post<Ausencia>(`/ausencias/${id}/encerrar`, {}).then(r => r.data),
}

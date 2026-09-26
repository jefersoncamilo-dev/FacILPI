import { api } from './api'

/**
 * Espelha o contrato D.3 de Admissões (backend/src/application/admissoes.py e
 * schemas AdmissaoResponse/AdmissaoAvancar/AdmissaoMotivo) — UX-03 / #76.
 *
 * O processo é só a condução: documentos, avaliações, leito e PAIS continuam
 * nas fontes oficiais; as pendências vêm do backend (GET /pendencias). Toda
 * ação envia `lock_version` — versão obsoleta responde 409 e exige recarregar.
 */

export const ETAPAS = ['pre_cadastro', 'triagem', 'documentacao', 'avaliacoes', 'contrato', 'quarto_leito', 'pais'] as const
export type Etapa = (typeof ETAPAS)[number]
export type SituacaoAdmissao = Etapa | 'concluida' | 'cancelada' | 'desistencia'

export const ROTULO_SITUACAO: Record<SituacaoAdmissao, string> = {
  pre_cadastro: 'Pré-cadastro',
  triagem: 'Triagem',
  documentacao: 'Documentação',
  avaliacoes: 'Avaliações',
  contrato: 'Contrato',
  quarto_leito: 'Quarto e leito',
  pais: 'PAIS',
  concluida: 'Concluída',
  cancelada: 'Cancelada',
  desistencia: 'Desistência',
}

export const TERMINAIS: SituacaoAdmissao[] = ['concluida', 'cancelada', 'desistencia']

export function emAndamento(situacao: string): boolean {
  return !TERMINAIS.includes(situacao as SituacaoAdmissao)
}

export function proximaEtapa(situacao: string): Etapa | null {
  const i = ETAPAS.indexOf(situacao as Etapa)
  return i >= 0 && i < ETAPAS.length - 1 ? ETAPAS[i + 1] : null
}

export interface Admissao {
  id: string
  ilpi_id: string
  residente_id: string
  situacao: SituacaoAdmissao
  autor_id: string
  responsavel_funcionario_id: string | null
  iniciada_em: string
  concluida_em: string | null
  cancelada_em: string | null
  desistencia_em: string | null
  motivo_cancelamento: string | null
  motivo_desistencia: string | null
  contrato_registrado_em: string | null
  contrato_documento_id: string | null
  avaliacoes_requeridas: { tipo: string; instrumento?: string | null; origem: string }[]
  lock_version: number
  created_at: string
  updated_at: string
}

export type CodigoPendencia =
  | 'residente_pendente'
  | 'documentacao_pendente'
  | 'avaliacao_requerida_pendente'
  | 'contrato_pendente'
  | 'quarto_leito_pendente'
  | 'pais_pendente'

export interface Pendencia {
  codigo: CodigoPendencia
  origem: string
  referencia_id?: string
  motivo?: string
  tipo?: string
  instrumento?: string | null
}

export interface VerificacaoPendencias {
  admissao_id: string
  lock_version: number
  data_verificacao: string
  documentos: { id: string; tipo: string; obrigatorio: boolean; situacao: string; validade: string | null; cumprido: boolean }[]
  avaliacoes_requeridas: { tipo: string; instrumento?: string | null; origem: string; cumprido: boolean }[]
  quarto_leito_ids: string[]
  pais_ids: string[]
  pendencias: Pendencia[]
  requisitos_cumpridos: boolean
}

export interface HistoricoAdmissao {
  id: string
  etapa_origem: SituacaoAdmissao | null
  etapa_destino: SituacaoAdmissao
  acao: string
  motivo: string | null
  lock_version: number
  created_at?: string
}

/** Pendência que impede SAIR de cada etapa (mesmo mapa de admissoes._transicao). */
export const PENDENCIA_QUE_BLOQUEIA: Partial<Record<Etapa, CodigoPendencia>> = {
  documentacao: 'documentacao_pendente',
  avaliacoes: 'avaliacao_requerida_pendente',
  contrato: 'contrato_pendente',
  quarto_leito: 'quarto_leito_pendente',
}

/** Etapa a que cada pendência pertence, para exibir no lugar certo. */
export const ETAPA_DA_PENDENCIA: Record<CodigoPendencia, Etapa> = {
  residente_pendente: 'pre_cadastro',
  documentacao_pendente: 'documentacao',
  avaliacao_requerida_pendente: 'avaliacoes',
  contrato_pendente: 'contrato',
  quarto_leito_pendente: 'quarto_leito',
  pais_pendente: 'pais',
}

export function descreverPendencia(p: Pendencia): string {
  switch (p.codigo) {
    case 'residente_pendente': return 'Cadastro do residente incompleto'
    case 'documentacao_pendente': return 'Documento obrigatório ainda não validado'
    case 'avaliacao_requerida_pendente': return `Avaliação requerida pendente: ${[p.tipo, p.instrumento].filter(Boolean).join(' · ')}`
    case 'contrato_pendente': return 'Contrato ainda não registrado'
    case 'quarto_leito_pendente': return 'Residente sem leito atribuído'
    case 'pais_pendente': return 'Residente sem PAIS vigente'
  }
}

const BASE = '/admissoes/'

export const admissoesApi = {
  listar: () => api.get<Admissao[]>(BASE, { params: { limit: 500 } }).then(r => r.data),
  obter: (id: string) => api.get<Admissao>(`${BASE}${id}`).then(r => r.data),
  pendencias: (id: string) => api.get<VerificacaoPendencias>(`${BASE}${id}/pendencias`).then(r => r.data),
  historico: (id: string) => api.get<HistoricoAdmissao[]>(`${BASE}${id}/historico`).then(r => r.data),
  criar: (residente_id: string, responsavel_funcionario_id?: string) =>
    api.post<Admissao>(BASE, responsavel_funcionario_id ? { residente_id, responsavel_funcionario_id } : { residente_id }).then(r => r.data),
  avancar: (a: Admissao, etapa_destino: Etapa) =>
    api.post<Admissao>(`${BASE}${a.id}/avancar`, { lock_version: a.lock_version, etapa_destino }).then(r => r.data),
  concluir: (a: Admissao) => api.post<Admissao>(`${BASE}${a.id}/concluir`, { lock_version: a.lock_version }).then(r => r.data),
  cancelar: (a: Admissao, motivo: string) =>
    api.post<Admissao>(`${BASE}${a.id}/cancelar`, { lock_version: a.lock_version, motivo }).then(r => r.data),
  desistir: (a: Admissao, motivo: string) =>
    api.post<Admissao>(`${BASE}${a.id}/desistir`, { lock_version: a.lock_version, motivo }).then(r => r.data),
  reabrir: (a: Admissao, motivo: string) =>
    api.post<Admissao>(`${BASE}${a.id}/reabrir`, { lock_version: a.lock_version, motivo }).then(r => r.data),
  registrarContrato: (a: Admissao, motivo: string, documento_id?: string) =>
    api.post<Admissao>(`${BASE}${a.id}/contrato`, documento_id
      ? { lock_version: a.lock_version, motivo, documento_id }
      : { lock_version: a.lock_version, motivo }).then(r => r.data),
}

/** Erro de API da admissão, já interpretado para a tela. */
export function erroDeAdmissao(e: unknown): { conflitoDeVersao: boolean; mensagem: string; pendencias: Pendencia[] } {
  const resposta = (e as { response?: { status?: number; data?: { detail?: unknown } } })?.response
  const detail = resposta?.data?.detail as { code?: string; message?: string; pendencias?: Pendencia[] } | string | undefined
  const mensagemBackend = typeof detail === 'string' ? detail : detail?.message
  const conflitoDeVersao = resposta?.status === 409 && /vers[aã]o obsoleta/i.test(mensagemBackend || '')
  const pendencias = typeof detail === 'object' && Array.isArray(detail?.pendencias) ? detail.pendencias : []
  let mensagem = mensagemBackend || 'Não foi possível concluir a ação.'
  if (!resposta) mensagem = 'Não foi possível falar com o servidor. Verifique sua conexão e tente novamente.'
  else if (conflitoDeVersao) mensagem = 'Esta admissão foi alterada por outra pessoa. Os dados foram recarregados; confira e tente de novo.'
  else if (resposta.status === 403) mensagem = 'Você não tem permissão para esta ação.'
  else if (pendencias.length) mensagem = 'Ainda há pendências que impedem esta ação.'
  return { conflitoDeVersao, mensagem, pendencias }
}

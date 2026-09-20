import { api } from './api'
import type {
  Instituicao,
  InstituicaoPayload,
  PrimeiroGestorCriado,
  PrimeiroGestorPayload,
} from '../types/platform'

/**
 * Central FACILPI — consome exclusivamente /api/platform/*, a porta de
 * provisionamento repetível. Não toca as rotas de bootstrap
 * (/api/instituicoes, /api/onboarding), que são a sequência de nascimento da
 * plataforma e só rodam uma vez.
 */

/** O backend não oferece busca; o filtro da tela é sobre esta página. */
export const LIMITE_LISTAGEM = 100

export async function listarInstituicoes(): Promise<Instituicao[]> {
  const { data } = await api.get<Instituicao[]>('/platform/instituicoes', {
    params: { limit: LIMITE_LISTAGEM },
  })
  return data
}

export async function obterInstituicao(id: string): Promise<Instituicao> {
  const { data } = await api.get<Instituicao>(`/platform/instituicoes/${id}`)
  return data
}

export async function criarInstituicao(payload: InstituicaoPayload): Promise<Instituicao> {
  const { data } = await api.post<Instituicao>('/platform/instituicoes', payload)
  return data
}

export async function atualizarInstituicao(
  id: string,
  payload: InstituicaoPayload,
): Promise<Instituicao> {
  const { data } = await api.put<Instituicao>(`/platform/instituicoes/${id}`, payload)
  return data
}

/**
 * Devolve `senha_temporaria` UMA única vez. Quem chama e responsável por nunca
 * persistir esse valor: ele vive apenas no estado da tela.
 */
export async function criarPrimeiroGestor(
  id: string,
  payload: PrimeiroGestorPayload,
): Promise<PrimeiroGestorCriado> {
  const { data } = await api.post<PrimeiroGestorCriado>(
    `/platform/instituicoes/${id}/primeiro-gestor`,
    payload,
  )
  return data
}

/**
 * Regeneração, não recuperação: a senha anterior deixa de valer. Também devolve
 * `senha_temporaria` uma única vez — mesma disciplina de `criarPrimeiroGestor`.
 */
export async function regerarCredencialPrimeiroGestor(
  id: string,
): Promise<PrimeiroGestorCriado> {
  const { data } = await api.post<PrimeiroGestorCriado>(
    `/platform/instituicoes/${id}/primeiro-gestor/credencial`,
  )
  return data
}

export async function ativarInstituicao(id: string): Promise<Instituicao> {
  const { data } = await api.post<Instituicao>(`/platform/instituicoes/${id}/ativar`)
  return data
}

export async function inativarInstituicao(id: string): Promise<Instituicao> {
  const { data } = await api.post<Instituicao>(`/platform/instituicoes/${id}/inativar`)
  return data
}

/** Remove campos vazios: o backend usa `exclude_unset` e trata ausência != vazio. */
export function montarPayload(form: Record<string, string>): InstituicaoPayload {
  const payload: Record<string, unknown> = {}
  for (const [chave, valor] of Object.entries(form)) {
    const limpo = valor.trim()
    if (!limpo) continue
    payload[chave] = chave === 'capacidade' ? Number(limpo) : limpo
  }
  return payload as unknown as InstituicaoPayload
}

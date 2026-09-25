import { api } from './api'
import type { ActiveContext } from '../types/context'

export interface InstituicaoRef {
  id: string
  razao_social: string
  nome_fantasia?: string | null
  situacao?: string | null
}

export interface PerfilRef {
  id: string
  nome: string
  chave: string
  escopo: string
  ilpi_id?: string | null
}

export interface ContextSelectPayload {
  scope: 'global' | 'ilpi'
  ilpi_id?: string
  perfil_id?: string
}

export interface TokenPayload {
  access_token: string
  token_type: string
  exige_troca_senha: boolean
}

/**
 * PH-01: encerramento de sessão no servidor.
 *
 * PH-02/PR-2: o interceptor de api.ts anexa o Bearer armazenado e ele é a
 * identidade suficiente para o backend revogar a família da sessão. Isso fecha
 * o logout também na topologia cross-origin do Render, onde o cookie
 * SameSite=Strict pode não atravessar facilpi-web → facilpi-api.
 *
 * `withCredentials` permanece como segunda prova quando o cookie está
 * disponível (mesma origem/topologia futura). Cookie e Bearer divergentes são
 * tratados pelo servidor como sessão inconsistente; nunca há escolha silenciosa.
 *
 * `timeout` existe porque sair não pode depender da rede: se o servidor não
 * responder, quem chama ainda precisa limpar a sessão local e seguir.
 */
export function logoutServidor() {
  return api.post('/auth/logout', null, { withCredentials: true, timeout: 5000 })
}

export const contextApi = {
  /** Troca oficial de contexto. O backend valida o vínculo; 403 = não autorizado. */
  selectContext(payload: ContextSelectPayload) {
    return api.post<TokenPayload>('/auth/contexto', payload)
  },
  /** ILPIs visíveis no contexto do token atual (fonte dos rótulos/IDs). */
  listInstitutions() {
    return api.get<InstituicaoRef[]>('/instituicoes/')
  },
  /** Perfis visíveis no contexto do token atual (para rótulo do perfil). */
  listPerfis() {
    return api.get<PerfilRef[]>('/perfis/')
  },
  /**
   * UX-01 (#83): permissões efetivas do contexto da sessão. Só orienta a
   * navegação; cada rota do backend continua decidindo por si.
   */
  permissoesDaSessao() {
    return api.get<PermissoesSessao>('/auth/permissoes')
  },
}

export interface PermissoesSessao {
  scope: 'global' | 'ilpi'
  ilpi_id?: string | null
  permissoes: string[]
}

export function displayIlpiName(ilpi: Pick<InstituicaoRef, 'razao_social' | 'nome_fantasia'>): string {
  return ilpi.nome_fantasia?.trim() || ilpi.razao_social
}

/**
 * Completa os rótulos do contexto com dados do backend.
 * Nunca inventa nomes: sem resposta, usa rótulos genéricos seguros.
 */
export async function resolveContextLabels(ctx: ActiveContext): Promise<ActiveContext> {
  if (ctx.scope !== 'ilpi' || !ctx.ilpi_id) {
    return { scope: 'global' }
  }
  let ilpiNome: string | null = null
  let perfilNome: string | null = null
  try {
    const { data } = await contextApi.listInstitutions()
    const found = (data || []).find(i => i.id === ctx.ilpi_id)
    if (found) ilpiNome = displayIlpiName(found)
  } catch {
    ilpiNome = null
  }
  if (ctx.perfil_id) {
    try {
      const { data } = await contextApi.listPerfis()
      const found = (data || []).find(p => p.id === ctx.perfil_id)
      if (found) perfilNome = found.nome
    } catch {
      perfilNome = null
    }
  }
  return { ...ctx, ilpiNome, perfilNome }
}

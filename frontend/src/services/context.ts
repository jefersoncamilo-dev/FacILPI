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

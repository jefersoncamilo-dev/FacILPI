export type ContextScope = 'global' | 'ilpi'

export interface JwtClaims {
  sub?: string
  email?: string
  is_superuser?: boolean
  exige_troca_senha?: boolean
  scope?: string
  ilpi_id?: string | null
  perfil_id?: string | null
  exp?: number
}

/** Contexto ativo derivado do token (fonte de verdade = backend). */
export interface ActiveContext {
  scope: ContextScope
  ilpi_id?: string | null
  perfil_id?: string | null
  /** Rótulos resolvidos via backend (nunca IDs na UI). */
  ilpiNome?: string | null
  perfilNome?: string | null
}

/** Opção selecionável. IDs sempre originados do backend. */
export interface ContextOption {
  key: string
  scope: ContextScope
  ilpi_id?: string
  label: string
  sublabel: string
}

export const TOKEN_KEY = 'facilpi_token'
export const USER_KEY = 'facilpi_user'
export const CONTEXT_KEY = 'facilpi_context'

export const CONTEXT_CHANGED_EVENT = 'facilpi:context-changed'

function base64UrlDecode(segment: string): string {
  const padded = segment.replace(/-/g, '+').replace(/_/g, '/')
  const pad = padded.length % 4 === 0 ? '' : '='.repeat(4 - (padded.length % 4))
  return atob(padded + pad)
}

/** Decodifica o payload do JWT apenas para exibição/roteamento. Sem validação local de acesso. */
export function decodeJwt(token: string | null): JwtClaims | null {
  if (!token) return null
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    return JSON.parse(base64UrlDecode(parts[1])) as JwtClaims
  } catch {
    return null
  }
}

export function isTokenExpired(token: string | null, skewSec = 30): boolean {
  const claims = decodeJwt(token)
  if (!claims || typeof claims.exp !== 'number') return true
  return claims.exp <= Math.floor(Date.now() / 1000) + skewSec
}

/** Deriva o contexto ativo das claims do token emitido pelo backend. */
export function contextFromToken(token: string | null): ActiveContext | null {
  const claims = decodeJwt(token)
  if (!claims) return null
  if (claims.scope === 'ilpi' && claims.ilpi_id) {
    return { scope: 'ilpi', ilpi_id: claims.ilpi_id, perfil_id: claims.perfil_id ?? null }
  }
  return { scope: 'global' }
}

export function sameContext(a: ActiveContext | null, b: ActiveContext | null): boolean {
  if (!a || !b) return a === b
  return a.scope === b.scope && (a.ilpi_id ?? null) === (b.ilpi_id ?? null)
}

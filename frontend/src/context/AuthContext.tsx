import { createContext, useContext, useEffect, useState, useCallback, ReactNode } from 'react'
import { api } from '../services/api'
import { contextApi, resolveContextLabels } from '../services/context'
import {
  TOKEN_KEY, USER_KEY, CONTEXT_KEY, CONTEXT_CHANGED_EVENT,
  decodeJwt, isTokenExpired, contextFromToken, sameContext,
} from '../types/context'
import type { ActiveContext, ContextOption } from '../types/context'

type User = { id: string; nome: string; email: string }

export type LoginResult = {
  options: ContextOption[]
  requiresPasswordChange: boolean
}

type AuthContextType = {
  user: User | null
  isAuthenticated: boolean
  /** Troca obrigatória pendente (primeiro acesso). Bloqueia app normal e context switch. */
  requiresPasswordChange: boolean
  login: (email: string, password: string) => Promise<LoginResult>
  logout: () => void
  updatePassword: (nova: string, confirmar: string) => Promise<void>
  /** Troca obrigatória: PUT /auth/password + re-login (token/claims atualizados). */
  completePasswordChange: (nova: string, confirmar: string) => Promise<LoginResult>
  loading: boolean
  activeContext: ActiveContext | null
  availableContexts: ContextOption[]
  switching: boolean
  contextError: string | null
  clearContextError: () => void
  switchContext: (opt: ContextOption) => Promise<void>
  refreshContexts: () => Promise<ContextOption[]>
}

const AuthContext = createContext<AuthContextType | null>(null)

function readStored<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

function buildUser(token: string): User {
  const payload = decodeJwt(token)
  const email = payload?.email || ''
  return { id: payload?.sub || '', nome: email.split('@')[0] || 'Usuário', email }
}

/** Monta as opções selecionáveis a partir do token atual (backend = autoridade). */
async function discoverContexts(token: string): Promise<ContextOption[]> {
  const claims = decodeJwt(token)
  if (!claims?.is_superuser) {
    // Sem vínculo global, o único contexto operável é o do próprio token.
    const ctx = contextFromToken(token)
    if (ctx?.scope === 'ilpi' && ctx.ilpi_id) {
      return [{ key: `ilpi:${ctx.ilpi_id}`, scope: 'ilpi', ilpi_id: ctx.ilpi_id, label: 'ILPI', sublabel: 'Contexto institucional' }]
    }
    return [{ key: 'global', scope: 'global', label: 'Plataforma', sublabel: 'Superusuário' }]
  }
  const options: ContextOption[] = [{ key: 'global', scope: 'global', label: 'Plataforma', sublabel: 'Superusuário' }]
  try {
    const { data } = await contextApi.listInstitutions()
    for (const ilpi of data || []) {
      const nome = ilpi.nome_fantasia?.trim() || ilpi.razao_social
      options.push({ key: `ilpi:${ilpi.id}`, scope: 'ilpi', ilpi_id: ilpi.id, label: nome, sublabel: 'Trocar para esta ILPI' })
    }
  } catch {
    // Sem leitura de ILPIs, mantém ao menos o contexto global atual.
  }
  return options
}

function persist(token: string, user: User, ctx: ActiveContext) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
  localStorage.setItem(CONTEXT_KEY, JSON.stringify(ctx))
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => readStored<User>(USER_KEY))
  const [activeContext, setActiveContext] = useState<ActiveContext | null>(() => readStored<ActiveContext>(CONTEXT_KEY))
  const [availableContexts, setAvailableContexts] = useState<ContextOption[]>([])
  const [requiresPasswordChange, setRequiresPasswordChange] = useState<boolean>(() => {
    const token = localStorage.getItem(TOKEN_KEY)
    return decodeJwt(token)?.exige_troca_senha === true
  })
  const [loading, setLoading] = useState(false)
  const [switching, setSwitching] = useState(false)
  const [contextError, setContextError] = useState<string | null>(null)

  const clearContextError = useCallback(() => setContextError(null), [])

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    localStorage.removeItem(CONTEXT_KEY)
    setUser(null)
    setActiveContext(null)
    setAvailableContexts([])
    setRequiresPasswordChange(false)
    window.location.href = '/login'
  }, [])

  /** Reconcilia o contexto armazenado com as claims do token (token vence). */
  const syncFromToken = useCallback(async (token: string, flagFromLogin?: boolean) => {
    const fromToken = contextFromToken(token)
    if (!fromToken) {
      logout()
      return { ctx: null as ActiveContext | null, options: [] as ContextOption[], requiresPasswordChange: false }
    }
    const mustChange = flagFromLogin ?? decodeJwt(token)?.exige_troca_senha === true
    setRequiresPasswordChange(mustChange)
    const stored = readStored<ActiveContext>(CONTEXT_KEY)
    let ctx: ActiveContext = fromToken
    if (stored && sameContext(stored, fromToken)) {
      ctx = stored
    } else {
      try {
        ctx = await resolveContextLabels(fromToken)
      } catch {
        ctx = fromToken
      }
    }
    setActiveContext(ctx)
    localStorage.setItem(CONTEXT_KEY, JSON.stringify(ctx))
    // Com troca pendente não há escolha operacional: só o contexto atual.
    const options = mustChange ? [currentAsOption(ctx)] : await discoverContexts(token)
    setAvailableContexts(options)
    return { ctx, options, requiresPasswordChange: mustChange }
  }, [logout])

  const refreshContexts = useCallback(async () => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token || isTokenExpired(token)) return []
    const options = await discoverContexts(token)
    setAvailableContexts(options)
    return options
  }, [])

  async function login(email: string, password: string): Promise<LoginResult> {
    setLoading(true)
    try {
      const { data } = await api.post('/auth/token', { email, password })
      const mustChange = data.exige_troca_senha === true
      const u = buildUser(data.access_token)
      const base = contextFromToken(data.access_token) || { scope: 'global' as const }
      persist(data.access_token, u, base)
      setUser(u)
      const { options } = await syncFromToken(data.access_token, mustChange)
      return { options, requiresPasswordChange: mustChange }
    } finally {
      setLoading(false)
    }
  }

  async function switchContext(opt: ContextOption): Promise<void> {
    if (requiresPasswordChange) {
      const msg = 'Defina sua nova senha antes de trocar de contexto'
      setContextError(msg)
      throw new Error(msg)
    }
    setSwitching(true)
    setContextError(null)
    try {
      const payload: { scope: 'global' | 'ilpi'; ilpi_id?: string } =
        opt.scope === 'ilpi' && opt.ilpi_id ? { scope: 'ilpi', ilpi_id: opt.ilpi_id } : { scope: 'global' }
      const { data } = await contextApi.selectContext(payload)
      const token = data.access_token
      const u = buildUser(token)
      const base = contextFromToken(token) || { scope: opt.scope, ilpi_id: opt.ilpi_id ?? null }
      let ctx: ActiveContext = base
      try {
        ctx = await resolveContextLabels(base)
      } catch {
        ctx = base
      }
      setRequiresPasswordChange(data.exige_troca_senha === true)
      persist(token, u, ctx)
      setUser(u)
      setActiveContext(ctx)
      window.dispatchEvent(new Event(CONTEXT_CHANGED_EVENT))
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setContextError(typeof detail === 'string' ? detail : detail?.message || 'Não foi possível trocar de contexto')
      throw e
    } finally {
      setSwitching(false)
    }
  }

  async function updatePassword(nova_senha: string, confirmar_senha: string) {
    await api.put('/auth/password', { nova_senha, confirmar_senha })
  }

  /**
   * Fluxo obrigatório de primeiro acesso: troca a senha e re-autentica para
   * obter token/claims atualizados. A senha vive só neste escopo (não persiste).
   */
  async function completePasswordChange(nova_senha: string, confirmar_senha: string): Promise<LoginResult> {
    setLoading(true)
    try {
      await api.put('/auth/password', { nova_senha, confirmar_senha })
      const email = user?.email || readStored<User>(USER_KEY)?.email || ''
      const { data } = await api.post('/auth/token', { email, password: nova_senha })
      const u = buildUser(data.access_token)
      const base = contextFromToken(data.access_token) || { scope: 'global' as const }
      persist(data.access_token, u, base)
      setUser(u)
      const { options } = await syncFromToken(data.access_token, data.exige_troca_senha === true)
      window.dispatchEvent(new Event(CONTEXT_CHANGED_EVENT))
      return { options, requiresPasswordChange: data.exige_troca_senha === true }
    } finally {
      setLoading(false)
    }
  }

  // Restaura sessão no refresh: token inválido/expirado derruba para login.
  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token || isTokenExpired(token)) {
      if (token) logout()
      return
    }
    if (!user) setUser(buildUser(token))
    syncFromToken(token).catch(() => undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // keep user sync on storage
  useEffect(() => {
    const onStorage = () => {
      const raw = localStorage.getItem(USER_KEY)
      setUser(raw ? JSON.parse(raw) : null)
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const isAuthenticated = !!user && !!localStorage.getItem(TOKEN_KEY)

  return (
    <AuthContext.Provider value={{
      user, isAuthenticated, requiresPasswordChange, login, logout, updatePassword,
      completePasswordChange, loading,
      activeContext, availableContexts, switching, contextError, clearContextError,
      switchContext, refreshContexts,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

/** Opção única representando o contexto atual (usada com troca pendente). */
function currentAsOption(ctx: ActiveContext): ContextOption {
  if (ctx.scope === 'ilpi' && ctx.ilpi_id) {
    return { key: `ilpi:${ctx.ilpi_id}`, scope: 'ilpi', ilpi_id: ctx.ilpi_id, label: ctx.ilpiNome || 'ILPI', sublabel: 'Contexto atual' }
  }
  return { key: 'global', scope: 'global', label: 'Plataforma', sublabel: 'Contexto atual' }
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

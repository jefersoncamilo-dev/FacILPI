import { describe, it, expect, beforeEach } from 'vitest'
import type { InternalAxiosRequestConfig } from 'axios'
import { api } from '../services/api'
import { TOKEN_KEY, decodeJwt, isTokenExpired, semAssinatura } from '../types/context'

// #207: credencial no cookie HttpOnly; o cliente só guarda claims e devolve o CSRF.

function aplicar(method: string) {
  const handlers = (api.interceptors.request as unknown as {
    handlers: { fulfilled: (c: InternalAxiosRequestConfig) => InternalAxiosRequestConfig }[]
  }).handlers
  const config = { method, headers: {} } as InternalAxiosRequestConfig
  return handlers.reduce((c, h) => h.fulfilled(c), config)
}

function limparCookies() {
  document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
}

describe('#207 sessão em cookie', () => {
  beforeEach(() => { localStorage.clear(); limparCookies() })

  it('envia cookies e nunca o Bearer', () => {
    localStorage.setItem(TOKEN_KEY, 'a.b.c')
    expect(api.defaults.withCredentials).toBe(true)
    expect(aplicar('post').headers.Authorization).toBeUndefined()
  })

  it('devolve o csrf no cabeçalho só em métodos mutáveis', () => {
    document.cookie = 'csrf_token=abc%2D1; path=/'
    expect(aplicar('post').headers['X-CSRF-Token']).toBe('abc-1')
    expect(aplicar('delete').headers['X-CSRF-Token']).toBe('abc-1')
    expect(aplicar('get').headers['X-CSRF-Token']).toBeUndefined()
  })

  it('semAssinatura preserva as claims e descarta a assinatura', () => {
    const payload = btoa(JSON.stringify({ sub: 'u1', exp: Math.floor(Date.now() / 1000) + 3600 }))
      .replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_')
    const token = `eyJhbGciOiJIUzI1NiJ9.${payload}.assinatura-secreta`
    const guardado = semAssinatura(token)
    expect(guardado).not.toContain('assinatura-secreta')
    expect(decodeJwt(guardado)?.sub).toBe('u1')
    expect(isTokenExpired(guardado)).toBe(false)
  })
})

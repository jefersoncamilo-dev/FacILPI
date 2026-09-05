import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthProvider, useAuth } from '../context/AuthContext'
import { ContextSwitcher } from '../components/ContextSwitcher'
import { api } from '../services/api'
import { contextApi } from '../services/context'
import { TOKEN_KEY, USER_KEY, CONTEXT_KEY } from '../types/context'

vi.mock('../services/api', () => ({
  api: { post: vi.fn(), get: vi.fn(), put: vi.fn() },
}))

vi.mock('../services/context', () => ({
  contextApi: { selectContext: vi.fn(), listInstitutions: vi.fn(), listPerfis: vi.fn() },
  resolveContextLabels: vi.fn(async (ctx: any) => ctx),
}))

const mockPost = vi.mocked(api.post)
const mockSelect = vi.mocked(contextApi.selectContext)
const mockListInst = vi.mocked(contextApi.listInstitutions)

function jwt(payload: object): string {
  const b64 = (o: object) =>
    btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${b64({ alg: 'HS256' })}.${b64(payload)}.sig`
}

const FUTURE = Math.floor(Date.now() / 1000) + 3600
const GLOBAL_TOKEN = jwt({ sub: 'u-admin', email: 'admin@ilpi.com', is_superuser: true, exp: FUTURE })
const ILPI_TOKEN = jwt({ sub: 'u-admin', email: 'admin@ilpi.com', scope: 'ilpi', ilpi_id: 'ilpi1', perfil_id: 'p1', exp: FUTURE })
const ILPI_LIST = [{ id: 'ilpi1', razao_social: 'ILPI Modelo', nome_fantasia: null, situacao: 'ILPI_RASCUNHO' }]

function Harness({ onReady }: { onReady: (ctx: ReturnType<typeof useAuth>) => void }) {
  const ctx = useAuth()
  onReady(ctx)
  return null
}

function renderAuth(extra?: ReactNode) {
  let captured: ReturnType<typeof useAuth> | null = null
  const utils = render(
    <AuthProvider>
      <Harness onReady={(c) => { captured = c }} />
      {extra}
    </AuthProvider>,
  )
  return { ...utils, get: () => captured as unknown as ReturnType<typeof useAuth> }
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  mockListInst.mockResolvedValue({ data: ILPI_LIST } as any)
})

describe('ContextSwitch — login e contexto', () => {
  it('1. login global persiste token e contexto Plataforma', async () => {
    mockPost.mockResolvedValueOnce({ data: { access_token: GLOBAL_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    const { get } = renderAuth()
    await get().login('admin@ilpi.com', 'senha')
    await waitFor(() => expect(localStorage.getItem(TOKEN_KEY)).toBe(GLOBAL_TOKEN))
    expect(get().activeContext?.scope).toBe('global')
    expect(get().availableContexts.length).toBe(2)
  })

  it('2. contexto atual exibido (Plataforma)', async () => {
    mockPost.mockResolvedValueOnce({ data: { access_token: GLOBAL_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    const { get } = renderAuth(<ContextSwitcher />)
    await get().login('admin@ilpi.com', 'senha')
    expect(await screen.findByText('Plataforma')).toBeTruthy()
  })

  it('3. seleção ILPI chama /auth/contexto corretamente (sem perfil fabricado)', async () => {
    mockPost.mockResolvedValueOnce({ data: { access_token: GLOBAL_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    mockSelect.mockResolvedValueOnce({ data: { access_token: ILPI_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    const { get } = renderAuth()
    await get().login('admin@ilpi.com', 'senha')
    await waitFor(() => expect(get().availableContexts.length).toBe(2))
    const opt = get().availableContexts.find(o => o.scope === 'ilpi')!
    await get().switchContext(opt)
    expect(mockSelect).toHaveBeenCalledWith({ scope: 'ilpi', ilpi_id: 'ilpi1' })
  })

  it('4. token ativo é substituído após a troca', async () => {
    mockPost.mockResolvedValueOnce({ data: { access_token: GLOBAL_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    mockSelect.mockResolvedValueOnce({ data: { access_token: ILPI_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    const { get } = renderAuth()
    await get().login('admin@ilpi.com', 'senha')
    await waitFor(() => expect(get().availableContexts.length).toBe(2))
    await get().switchContext(get().availableContexts.find(o => o.scope === 'ilpi')!)
    expect(localStorage.getItem(TOKEN_KEY)).toBe(ILPI_TOKEN)
    await waitFor(() => expect(get().activeContext?.scope).toBe('ilpi'))
  })

  it('5. troca dispara recarregamento dos dados (/equipe escuta o evento)', async () => {
    mockPost.mockResolvedValueOnce({ data: { access_token: GLOBAL_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    mockSelect.mockResolvedValueOnce({ data: { access_token: ILPI_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    const events: string[] = []
    const listener = () => events.push('changed')
    window.addEventListener('facilpi:context-changed', listener)
    try {
      const { get } = renderAuth()
      await get().login('admin@ilpi.com', 'senha')
      await waitFor(() => expect(get().availableContexts.length).toBe(2))
      await get().switchContext(get().availableContexts.find(o => o.scope === 'ilpi')!)
      expect(events).toContain('changed')
    } finally {
      window.removeEventListener('facilpi:context-changed', listener)
    }
  })

  it('6. reload da página preserva o contexto quando o token é válido', async () => {
    localStorage.setItem(TOKEN_KEY, ILPI_TOKEN)
    localStorage.setItem(USER_KEY, JSON.stringify({ id: 'u-admin', nome: 'admin', email: 'admin@ilpi.com' }))
    localStorage.setItem(CONTEXT_KEY, JSON.stringify({ scope: 'ilpi', ilpi_id: 'ilpi1', perfil_id: 'p1', ilpiNome: 'ILPI Modelo', perfilNome: 'Administrador' }))
    const { get } = renderAuth()
    await waitFor(() => expect(get().activeContext?.scope).toBe('ilpi'))
    expect(get().activeContext?.ilpi_id).toBe('ilpi1')
    render(
      <AuthProvider>
        <ContextSwitcher />
      </AuthProvider>,
    )
    expect(await screen.findByText('ILPI Modelo')).toBeTruthy()
  })

  it('7. troca de volta para global usa payload {scope:global}', async () => {
    localStorage.setItem(TOKEN_KEY, ILPI_TOKEN)
    localStorage.setItem(USER_KEY, JSON.stringify({ id: 'u-admin', nome: 'admin', email: 'admin@ilpi.com' }))
    localStorage.setItem(CONTEXT_KEY, JSON.stringify({ scope: 'ilpi', ilpi_id: 'ilpi1' }))
    mockSelect.mockResolvedValueOnce({ data: { access_token: GLOBAL_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    const { get } = renderAuth()
    await waitFor(() => expect(get().activeContext?.scope).toBe('ilpi'))
    await get().switchContext({ key: 'global', scope: 'global', label: 'Plataforma', sublabel: 'Superusuário' })
    expect(mockSelect).toHaveBeenCalledWith({ scope: 'global' })
    expect(localStorage.getItem(TOKEN_KEY)).toBe(GLOBAL_TOKEN)
    await waitFor(() => expect(get().activeContext?.scope).toBe('global'))
  })

  it('8. contexto não autorizado é rejeitado e o token permanece', async () => {
    mockPost.mockResolvedValueOnce({ data: { access_token: GLOBAL_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    mockSelect.mockRejectedValueOnce({ response: { status: 403, data: { detail: { code: 'AUTH_CONTEXT_REQUIRED', message: 'Contexto de autorização não disponível' } } } })
    const { get } = renderAuth()
    await get().login('admin@ilpi.com', 'senha')
    await waitFor(() => expect(get().availableContexts.length).toBe(2))
    await expect(get().switchContext(get().availableContexts.find(o => o.scope === 'ilpi')!)).rejects.toBeTruthy()
    expect(localStorage.getItem(TOKEN_KEY)).toBe(GLOBAL_TOKEN)
    await waitFor(() => expect(get().contextError).toContain('Contexto de autorização não disponível'))
  })

  it('9. erro de troca é exibido na UI (sem alert)', async () => {
    const user = userEvent.setup()
    mockPost.mockResolvedValueOnce({ data: { access_token: GLOBAL_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    mockSelect.mockRejectedValueOnce({ response: { status: 403, data: { detail: { code: 'PERMISSION_DENIED', message: 'Permissão não autorizada' } } } })
    const { get } = renderAuth(<ContextSwitcher />)
    await get().login('admin@ilpi.com', 'senha')
    const btn = await screen.findByLabelText('Contexto atual')
    await user.click(btn)
    const opt = await screen.findByText('ILPI Modelo')
    await user.click(opt)
    expect(await screen.findByText('Permissão não autorizada')).toBeTruthy()
  })

  it('10. usuário de contexto único não recebe picker', async () => {
    const SINGLE = jwt({ sub: 'u2', email: 'cuidador@ilpi.com', scope: 'ilpi', ilpi_id: 'ilpi1', perfil_id: 'p2', exp: FUTURE })
    mockPost.mockResolvedValueOnce({ data: { access_token: SINGLE, token_type: 'bearer', exige_troca_senha: false } } as any)
    const { get } = renderAuth()
    const { options: opts } = await get().login('cuidador@ilpi.com', 'senha')
    expect(opts.length).toBe(1)
    expect(opts[0].scope).toBe('ilpi')
  })
})

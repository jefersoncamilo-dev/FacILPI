import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthProvider, useAuth } from '../context/AuthContext'
import { ContextSwitcher } from '../components/ContextSwitcher'
import { api } from '../services/api'
import { contextApi } from '../services/context'
import { TOKEN_KEY, USER_KEY, CONTEXT_KEY } from '../types/context'

// Preserva os helpers reais do módulo (mensagemDeErro, formatDate…): substituir o módulo
// inteiro deixaria essas funções indefinidas nas telas sob teste.
vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { post: vi.fn(), get: vi.fn(), put: vi.fn() } }
})

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
// Usuário com vínculo em duas ILPIs: a transição ilpi1 -> ilpi2 é aceita pelo backend.
const GESTOR_ILPI1 = jwt({ sub: 'u-gestor', email: 'gestor@ilpi.com', scope: 'ilpi', ilpi_id: 'ilpi1', perfil_id: 'p1', exp: FUTURE })
const GESTOR_ILPI2 = jwt({ sub: 'u-gestor', email: 'gestor@ilpi.com', scope: 'ilpi', ilpi_id: 'ilpi2', perfil_id: 'p2', exp: FUTURE })
const OPCAO_ILPI2 = { key: 'ilpi:ilpi2', scope: 'ilpi' as const, ilpi_id: 'ilpi2', label: 'ILPI 2', sublabel: 'Contexto institucional' }
// Token global reemitido: difere do primeiro para provar a substituição.
const GLOBAL_TOKEN_2 = jwt({ sub: 'u-admin', email: 'admin@ilpi.com', is_superuser: true, exp: FUTURE, jti: 'reemitido' })

function semearGestor() {
  localStorage.setItem(TOKEN_KEY, GESTOR_ILPI1)
  localStorage.setItem(USER_KEY, JSON.stringify({ id: 'u-gestor', nome: 'gestor', email: 'gestor@ilpi.com' }))
  localStorage.setItem(CONTEXT_KEY, JSON.stringify({ scope: 'ilpi', ilpi_id: 'ilpi1', perfil_id: 'p1' }))
}

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
  // PH02-04 (#72 / H01): os testes 1, 3, 4, 5, 8 e 9 simulavam o superusuário
  // recebendo e escolhendo ILPIs como contexto, com /auth/contexto mockado em
  // sucesso — uma troca que o backend real recusa (403 AUTH_CONTEXT_REQUIRED). O 7
  // mockava uma volta ILPI -> global de quem não tem vínculo global. Foram
  // recriados sobre transições que o backend aceita: o superusuário fica na
  // Plataforma, e a mecânica de switchContext é exercida por um usuário com
  // vínculo em duas ILPIs.
  it('1. login do superusuário oferece só Plataforma — ILPIs visíveis não viram contexto', async () => {
    mockPost.mockResolvedValueOnce({ data: { access_token: GLOBAL_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    const { get } = renderAuth()
    const { options } = await get().login('admin@ilpi.com', 'senha')
    expect(options).toHaveLength(1)
    expect(options[0].scope).toBe('global')
    await waitFor(() => {
      expect(get().activeContext?.scope).toBe('global')
      expect(get().availableContexts).toHaveLength(1)
    })
    expect(localStorage.getItem(TOKEN_KEY)).toBe(GLOBAL_TOKEN)
    // A lista de ILPIs não é mais consultada para montar opções de contexto.
    expect(mockListInst).not.toHaveBeenCalled()
  })

  it('2. contexto atual exibido (Plataforma)', async () => {
    mockPost.mockResolvedValueOnce({ data: { access_token: GLOBAL_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    const { get } = renderAuth(<ContextSwitcher />)
    await get().login('admin@ilpi.com', 'senha')
    expect(await screen.findByText('Plataforma')).toBeTruthy()
  })

  it('3. troca entre ILPIs chama /auth/contexto corretamente (sem perfil fabricado)', async () => {
    semearGestor()
    mockSelect.mockResolvedValueOnce({ data: { access_token: GESTOR_ILPI2, token_type: 'bearer', exige_troca_senha: false } } as any)
    const { get } = renderAuth()
    await waitFor(() => expect(get().activeContext?.ilpi_id).toBe('ilpi1'))
    await get().switchContext(OPCAO_ILPI2)
    expect(mockSelect).toHaveBeenCalledWith({ scope: 'ilpi', ilpi_id: 'ilpi2' })
  })

  it('4. token ativo é substituído após a troca', async () => {
    semearGestor()
    mockSelect.mockResolvedValueOnce({ data: { access_token: GESTOR_ILPI2, token_type: 'bearer', exige_troca_senha: false } } as any)
    const { get } = renderAuth()
    await waitFor(() => expect(get().activeContext?.ilpi_id).toBe('ilpi1'))
    await get().switchContext(OPCAO_ILPI2)
    expect(localStorage.getItem(TOKEN_KEY)).toBe(GESTOR_ILPI2)
    await waitFor(() => expect(get().activeContext?.ilpi_id).toBe('ilpi2'))
  })

  it('5. troca dispara recarregamento dos dados (/equipe escuta o evento)', async () => {
    semearGestor()
    mockSelect.mockResolvedValueOnce({ data: { access_token: GESTOR_ILPI2, token_type: 'bearer', exige_troca_senha: false } } as any)
    const events: string[] = []
    const listener = () => events.push('changed')
    window.addEventListener('facilpi:context-changed', listener)
    try {
      const { get } = renderAuth()
      await waitFor(() => expect(get().activeContext?.ilpi_id).toBe('ilpi1'))
      await get().switchContext(OPCAO_ILPI2)
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

  it('7. contexto global é reemitido com payload {scope:global}', async () => {
    // Transição que o backend aceita: o superusuário, já na Plataforma, pede o
    // contexto global de novo e recebe um token novo.
    localStorage.setItem(TOKEN_KEY, GLOBAL_TOKEN)
    localStorage.setItem(USER_KEY, JSON.stringify({ id: 'u-admin', nome: 'admin', email: 'admin@ilpi.com' }))
    localStorage.setItem(CONTEXT_KEY, JSON.stringify({ scope: 'global' }))
    mockSelect.mockResolvedValueOnce({ data: { access_token: GLOBAL_TOKEN_2, token_type: 'bearer', exige_troca_senha: false } } as any)
    const { get } = renderAuth()
    await waitFor(() => expect(get().activeContext?.scope).toBe('global'))
    await get().switchContext({ key: 'global', scope: 'global', label: 'Plataforma', sublabel: 'Superusuário' })
    expect(mockSelect).toHaveBeenCalledWith({ scope: 'global' })
    expect(localStorage.getItem(TOKEN_KEY)).toBe(GLOBAL_TOKEN_2)
    await waitFor(() => expect(get().activeContext?.scope).toBe('global'))
  })

  it('8. troca recusada pelo backend mantém o token e expõe o erro', async () => {
    // Ex.: o vínculo com a ILPI 2 foi revogado entre a listagem e o clique.
    semearGestor()
    mockSelect.mockRejectedValueOnce({ response: { status: 403, data: { detail: { code: 'AUTH_CONTEXT_REQUIRED', message: 'Contexto de autorização não disponível' } } } })
    const { get } = renderAuth()
    await waitFor(() => expect(get().activeContext?.ilpi_id).toBe('ilpi1'))
    await expect(get().switchContext(OPCAO_ILPI2)).rejects.toBeTruthy()
    expect(localStorage.getItem(TOKEN_KEY)).toBe(GESTOR_ILPI1)
    await waitFor(() => expect(get().contextError).toContain('Contexto de autorização não disponível'))
  })

  it('9. seletor do superusuário não oferece ILPI — nenhum 403 provocado pela UI', async () => {
    const user = userEvent.setup()
    mockPost.mockResolvedValueOnce({ data: { access_token: GLOBAL_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    const { get } = renderAuth(<ContextSwitcher />)
    await get().login('admin@ilpi.com', 'senha')
    const btn = await screen.findByLabelText('Contexto atual')
    expect(btn).toBeDisabled()
    await user.click(btn)
    expect(screen.queryByText('ILPI Modelo')).toBeNull()
    expect(screen.queryByText('Trocar para esta ILPI')).toBeNull()
    expect(mockSelect).not.toHaveBeenCalled()
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

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { Login } from '../pages/Login'
import { Placeholder } from '../pages/Placeholder'
import { Layout } from '../components/Layout'
import { api } from '../services/api'
import { contextApi } from '../services/context'
import { TOKEN_KEY, USER_KEY, CONTEXT_KEY, SESSION_ENDED_KEY } from '../types/context'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
})

vi.mock('../services/context', () => ({
  contextApi: {
    selectContext: vi.fn(),
    listInstitutions: vi.fn(async () => ({ data: [] })),
    listPerfis: vi.fn(async () => ({ data: [] })),
    permissoesDaSessao: vi.fn(),
  },
  resolveContextLabels: vi.fn(async (ctx: any) => ctx),
  logoutServidor: vi.fn(async () => ({ data: {} })),
}))

const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

function jwt(payload: object): string {
  const b64 = (o: object) =>
    btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${b64({ alg: 'HS256' })}.${b64(payload)}.sig`
}

function seedSessao() {
  const exp = Math.floor(Date.now() / 1000) + 3600
  localStorage.setItem(TOKEN_KEY, jwt({ sub: 'u1', email: 'gestora@ilpi.com', scope: 'ilpi', ilpi_id: 'ilpi1', perfil_id: 'p1', exp }))
  localStorage.setItem(USER_KEY, JSON.stringify({ id: 'u1', nome: 'gestora', email: 'gestora@ilpi.com' }))
  localStorage.setItem(CONTEXT_KEY, JSON.stringify({ scope: 'ilpi', ilpi_id: 'ilpi1' }))
}

function renderShell(conteudo = <div>conteúdo</div>) {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={['/']}>
        <Layout>{conteudo}</Layout>
      </MemoryRouter>
    </AuthProvider>,
  )
}

function menu() {
  return within(screen.getByRole('navigation', { name: 'Navegação principal' }))
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
  vi.mocked(api.get).mockResolvedValue({ data: [] } as any)
})

describe('UX-01 — sessão encerrada explicada no login', () => {
  it('mostra o aviso e só consome a marca quando a pessoa tenta entrar', async () => {
    const user = userEvent.setup()
    sessionStorage.setItem(SESSION_ENDED_KEY, '1')
    vi.mocked(api.post).mockRejectedValueOnce({ response: { status: 401, data: { detail: 'Credenciais inválidas' } } })
    const primeira = render(<AuthProvider><MemoryRouter><Login /></MemoryRouter></AuthProvider>)
    expect(screen.getByText('Sua sessão foi encerrada')).toBeTruthy()

    // Um segundo carregamento (o reload pedido pelo interceptor) ainda vê a marca.
    primeira.unmount()
    render(<AuthProvider><MemoryRouter><Login /></MemoryRouter></AuthProvider>)
    expect(screen.getByText('Sua sessão foi encerrada')).toBeTruthy()

    await user.type(screen.getByPlaceholderText('E-mail'), 'alguem@ilpi.com')
    await user.type(screen.getByPlaceholderText('Senha'), 'Senha1234')
    await user.click(screen.getByRole('button', { name: 'Entrar' }))
    expect(await screen.findByText('Credenciais inválidas')).toBeTruthy()
    expect(sessionStorage.getItem(SESSION_ENDED_KEY)).toBeNull()
    expect(screen.queryByText('Sua sessão foi encerrada')).toBeNull()
  })

  it('não mostra o aviso num acesso comum', () => {
    render(<AuthProvider><MemoryRouter><Login /></MemoryRouter></AuthProvider>)
    expect(screen.queryByText('Sua sessão foi encerrada')).toBeNull()
  })
})

describe('UX-01 — conta com vários vínculos recebe explicação honesta', () => {
  it('não pede uma escolha de contexto que a tela não oferece', async () => {
    const user = userEvent.setup()
    vi.mocked(api.post).mockRejectedValueOnce({
      response: { status: 403, data: { detail: { code: 'PROFILE_SELECTION_REQUIRED', message: 'Selecione um perfil e contexto' } } },
    })
    render(<AuthProvider><MemoryRouter><Login /></MemoryRouter></AuthProvider>)

    await user.type(screen.getByPlaceholderText('E-mail'), 'multi@ilpi.com')
    await user.type(screen.getByPlaceholderText('Senha'), 'Senha1234')
    await user.click(screen.getByRole('button', { name: 'Entrar' }))

    expect(await screen.findByText(/vinculada a mais de uma instituição/)).toBeTruthy()
    expect(screen.queryByText('Selecione um perfil e contexto')).toBeNull()
  })
})

describe('UX-01 — navegação reflete as permissões do contexto', () => {
  it('só oferece o que a sessão pode abrir', async () => {
    seedSessao()
    mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', ilpi_id: 'ilpi1', permissoes: ['residentes:ler', 'sinais_vitais:ler'] } } as any)
    renderShell()

    expect(await menu().findByRole('link', { name: /Residentes/ })).toBeTruthy()
    expect(menu().getByRole('link', { name: /Início/ })).toBeTruthy()
    expect(menu().getByRole('link', { name: /Sinais Vitais/ })).toBeTruthy()
    expect(menu().queryByRole('link', { name: /Meu Plantão/ })).toBeNull()
    expect(menu().queryByRole('link', { name: /Equipe/ })).toBeNull()
    expect(menu().queryByRole('link', { name: /Admissões/ })).toBeNull()
  })

  it('marca como "Em breve" a tela ainda não entregue, sem esconder a permissão', async () => {
    seedSessao()
    mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes: ['plantao:ler', 'avaliacoes:ler'] } } as any)
    renderShell()

    const passagem = await menu().findByRole('link', { name: /Passagem de Plantão/ })
    expect(within(passagem).getByText('Em breve')).toBeTruthy()
    // Entregue na UX-06 (#79): deixa de ser "Em breve".
    expect(within(menu().getByRole('link', { name: /Avaliações/ })).queryByText('Em breve')).toBeNull()
  })

  it('sem o endpoint, mostra os módulos prontos e deixa o backend decidir', async () => {
    seedSessao()
    mockPermissoes.mockRejectedValue({ response: { status: 404, data: { detail: 'Not Found' } } })
    renderShell()

    expect(await menu().findByRole('link', { name: /Meu Plantão/ })).toBeTruthy()
    expect(menu().getByRole('link', { name: /Equipe/ })).toBeTruthy()
  })

  it('módulos sem tela nem jornada nesta fase não aparecem no menu', async () => {
    seedSessao()
    mockPermissoes.mockRejectedValue(new Error('offline'))
    renderShell()

    await menu().findByRole('link', { name: /Residentes/ })
    for (const nome of ['Financeiro', 'Estoque', 'Compliance e Fiscalização', 'Auditoria', 'Configurações']) {
      expect(menu().queryByRole('link', { name: nome })).toBeNull()
    }
  })
})

describe('UX-01 — erros de tela não derrubam o shell (Issue #32)', () => {
  it('um erro de render mostra o estado de erro e mantém a navegação', async () => {
    seedSessao()
    mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes: [] } } as any)
    const erroConsole = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    function Quebra(): JSX.Element {
      throw new Error('falha de render')
    }
    renderShell(<Quebra />)

    await waitFor(() => expect(screen.getByText('Algo deu errado')).toBeTruthy())
    expect(screen.getByRole('button', { name: 'Tentar novamente' })).toBeTruthy()
    expect(menu().getByRole('link', { name: /Início/ })).toBeTruthy()
    erroConsole.mockRestore()
  })
})

describe('UX-01 — placeholder não promete o que não existe', () => {
  it('não afirma API pronta nem responsividade validada', () => {
    render(<MemoryRouter><Placeholder title="Estoque" /></MemoryRouter>)
    expect(screen.getByText('Módulo ainda não disponível')).toBeTruthy()
    expect(screen.queryByText(/API pronta/)).toBeNull()
    expect(screen.queryByText(/validadas em 360/)).toBeNull()
  })
})

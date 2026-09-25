import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider, useAuth } from '../context/AuthContext'
import { Residentes } from '../pages/Residentes'
import { Login } from '../pages/Login'
import { Layout } from '../components/Layout'
import { api } from '../services/api'
import { logoutServidor } from '../services/context'
import { TOKEN_KEY, USER_KEY, CONTEXT_KEY } from '../types/context'
import { cnpjEhValido, ufEhValida, UF_VALIDAS } from '../types/platform'

// Preserva os helpers reais (mensagemDeErro, formatDate): substituir o módulo
// inteiro os deixaria indefinidos nas telas sob teste.
vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
})

vi.mock('../services/context', () => ({
  contextApi: {
    selectContext: vi.fn(),
    listInstitutions: vi.fn(async () => ({ data: [] })),
    listPerfis: vi.fn(async () => ({ data: [] })),
  },
  resolveContextLabels: vi.fn(async (ctx: any) => ctx),
  logoutServidor: vi.fn(async () => ({ data: { mensagem: 'Sessão encerrada' } })),
}))

const mockGet = vi.mocked(api.get)
const mockLogout = vi.mocked(logoutServidor)

function jwt(payload: object): string {
  const b64 = (o: object) =>
    btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${b64({ alg: 'HS256' })}.${b64(payload)}.sig`
}

const FUTURE = Math.floor(Date.now() / 1000) + 3600
const TOKEN_ILPI = jwt({
  sub: 'u1', email: 'gestor@ilpi.com', scope: 'ilpi', ilpi_id: 'ilpi1', perfil_id: 'p1', exp: FUTURE,
})

const RESIDENTES = [
  { id: 'r1', nome: 'Maria Silva', situacao: 'Ativo', data_nascimento: '1940-03-02', sexo: 'F', cpf: null },
  { id: 'r2', nome: 'Joao Souza', situacao: 'Ativo', data_nascimento: '1938-07-11', sexo: 'M', cpf: null },
]

function erroHttp(status: number) {
  return { response: { status, data: { detail: { code: 'PERMISSION_DENIED', message: 'Permissão não autorizada' } } } }
}

function seedSessao() {
  localStorage.setItem(TOKEN_KEY, TOKEN_ILPI)
  localStorage.setItem(USER_KEY, JSON.stringify({ id: 'u1', nome: 'Gestor', email: 'gestor@ilpi.com' }))
  localStorage.setItem(CONTEXT_KEY, JSON.stringify({ scope: 'ilpi', ilpi_id: 'ilpi1' }))
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// PH-01 item 1 — INSTITUICAO_FORM_UF_CNPJ (espelhos de contrato)
// ---------------------------------------------------------------------------

describe('PH-01/1 — espelhos do contrato de instituição', () => {
  it('UF_VALIDAS tem exatamente as 27 siglas do backend', () => {
    expect(UF_VALIDAS).toHaveLength(27)
    // Amostra dos casos que o defeito real produziu.
    expect(ufEhValida('PR')).toBe(true)
    expect(ufEhValida('pr')).toBe(true)
    expect(ufEhValida(' SP ')).toBe(true)
    expect(ufEhValida('Paraná')).toBe(false)
    expect(ufEhValida('XX')).toBe(false)
    expect(ufEhValida('')).toBe(false)
  })

  it('cnpjEhValido reproduz o dígito verificador do backend', () => {
    // CNPJs sintéticos com DV correto (nenhuma empresa real).
    expect(cnpjEhValido('11.222.333/0001-81')).toBe(true)
    expect(cnpjEhValido('11222333000181')).toBe(true)
    // Um dígito trocado no final: é exatamente o erro de digitação que gerava 422.
    expect(cnpjEhValido('11.222.333/0001-82')).toBe(false)
    // Tamanho errado e repetição — as duas recusas explícitas do validators.py.
    expect(cnpjEhValido('1122233300018')).toBe(false)
    expect(cnpjEhValido('00000000000000')).toBe(false)
    expect(cnpjEhValido('')).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// PH-01 item 2 — LEGACY_PAGES_SILENT_FAILURE (Residentes)
// ---------------------------------------------------------------------------

describe('PH-01/2 — Residentes distingue os quatro estados', () => {
  function renderResidentes() {
    return render(<MemoryRouter><Residentes /></MemoryRouter>)
  }

  it('carregando não afirma contagem alguma', async () => {
    let liberar: (v: unknown) => void = () => {}
    mockGet.mockImplementation(() => new Promise(res => { liberar = res }))
    renderResidentes()

    expect(await screen.findByText('Carregando residentes…')).toBeTruthy()
    expect(screen.queryByText(/residentes$/)).toBeNull()

    liberar({ data: [] })
    await waitFor(() => expect(screen.queryByText('Carregando residentes…')).toBeNull())
  })

  it('403 mostra acesso negado, não "0 residentes"', async () => {
    mockGet.mockRejectedValue(erroHttp(403))
    renderResidentes()

    expect(await screen.findByText('Você não tem permissão para ver os residentes')).toBeTruthy()
    expect(screen.queryByText('0 residentes')).toBeNull()
    expect(screen.queryByText('Nenhum residente cadastrado')).toBeNull()
  })

  it('falha de consulta mostra erro e diz que não significa ausência', async () => {
    mockGet.mockRejectedValue(new Error('Network Error'))
    renderResidentes()

    expect(await screen.findByText('Isso não significa que não há residentes cadastrados.')).toBeTruthy()
    expect(screen.queryByText('0 residentes')).toBeNull()
    expect(screen.getByRole('button', { name: 'Tentar novamente' })).toBeTruthy()
  })

  it('"Tentar novamente" repete a consulta e recupera a lista', async () => {
    const user = userEvent.setup()
    mockGet.mockRejectedValueOnce(new Error('Network Error'))
    renderResidentes()

    const botao = await screen.findByRole('button', { name: 'Tentar novamente' })
    // A resposta boa precisa estar armada ANTES do clique: o retry dispara a
    // consulta de forma síncrona.
    mockGet.mockResolvedValue({ data: RESIDENTES } as any)
    await user.click(botao)

    await waitFor(() => expect(screen.queryByRole('button', { name: 'Tentar novamente' })).toBeNull())
    expect(await screen.findByText('Maria Silva')).toBeTruthy()
  })

  it('zero legítimo continua sendo zero', async () => {
    mockGet.mockResolvedValue({ data: [] } as any)
    renderResidentes()

    expect(await screen.findByText('Nenhum residente cadastrado')).toBeTruthy()
    expect(screen.getByText('0 residentes')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('lista carregada mostra contagem real', async () => {
    mockGet.mockResolvedValue({ data: RESIDENTES } as any)
    renderResidentes()

    expect(await screen.findByText('Maria Silva')).toBeTruthy()
    expect(screen.getByText('2 residentes')).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// PH-01 item 3 — REGISTER_DEAD_PATH
// ---------------------------------------------------------------------------

describe('PH-01/3 — login não oferece autocadastro', () => {
  it('não há convite "Cadastre-se" nem link para /register', () => {
    const { container } = render(<AuthProvider><MemoryRouter><Login /></MemoryRouter></AuthProvider>)

    expect(screen.queryByText(/Cadastre-se/i)).toBeNull()
    expect(container.querySelector('a[href="/register"]')).toBeNull()
    expect(screen.getByText(/O acesso é criado pela sua instituição/)).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// PH-01 item 4 — LOGOUT_NOT_SERVER_SIDE
// ---------------------------------------------------------------------------

describe('PH-01/4 — sair avisa o servidor e limpa sempre', () => {
  // `logout` navega via window.location.href; em jsdom isso é um no-op ruidoso,
  // então a propriedade é substituída e restaurada por teste.
  let href = ''
  beforeEach(() => {
    href = ''
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, get href() { return href }, set href(v: string) { href = v } },
    })
  })
  afterEach(() => vi.restoreAllMocks())

  function Harness({ capture }: { capture: (c: ReturnType<typeof useAuth>) => void }) {
    capture(useAuth())
    return null
  }

  async function sair() {
    let ctx: ReturnType<typeof useAuth> | null = null
    render(<AuthProvider><Harness capture={c => { ctx = c }} /></AuthProvider>)
    await waitFor(() => expect(ctx).not.toBeNull())
    await ctx!.logout()
  }

  it('chama POST /auth/logout antes de limpar a sessão local', async () => {
    seedSessao()
    await sair()

    expect(mockLogout).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(localStorage.getItem(USER_KEY)).toBeNull()
    expect(localStorage.getItem(CONTEXT_KEY)).toBeNull()
    expect(href).toBe('/login')
  })

  it('falha da chamada NÃO impede a saída local', async () => {
    seedSessao()
    mockLogout.mockRejectedValueOnce(new Error('Network Error'))
    await sair()

    expect(mockLogout).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(localStorage.getItem(CONTEXT_KEY)).toBeNull()
    expect(href).toBe('/login')
  })

  it('o serviço mantém withCredentials como prova adicional do cookie', async () => {
    // PH-02/PR-2: em runtime o interceptor de api.ts também anexa o Bearer,
    // que é a prova principal no split-origin. Este teste unitário confirma
    // apenas que o cookie continua habilitado quando o navegador puder enviá-lo.
    const real = await vi.importActual<typeof import('../services/context')>('../services/context')
    await real.logoutServidor()
    const [url, corpo, config] = vi.mocked(api.post).mock.calls[0]
    expect(url).toBe('/auth/logout')
    expect(corpo).toBeNull()
    expect(config).toMatchObject({ withCredentials: true })
  })
})

// ---------------------------------------------------------------------------
// PH-01 item 5 — MOBILE_AVATAR_IS_LOGOUT
// ---------------------------------------------------------------------------

describe('PH-01/5 — avatar não desloga', () => {
  it('o avatar não é botão e existe uma ação "Sair" explícita', async () => {
    seedSessao()
    mockGet.mockResolvedValue({ data: [] } as any)
    render(
      <AuthProvider>
        <MemoryRouter><Layout><div>conteúdo</div></Layout></MemoryRouter>
      </AuthProvider>,
    )

    await screen.findByText('conteúdo')

    // Nenhum botão é rotulado apenas pela inicial do usuário ("G" de Gestor).
    const botoes = screen.getAllByRole('button')
    expect(botoes.some(b => (b.textContent || '').trim() === 'G')).toBe(false)

    // Sair continua disponível — no menu lateral e no cabeçalho mobile.
    const sair = screen.getAllByRole('button', { name: 'Sair' })
    expect(sair.length).toBeGreaterThan(0)
  })

  it('clicar em "Sair" dispara o mesmo fluxo de logout', async () => {
    const user = userEvent.setup()
    seedSessao()
    mockGet.mockResolvedValue({ data: [] } as any)
    render(
      <AuthProvider>
        <MemoryRouter><Layout><div>conteúdo</div></Layout></MemoryRouter>
      </AuthProvider>,
    )
    await screen.findByText('conteúdo')

    await user.click(screen.getAllByRole('button', { name: 'Sair' })[0])
    await waitFor(() => expect(mockLogout).toHaveBeenCalled())
  })
})

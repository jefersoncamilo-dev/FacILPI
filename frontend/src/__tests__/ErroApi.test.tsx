import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, renderHook } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { Login } from '../pages/Login'
import { useEquipe } from '../hooks/useEquipe'
import { api, mensagemDeErro, ERRO_SEM_RESPOSTA } from '../services/api'
import { equipeApi } from '../services/equipe'

// Preserva os helpers reais; só o cliente HTTP é mockado.
vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { post: vi.fn(), get: vi.fn(), put: vi.fn() } }
})

vi.mock('../services/context', () => ({
  contextApi: { selectContext: vi.fn(), listInstitutions: vi.fn().mockResolvedValue({ data: [] }), listPerfis: vi.fn() },
  resolveContextLabels: vi.fn(async (ctx: any) => ctx),
}))

vi.mock('../services/equipe', () => ({
  equipeApi: { listFuncionarios: vi.fn(), listUsuarios: vi.fn(), listPerfis: vi.fn(), listPermissoes: vi.fn() },
}))

const mockPost = vi.mocked(api.post)

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

async function tentarLogin(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByPlaceholderText('E-mail'), 'alguem@ilpi.com')
  await user.type(screen.getByPlaceholderText('Senha'), 'Senha1234')
  await user.click(screen.getByRole('button', { name: 'Entrar' }))
}

// A aplicação continuar montada é o coração da Issue #29: antes, o erro de render
// desmontava a árvore inteira e a tela ficava branca.
function aplicacaoContinuaMontada() {
  return screen.queryByPlaceholderText('E-mail') !== null
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('mensagemDeErro — normalização do corpo de erro da API', () => {
  it('1. detail string é devolvido como está', () => {
    expect(mensagemDeErro({ response: { data: { detail: 'Senha expirada' } } }, 'padrao')).toBe('Senha expirada')
  })

  it('2. detail objeto devolve message e nunca expõe code', () => {
    const e = { response: { data: { detail: { code: 'AUTH_CONTEXT_REQUIRED', message: 'Contexto de autorização não disponível' } } } }
    const msg = mensagemDeErro(e, 'padrao')
    expect(msg).toBe('Contexto de autorização não disponível')
    expect(msg).not.toContain('AUTH_CONTEXT_REQUIRED')
  })

  it('3. detail array do 422 junta as mensagens de validação', () => {
    const e = { response: { data: { detail: [
      { type: 'value_error', loc: ['body', 'email'], msg: 'e-mail inválido' },
      { type: 'missing', loc: ['body', 'senha'], msg: 'campo obrigatório' },
    ] } } }
    expect(mensagemDeErro(e, 'padrao')).toBe('e-mail inválido; campo obrigatório')
  })

  it('4. erro sem response recebe mensagem própria, distinta de credencial inválida', () => {
    const msg = mensagemDeErro(new Error('Network Error'), 'Falha no login. Verifique credenciais.')
    expect(msg).toBe(ERRO_SEM_RESPOSTA)
    expect(msg).not.toContain('credenciais')
  })

  it('5. formatos inesperados caem no padrão, sem devolver objeto', () => {
    expect(mensagemDeErro({ response: { data: { detail: { semMessage: 1 } } } }, 'padrao')).toBe('padrao')
    expect(mensagemDeErro({ response: { data: {} } }, 'padrao')).toBe('padrao')
    expect(mensagemDeErro({ response: { data: { detail: [] } } }, 'padrao')).toBe('padrao')
    expect(typeof mensagemDeErro({ response: { data: { detail: { a: 1 } } } }, 'padrao')).toBe('string')
  })
})

describe('Login — erros estruturados não derrubam a aplicação (Issue #29)', () => {
  it('6. 403 com detail objeto exibe a mensagem e mantém a aplicação montada', async () => {
    const user = userEvent.setup()
    mockPost.mockRejectedValueOnce({
      response: { status: 403, data: { detail: { code: 'AUTH_CONTEXT_REQUIRED', message: 'Contexto de autorização não disponível' } } },
    })
    renderLogin()
    await tentarLogin(user)

    expect(await screen.findByText('Contexto de autorização não disponível')).toBeTruthy()
    expect(aplicacaoContinuaMontada()).toBe(true)
  })

  it('7. 422 com detail array exibe a mensagem de validação', async () => {
    const user = userEvent.setup()
    mockPost.mockRejectedValueOnce({
      response: { status: 422, data: { detail: [{ type: 'value_error', loc: ['body', 'email'], msg: 'e-mail inválido' }] } },
    })
    renderLogin()
    await tentarLogin(user)

    expect(await screen.findByText('e-mail inválido')).toBeTruthy()
    expect(aplicacaoContinuaMontada()).toBe(true)
  })

  it('8. detail string continua sendo exibido (sem regressão)', async () => {
    const user = userEvent.setup()
    mockPost.mockRejectedValueOnce({ response: { status: 400, data: { detail: 'Conta bloqueada' } } })
    renderLogin()
    await tentarLogin(user)

    expect(await screen.findByText('Conta bloqueada')).toBeTruthy()
  })

  it('9. falha sem resposta não acusa credencial inválida', async () => {
    const user = userEvent.setup()
    mockPost.mockRejectedValueOnce(new Error('Network Error'))
    renderLogin()
    await tentarLogin(user)

    expect(await screen.findByText(ERRO_SEM_RESPOSTA)).toBeTruthy()
    expect(screen.queryByText('Falha no login. Verifique credenciais.')).toBeNull()
  })
})

describe('useEquipe — detail array não vira valor não-renderizável (Classe B)', () => {
  it('10. erro 422 com array deixa `error` como string', async () => {
    vi.mocked(equipeApi.listFuncionarios).mockRejectedValueOnce({
      response: { status: 422, data: { detail: [{ type: 'value_error', loc: ['query', 'situacao'], msg: 'situação inválida' }] } },
    })
    const { result } = renderHook(() => useEquipe())
    await result.current.loadFuncionarios()

    await waitFor(() => expect(result.current.error).toBeTruthy())
    expect(typeof result.current.error).toBe('string')
    expect(result.current.error).toBe('situação inválida')
  })
})

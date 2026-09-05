import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider, useAuth } from '../context/AuthContext'
import { PrivateRoute } from '../components/PrivateRoute'
import { Login } from '../pages/Login'
import { PrimeiroAcesso } from '../pages/PrimeiroAcesso'
import { api } from '../services/api'
import { contextApi } from '../services/context'
import { TOKEN_KEY, USER_KEY } from '../types/context'

vi.mock('../services/api', () => ({
  api: { post: vi.fn(), get: vi.fn(), put: vi.fn() },
}))

vi.mock('../services/context', () => ({
  contextApi: { selectContext: vi.fn(), listInstitutions: vi.fn(), listPerfis: vi.fn() },
  resolveContextLabels: vi.fn(async (ctx: any) => ctx),
}))

const mockPost = vi.mocked(api.post)
const mockPut = vi.mocked(api.put)
const mockSelect = vi.mocked(contextApi.selectContext)
const mockListInst = vi.mocked(contextApi.listInstitutions)

function jwt(payload: object): string {
  const b64 = (o: object) =>
    btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${b64({ alg: 'HS256' })}.${b64(payload)}.sig`
}

const FUTURE = Math.floor(Date.now() / 1000) + 3600
const FLAG_TOKEN = jwt({ sub: 'u9', email: 'novo@ilpi.com', exige_troca_senha: true, exp: FUTURE })
const ILPI_TOKEN = jwt({ sub: 'u9', email: 'novo@ilpi.com', scope: 'ilpi', ilpi_id: 'ilpi1', perfil_id: 'p1', exp: FUTURE })

function renderAuth(extra?: ReactNode) {
  let captured: ReturnType<typeof useAuth> | null = null
  function Probe() {
    captured = useAuth()
    return null
  }
  const utils = render(
    <AuthProvider>
      <Probe />
      {extra}
    </AuthProvider>,
  )
  return { ...utils, get: () => captured as unknown as ReturnType<typeof useAuth> }
}

function seedPending() {
  localStorage.setItem(TOKEN_KEY, FLAG_TOKEN)
  localStorage.setItem(USER_KEY, JSON.stringify({ id: 'u9', nome: 'novo', email: 'novo@ilpi.com' }))
}

async function fillLogin(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByPlaceholderText('E-mail'), 'novo@ilpi.com')
  await user.type(screen.getByPlaceholderText('Senha'), 'Temp1234')
  await user.click(screen.getByRole('button', { name: 'Entrar' }))
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  mockListInst.mockResolvedValue({ data: [] } as any)
})

describe('FirstAccess — troca obrigatória', () => {
  it('1. login com exige_troca_senha=true marca requiresPasswordChange', async () => {
    mockPost.mockResolvedValueOnce({ data: { access_token: FLAG_TOKEN, token_type: 'bearer', exige_troca_senha: true } } as any)
    const { get } = renderAuth()
    const res = await get().login('novo@ilpi.com', 'Temp1234')
    expect(res.requiresPasswordChange).toBe(true)
    await waitFor(() => expect(get().requiresPasswordChange).toBe(true))
  })

  it('2. com flag, login NÃO navega para o dashboard', async () => {
    const user = userEvent.setup()
    mockPost.mockResolvedValueOnce({ data: { access_token: FLAG_TOKEN, token_type: 'bearer', exige_troca_senha: true } } as any)
    render(
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/primeiro-acesso" element={<div>TELA-PRIMEIRO-ACESSO</div>} />
            <Route path="/" element={<div>TELA-DASHBOARD</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )
    await fillLogin(user)
    await waitFor(() => expect(screen.queryByText('TELA-DASHBOARD')).toBeNull())
  })

  it('3. com flag, NÃO abre o context picker', async () => {
    const user = userEvent.setup()
    mockPost.mockResolvedValueOnce({ data: { access_token: FLAG_TOKEN, token_type: 'bearer', exige_troca_senha: true } } as any)
    render(
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/primeiro-acesso" element={<div>TELA-PRIMEIRO-ACESSO</div>} />
            <Route path="/" element={<div>TELA-DASHBOARD</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )
    await fillLogin(user)
    await waitFor(() => expect(screen.queryByText('TELA-PRIMEIRO-ACESSO')).not.toBeNull())
    expect(screen.queryByText('Escolha o contexto')).toBeNull()
  })

  it('4. redireciona para /primeiro-acesso', async () => {
    const user = userEvent.setup()
    mockPost.mockResolvedValueOnce({ data: { access_token: FLAG_TOKEN, token_type: 'bearer', exige_troca_senha: true } } as any)
    render(
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/primeiro-acesso" element={<PrimeiroAcesso />} />
            <Route path="/" element={<div>TELA-DASHBOARD</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )
    await fillLogin(user)
    expect(await screen.findByText('Defina sua nova senha')).toBeTruthy()
  })

  it('5. rota privada redireciona para /primeiro-acesso enquanto flag=true', async () => {
    seedPending()
    render(
      <MemoryRouter initialEntries={['/equipe']}>
        <AuthProvider>
          <Routes>
            <Route path="/equipe" element={<PrivateRoute><div>PAGINA-EQUIPE</div></PrivateRoute>} />
            <Route path="/primeiro-acesso" element={<div>TELA-PRIMEIRO-ACESSO</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )
    expect(await screen.findByText('TELA-PRIMEIRO-ACESSO')).toBeTruthy()
    expect(screen.queryByText('PAGINA-EQUIPE')).toBeNull()
  })

  it('6. valida confirmação de senha', async () => {
    const user = userEvent.setup()
    seedPending()
    render(
      <MemoryRouter>
        <AuthProvider><PrimeiroAcesso /></AuthProvider>
      </MemoryRouter>,
    )
    await user.type(screen.getByPlaceholderText('Nova senha'), 'Nova1234')
    await user.type(screen.getByPlaceholderText('Confirmar nova senha'), 'Outra9999')
    await user.click(screen.getByRole('button', { name: 'Salvar nova senha' }))
    expect(await screen.findByText(/não conferem/)).toBeTruthy()
    expect(mockPut).not.toHaveBeenCalled()
  })

  it('7. valida regras mínimas', async () => {
    const user = userEvent.setup()
    seedPending()
    render(
      <MemoryRouter>
        <AuthProvider><PrimeiroAcesso /></AuthProvider>
      </MemoryRouter>,
    )
    await user.type(screen.getByPlaceholderText('Nova senha'), 'curta')
    await user.type(screen.getByPlaceholderText('Confirmar nova senha'), 'curta')
    await user.click(screen.getByRole('button', { name: 'Salvar nova senha' }))
    expect(await screen.findByText(/no mínimo 8 caracteres/)).toBeTruthy()
    expect(mockPut).not.toHaveBeenCalled()
  })

  it('8. confirmação chama PUT /auth/password com o contrato real', async () => {
    const user = userEvent.setup()
    seedPending()
    mockPut.mockResolvedValueOnce({ data: { mensagem: 'Senha alterada com sucesso' } } as any)
    mockPost.mockResolvedValueOnce({ data: { access_token: ILPI_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    render(
      <MemoryRouter initialEntries={['/primeiro-acesso']}>
        <AuthProvider>
          <Routes>
            <Route path="/primeiro-acesso" element={<PrimeiroAcesso />} />
            <Route path="/" element={<div>TELA-DASHBOARD</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )
    await user.type(screen.getByPlaceholderText('Nova senha'), 'Nova1234')
    await user.type(screen.getByPlaceholderText('Confirmar nova senha'), 'Nova1234')
    await user.click(screen.getByRole('button', { name: 'Salvar nova senha' }))
    await waitFor(() => expect(mockPut).toHaveBeenCalledWith('/auth/password', { nova_senha: 'Nova1234', confirmar_senha: 'Nova1234' }))
  })

  it('9. sucesso limpa a flag', async () => {
    const user = userEvent.setup()
    seedPending()
    mockPut.mockResolvedValueOnce({ data: { mensagem: 'Senha alterada com sucesso' } } as any)
    mockPost.mockResolvedValueOnce({ data: { access_token: ILPI_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    let captured: ReturnType<typeof useAuth> | null = null
    function Probe() {
      captured = useAuth()
      return null
    }
    render(
      <MemoryRouter initialEntries={['/primeiro-acesso']}>
        <AuthProvider>
          <Probe />
          <Routes>
            <Route path="/primeiro-acesso" element={<PrimeiroAcesso />} />
            <Route path="/" element={<div>TELA-DASHBOARD</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )
    await user.type(screen.getByPlaceholderText('Nova senha'), 'Nova1234')
    await user.type(screen.getByPlaceholderText('Confirmar nova senha'), 'Nova1234')
    await user.click(screen.getByRole('button', { name: 'Salvar nova senha' }))
    await waitFor(() => expect(captured!.requiresPasswordChange).toBe(false))
  })

  it('10. pós-troca segue fluxo normal (dashboard, contexto único)', async () => {
    const user = userEvent.setup()
    seedPending()
    mockPut.mockResolvedValueOnce({ data: { mensagem: 'Senha alterada com sucesso' } } as any)
    mockPost.mockResolvedValueOnce({ data: { access_token: ILPI_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    render(
      <MemoryRouter initialEntries={['/primeiro-acesso']}>
        <AuthProvider>
          <Routes>
            <Route path="/primeiro-acesso" element={<PrimeiroAcesso />} />
            <Route path="/" element={<div>TELA-DASHBOARD</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )
    await user.type(screen.getByPlaceholderText('Nova senha'), 'Nova1234')
    await user.type(screen.getByPlaceholderText('Confirmar nova senha'), 'Nova1234')
    await user.click(screen.getByRole('button', { name: 'Salvar nova senha' }))
    expect(await screen.findByText('TELA-DASHBOARD')).toBeTruthy()
  })

  it('11. erro do backend permanece na tela', async () => {
    const user = userEvent.setup()
    seedPending()
    mockPut.mockRejectedValueOnce({ response: { status: 422, data: { detail: 'Senha já utilizada recentemente' } } })
    render(
      <MemoryRouter>
        <AuthProvider><PrimeiroAcesso /></AuthProvider>
      </MemoryRouter>,
    )
    await user.type(screen.getByPlaceholderText('Nova senha'), 'Nova1234')
    await user.type(screen.getByPlaceholderText('Confirmar nova senha'), 'Nova1234')
    await user.click(screen.getByRole('button', { name: 'Salvar nova senha' }))
    expect(await screen.findByText('Senha já utilizada recentemente')).toBeTruthy()
    expect(screen.getByText('Defina sua nova senha')).toBeTruthy()
  })

  it('12. reload com claim de troca mantém o gate', async () => {
    seedPending()
    const { get } = renderAuth()
    await waitFor(() => expect(get().requiresPasswordChange).toBe(true))
  })

  it('13. login com flag=false segue normal', async () => {
    const OK = jwt({ sub: 'u1', email: 'admin@ilpi.com', is_superuser: true, exp: Math.floor(Date.now() / 1000) + 3600 })
    mockPost.mockResolvedValueOnce({ data: { access_token: OK, token_type: 'bearer', exige_troca_senha: false } } as any)
    const { get } = renderAuth()
    const res = await get().login('admin@ilpi.com', 'senha')
    expect(res.requiresPasswordChange).toBe(false)
    await waitFor(() => expect(get().requiresPasswordChange).toBe(false))
  })

  it('14. context switch funciona após a troca', async () => {
    seedPending()
    mockPut.mockResolvedValueOnce({ data: { mensagem: 'Senha alterada com sucesso' } } as any)
    const SUPER = jwt({ sub: 'u1', email: 'admin@ilpi.com', is_superuser: true, exp: Math.floor(Date.now() / 1000) + 3600 })
    mockPost.mockResolvedValueOnce({ data: { access_token: SUPER, token_type: 'bearer', exige_troca_senha: false } } as any)
    const { get } = renderAuth()
    await get().completePasswordChange('Nova1234', 'Nova1234')
    await waitFor(() => expect(get().requiresPasswordChange).toBe(false))
    mockSelect.mockResolvedValueOnce({ data: { access_token: ILPI_TOKEN, token_type: 'bearer', exige_troca_senha: false } } as any)
    await get().switchContext({ key: 'ilpi:ilpi1', scope: 'ilpi', ilpi_id: 'ilpi1', label: 'ILPI', sublabel: '' })
    expect(mockSelect).toHaveBeenCalledWith({ scope: 'ilpi', ilpi_id: 'ilpi1' })
  })
})

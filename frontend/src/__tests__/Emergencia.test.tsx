import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { Layout } from '../components/Layout'
import { AvatarResidente, iniciais } from '../components/residente/AvatarResidente'
import { api } from '../services/api'
import { contextApi } from '../services/context'
import { TOKEN_KEY, USER_KEY, CONTEXT_KEY } from '../types/context'

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

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)
const CONTAGEM_VAZIA = { critico: 0, atencao: 0, aviso: 0, alerta: 0, pendencia: 0, informativo: 0, atividade: 0, total: 0 }
const RESIDENTES = [
  { id: 'r1', nome: 'Maria Souza', foto: null },
  { id: 'r2', nome: 'João Lima', foto: 'data:image/png;base64,AAAA' },
]

function jwt(payload: object): string {
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${b64({ alg: 'HS256' })}.${b64(payload)}.sig`
}

function renderEm(rota: string, permissoes: string[]) {
  localStorage.setItem(TOKEN_KEY, jwt({ sub: 'u1', exp: Math.floor(Date.now() / 1000) + 3600 }))
  localStorage.setItem(USER_KEY, JSON.stringify({ id: 'u1', nome: 'cuidadora', email: 'c@ilpi.com' }))
  localStorage.setItem(CONTEXT_KEY, JSON.stringify({ scope: 'ilpi', ilpi_id: 'ilpi1' }))
  vi.mocked(contextApi.permissoesDaSessao).mockResolvedValue({ data: { scope: 'ilpi', ilpi_id: 'ilpi1', permissoes } } as any)
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[rota]}>
        <Layout>
          <Routes>
            <Route path="/" element={<p>tela início</p>} />
            <Route path="/residentes/:id" element={<p>tela prontuário</p>} />
          </Routes>
        </Layout>
      </MemoryRouter>
    </AuthProvider>,
  )
}

// Os dois cabeçalhos (mobile/tablet e desktop) ficam no DOM; o CSS esconde um.
const abrirEmergencia = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click((await screen.findAllByRole('button', { name: 'Emergência' }))[0])
  return within(await screen.findByRole('dialog', { name: 'Emergência' }))
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
  mockGet.mockImplementation(async (url: string) =>
    url === '/central-alertas/'
      ? ({ data: { gerado_em: '2026-10-01T12:00:00Z', alertas: [], contagem: CONTAGEM_VAZIA } } as any)
      : url === '/residentes/' ? ({ data: RESIDENTES } as any) : ({ data: [] } as any))
})

describe('Emergência — entrada global', () => {
  it('sem residentes:ler o botão não aparece', async () => {
    renderEm('/', ['sinais_vitais:ler'])
    await screen.findByText('tela início')
    await waitFor(() => expect(contextApi.permissoesDaSessao).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: 'Emergência' })).toBeNull()
  })

  it('um toque só abre o diálogo: pede o residente, busca e oferece o prontuário', async () => {
    const user = userEvent.setup()
    renderEm('/', ['residentes:ler'])
    const dialogo = await abrirEmergencia(user)

    expect(dialogo.getByText('Para qual residente?')).toBeTruthy()
    expect(['INPUT', 'TEXTAREA']).not.toContain(document.activeElement?.tagName)
    await user.type(dialogo.getByRole('searchbox', { name: 'Buscar residente' }), 'joao')
    expect(dialogo.queryByText('Maria Souza')).toBeNull()
    await user.click(dialogo.getByRole('button', { name: /João Lima/ }))

    expect(dialogo.getByRole('link', { name: 'Abrir prontuário' }).getAttribute('href')).toBe('/residentes/r2')
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('no prontuário, já abre com o residente da tela', async () => {
    const user = userEvent.setup()
    renderEm('/residentes/r1', ['residentes:ler'])
    await screen.findByText('tela prontuário')
    const dialogo = await abrirEmergencia(user)

    expect(await dialogo.findByText('Maria Souza')).toBeTruthy()
    expect(dialogo.getByRole('link', { name: 'Abrir prontuário' }).getAttribute('href')).toBe('/residentes/r1')
    await user.click(dialogo.getByRole('button', { name: 'Trocar residente' }))
    expect(dialogo.getByText('Para qual residente?')).toBeTruthy()
  })
})

describe('Avatar do residente', () => {
  it('iniciais: primeiro e último nome; ignora conectivos', () => {
    expect(iniciais('Maria da Silva Souza')).toBe('MS')
    expect(iniciais('Pelé')).toBe('PE')
    expect(iniciais('  ')).toBe('?')
  })

  it('só usa foto embutida ou https; outro texto vira iniciais', () => {
    const { container, rerender } = render(<AvatarResidente nome="Ana Reis" foto="data:image/jpeg;base64,AAAA" />)
    expect(container.querySelector('img')).toBeTruthy()
    rerender(<AvatarResidente nome="Ana Reis" foto="http://exemplo/foto.jpg" />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.textContent).toBe('AR')
    rerender(<AvatarResidente nome="Ana Reis" foto="javascript:alert(1)" />)
    expect(container.querySelector('img')).toBeNull()
  })
})

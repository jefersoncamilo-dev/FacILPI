import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { Residentes } from '../pages/Residentes'
import { ResidenteProntuario } from '../pages/ResidenteProntuario'
import { api } from '../services/api'
import { contextApi } from '../services/context'

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
  logoutServidor: vi.fn(),
}))

const mockGet = vi.mocked(api.get)
const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

const RESIDENTE = {
  id: 'r1', nome: 'Antônia Ribeiro', situacao: 'Ativo', data_nascimento: '1940-05-10', data_admissao: '2026-09-25',
  sexo: 'F', alergias: 'Dipirona', grau_dependencia: 'Grau III',
}
const OUTRO = { id: 'r2', nome: 'Benedito Carvalho', situacao: 'Em admissao', data_nascimento: '1938-01-02', sexo: 'M' }
const LEITOS = [{ id: 'l1', quarto: '101', leito: 'A', unidade: null, residente_atual_id: 'r1', situacao: 'livre' }]
const GRAUS = [
  { classificacao: 'Grau II', situacao: 'ativo', validade: null },
  { classificacao: 'Grau I', situacao: 'substituido', validade: null },
]
const AUSENCIAS = [{ tipo: 'hospitalizacao', data_inicio: '2026-09-20T10:00:00Z', data_fim: null }]
const PRONTUARIO_VAZIO = { items: [], next_cursor: null, has_more: false }

function respondePorUrl() {
  mockGet.mockImplementation((url: string) => {
    const r = (data: unknown) => Promise.resolve({ data } as any)
    if (url === '/residentes/') return r([RESIDENTE, OUTRO])
    if (url === '/residentes/r1') return r(RESIDENTE)
    if (url === '/residentes/r1/prontuario') return r(PRONTUARIO_VAZIO)
    if (url === '/quartos_leitos/') return r(LEITOS)
    if (url === '/graus-dependencia/') return r(GRAUS)
    if (url === '/ausencias/') return r(AUSENCIAS)
    throw new Error(`URL inesperada: ${url}`)
  })
}

function renderEm(rota: string, permissoes: string[]) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes } } as any)
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[rota]}>
        <PermissoesProvider>
          <Routes>
            <Route path="/residentes" element={<Residentes />} />
            <Route path="/residentes/:id" element={<ResidenteProntuario />} />
          </Routes>
        </PermissoesProvider>
      </MemoryRouter>
    </AuthProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  respondePorUrl()
})

describe('UX-04 — prontuário', () => {
  it('ações só aparecem para quem pode registrar', async () => {
    renderEm('/residentes/r1', ['residentes:ler', 'sinais_vitais:ler'])
    await screen.findByRole('heading', { name: 'Antônia Ribeiro' })
    await waitFor(() => expect(mockPermissoes).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: '+ Registrar sinais vitais' })).toBeNull()
    expect(screen.queryByRole('button', { name: '+ Registrar intercorrência' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Documentos' })).toBeNull()
  })

  it('cabeçalho usa as fontes oficiais: leito, grau ativo e ausência — nunca o grau legado', async () => {
    renderEm('/residentes/r1', ['residentes:ler', 'quartos_leitos:ler', 'grau_dependencia:ler', 'ausencias:ler'])
    await screen.findByRole('heading', { name: 'Antônia Ribeiro' })
    expect(await screen.findByText('Quarto 101 · Leito A')).toBeTruthy()
    expect(await screen.findByText('Grau II')).toBeTruthy()
    expect(screen.queryByText('Grau III')).toBeNull()
    expect(await screen.findByText(/Hospitalizado\(a\) desde/)).toBeTruthy()
    expect(screen.getByText('Dipirona')).toBeTruthy()
  })

  it('sem permissão de leitos ou graus, esses itens não são consultados nem exibidos', async () => {
    renderEm('/residentes/r1', ['residentes:ler'])
    await screen.findByRole('heading', { name: 'Antônia Ribeiro' })
    await waitFor(() => expect(mockPermissoes).toHaveBeenCalled())
    const urls = mockGet.mock.calls.map(c => String(c[0]))
    expect(urls).not.toContain('/quartos_leitos/')
    expect(urls).not.toContain('/graus-dependencia/')
    expect(screen.queryByText('Leito', { selector: 'dt' })).toBeNull()
    expect(screen.queryByText('Grau de dependência', { selector: 'dt' })).toBeNull()
  })

  it('atalhos de visão só oferecem origens permitidas e aplicam o filtro de origem', async () => {
    const user = userEvent.setup()
    renderEm('/residentes/r1', ['residentes:ler', 'sinais_vitais:ler', 'intercorrencias:ler'])
    const grupo = within(await screen.findByRole('group', { name: 'Ver no prontuário' }))
    expect(grupo.getByRole('button', { name: 'Tudo' }).getAttribute('aria-pressed')).toBe('true')
    expect(grupo.queryByRole('button', { name: 'PAIS' })).toBeNull()
    await user.click(grupo.getByRole('button', { name: 'Sinais vitais' }))
    await waitFor(() => {
      const ultima = mockGet.mock.calls.filter(c => c[0] === '/residentes/r1/prontuario').at(-1)
      expect((ultima?.[1] as any)?.params?.origem).toBe('sinal_vital')
    })
    expect(grupo.getByRole('button', { name: 'Sinais vitais' }).getAttribute('aria-pressed')).toBe('true')
  })
})

describe('UX-04 — lista de residentes', () => {
  it('"Novo residente" só com residentes:criar; filtro por situação usa os valores reais', async () => {
    const user = userEvent.setup()
    renderEm('/residentes', ['residentes:ler', 'quartos_leitos:ler'])
    await screen.findByRole('link', { name: /^Antônia Ribeiro/ })
    await waitFor(() => expect(mockPermissoes).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: /Novo residente/ })).toBeNull()
    expect(await screen.findByText('Quarto 101 · Leito A')).toBeTruthy()

    await user.click(screen.getByRole('button', { name: /Em admissao/ }))
    expect(screen.queryByRole('link', { name: /^Antônia Ribeiro/ })).toBeNull()
    expect(screen.getByRole('link', { name: /^Benedito Carvalho/ })).toBeTruthy()
  })
})

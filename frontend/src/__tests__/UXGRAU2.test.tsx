import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { Residentes } from '../pages/Residentes'
import { BuscaGlobal } from '../components/shell/BuscaGlobal'
import { api } from '../services/api'
import { contextApi } from '../services/context'

// Dados sintéticos: nomes fictícios, nenhum dado real.
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

// Ordem do backend: alfabética. O grau legado (campo do cadastro) diverge do oficial de propósito.
const RESIDENTES = [
  { id: 'a', nome: 'Ana Um', situacao: 'Ativo', data_nascimento: '1940-01-01', grau_dependencia: 'Grau III' },
  { id: 'b', nome: 'Bruno Dois', situacao: 'Ativo', data_nascimento: '1941-01-01' },
  { id: 'c', nome: 'Carla Tres', situacao: 'Ativo', data_nascimento: '1942-01-01' },
  { id: 'd', nome: 'Davi Quatro', situacao: 'Ativo', data_nascimento: '1943-01-01' },
]
const GRAUS = [
  { residente_id: 'a', classificacao: 'Grau I', situacao: 'ativo' },
  { residente_id: 'b', classificacao: 'Grau III', situacao: 'ativo' },
  { residente_id: 'c', classificacao: 'Grau II', situacao: 'ativo' },
  { residente_id: 'd', classificacao: 'Grau III', situacao: 'substituido' },
]

function renderLista(permissoes: string[]) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', ilpi_id: 'ilpi1', permissoes } } as any)
  mockGet.mockImplementation(((url: string) =>
    Promise.resolve({ data: url === '/residentes/' ? RESIDENTES : url === '/graus-dependencia/' ? GRAUS : [] })) as any)
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={['/residentes']}>
        <PermissoesProvider>
          <Routes><Route path="/residentes" element={<Residentes />} /></Routes>
        </PermissoesProvider>
      </MemoryRouter>
    </AuthProvider>,
  )
}

const cardDe = (nome: RegExp) => screen.getByRole('link', { name: nome }).parentElement!

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('UX-GRAU G2 — lista de Residentes', () => {
  it('ordena por prioridade: sem grau, Grau III, Grau II, Grau I', async () => {
    renderLista(['residentes:ler', 'grau_dependencia:ler'])
    await waitFor(() => expect(within(cardDe(/^Bruno Dois/)).queryByText('Grau III')).toBeTruthy())
    // Davi só tem grau substituído → "Sem grau" no topo; depois Bruno (III), Carla (II), Ana (I).
    const nomes = screen.getAllByRole('link', { name: /^(Ana|Bruno|Carla|Davi) / }).map(l => l.getAttribute('href'))
    expect(nomes).toEqual(['/residentes/d', '/residentes/b', '/residentes/c', '/residentes/a'])
  })

  it('mostra o grau OFICIAL no cartão, nunca o campo legado', async () => {
    renderLista(['residentes:ler', 'grau_dependencia:ler'])
    await waitFor(() => expect(within(cardDe(/^Ana Um/)).queryByText('Grau I')).toBeTruthy())
    expect(within(cardDe(/^Ana Um/)).queryByText('Grau III')).toBeNull()
    expect(within(cardDe(/^Davi Quatro/)).getByText('Sem grau')).toBeTruthy()
  })

  it('círculo da foto na cor do grau', async () => {
    renderLista(['residentes:ler', 'grau_dependencia:ler'])
    await waitFor(() => expect(cardDe(/^Bruno Dois/).querySelector('[data-grau="Grau III"]')).toBeTruthy())
    expect(cardDe(/^Bruno Dois/).querySelector('[aria-hidden="true"]')!.className).toContain('ring-grau-3')
    expect(cardDe(/^Carla Tres/).querySelector('[data-grau="Grau II"]')!.className).toContain('outline-grau-2-contorno')
  })

  it('filtro por grau, com contagem e a cor do grau no botão ativo', async () => {
    const user = userEvent.setup()
    renderLista(['residentes:ler', 'grau_dependencia:ler'])
    const filtros = await screen.findByRole('group', { name: 'Filtrar por grau de dependência' })
    expect(within(filtros).getAllByRole('button').map(b => b.textContent)).toEqual([
      'Todos os graus (4)', 'Sem grau (1)', 'Grau III (1)', 'Grau II (1)', 'Grau I (1)',
    ])
    const tres = within(filtros).getByRole('button', { name: /^Grau III/ })
    await user.click(tres)
    expect(tres.getAttribute('aria-pressed')).toBe('true')
    expect(tres.className).toContain('bg-grau-3-fundo')
    expect(screen.getAllByRole('link', { name: /^(Ana|Bruno|Carla|Davi) / }).map(l => l.getAttribute('href'))).toEqual(['/residentes/b'])
  })

  it('sem grau_dependencia:ler: não consulta, não mostra grau (nem o legado), não reordena', async () => {
    renderLista(['residentes:ler'])
    await screen.findByRole('link', { name: /^Ana Um/ })
    await waitFor(() => expect(mockPermissoes).toHaveBeenCalled())
    expect(mockGet.mock.calls.some(c => c[0] === '/graus-dependencia/')).toBe(false)
    expect(screen.queryByRole('group', { name: 'Filtrar por grau de dependência' })).toBeNull()
    expect(screen.queryByText(/^Grau (I|II|III)$/)).toBeNull()
    expect(screen.queryByText('Sem grau')).toBeNull()
    expect(screen.getAllByRole('link', { name: /^(Ana|Bruno|Carla|Davi) / }).map(l => l.getAttribute('href'))).toEqual([
      '/residentes/a', '/residentes/b', '/residentes/c', '/residentes/d',
    ])
  })

  it('cadastro: a opção de grau escolhida fica na cor do grau', async () => {
    const user = userEvent.setup()
    mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes: ['residentes:ler', 'residentes:criar', 'grau_dependencia:criar'] } } as any)
    mockGet.mockImplementation((() => Promise.resolve({ data: [] })) as any)
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={['/residentes?novo=1']}>
          <PermissoesProvider><Routes><Route path="/residentes" element={<Residentes />} /></Routes></PermissoesProvider>
        </MemoryRouter>
      </AuthProvider>,
    )
    const grupo = await screen.findByRole('group', { name: 'Grau de dependência' })
    await user.click(within(grupo).getByRole('radio', { name: 'Grau II' }))
    expect(within(grupo).getByRole('radio', { name: 'Grau II' }).closest('label')!.className).toContain('bg-grau-2-fundo')
  })
})

describe('UX-GRAU G2 — busca Ctrl+K', () => {
  it('entre os residentes encontrados, prioridade por grau, com selo e círculo', async () => {
    const user = userEvent.setup()
    mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', ilpi_id: 'ilpi1', permissoes: ['residentes:ler', 'grau_dependencia:ler'] } } as any)
    mockGet.mockImplementation(((url: string) =>
      Promise.resolve({ data: url === '/residentes/' ? RESIDENTES : url === '/graus-dependencia/' ? GRAUS : [] })) as any)
    render(
      <PermissoesProvider>
        <MemoryRouter><BuscaGlobal open onOpenChange={vi.fn()} /></MemoryRouter>
      </PermissoesProvider>,
    )
    await waitFor(() => expect(mockGet.mock.calls.some(c => c[0] === '/graus-dependencia/')).toBe(true))
    await user.type(screen.getByRole('combobox', { name: 'Buscar residente ou tela' }), 'a')
    // "a" casa com Ana (I), Carla (II) e Davi (sem grau); Bruno não tem "a".
    const lista = within(screen.getByRole('listbox'))
    await waitFor(() => expect(lista.getAllByRole('option')[0].textContent).toContain('Davi Quatro'))
    const residentes = lista.getAllByRole('option').filter(o => /Ana|Carla|Davi/.test(o.textContent || ''))
    expect(residentes.map(o => o.textContent)).toEqual([
      expect.stringContaining('Davi Quatro'), expect.stringContaining('Carla Tres'), expect.stringContaining('Ana Um'),
    ])
    expect(residentes[1].textContent).toContain('Grau II')
    expect(residentes[0].textContent).toContain('Sem grau')
    expect(residentes[1].querySelector('[data-grau="Grau II"]')).toBeTruthy()
  })
})


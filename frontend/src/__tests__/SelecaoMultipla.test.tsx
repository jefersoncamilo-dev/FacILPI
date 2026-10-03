import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { MeuPlantao } from '../pages/MeuPlantao'
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

const em = (min: number) => new Date(Date.now() + min * 60_000).toISOString()
const cuidado = (id: string, residente: string, descricao: string, min: number) =>
  ({ origem: 'cuidado', registro_id: id, residente_id: residente, descricao, previsto_em: em(min), prioridade: null, local: null })
const BANHO_1 = cuidado('b1', 'r1', 'Banho assistido', 30)
const BANHO_2 = cuidado('b2', 'r2', 'Banho assistido', 40)
const HIDRATACAO = cuidado('h1', 'r1', 'Hidratação', 50)
const DOSE = { origem: 'medicacao', registro_id: 'd1', residente_id: 'r1', descricao: 'Dose prevista de medicacao', previsto_em: em(35), prioridade: null, local: null }

let fila: unknown[] = []
function responde(itens: unknown[]) {
  fila = itens
  mockGet.mockImplementation((url: string) => {
    if (url === '/plantao/') return Promise.resolve({ data: fila } as any)
    if (url === '/residentes/') return Promise.resolve({ data: [{ id: 'r1', nome: 'Maria Souza' }, { id: 'r2', nome: 'João Lima' }] } as any)
    if (url === '/meu-plantao/') return Promise.resolve({ data: { gerado_em: em(0), areas: [] } } as any)
    return Promise.resolve({ data: [] } as any)
  })
}

function renderCom(permissoes: string[]) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes } } as any)
  return render(<AuthProvider><MemoryRouter><PermissoesProvider><MeuPlantao /></PermissoesProvider></MemoryRouter></AuthProvider>)
}

const TUDO = ['plantao:ler', 'execucoes:criar', 'administracoes:criar', 'intercorrencias:atualizar']
const barra = () => within(screen.getByRole('region', { name: 'Seleção' }))

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
})

describe('UX-01B — seleção múltipla', () => {
  it('só cuidados viram marcáveis; medicação não, e Registrar some no modo seleção', async () => {
    const user = userEvent.setup()
    responde([BANHO_1, DOSE, BANHO_2])
    renderCom(TUDO)

    await user.click(await screen.findByRole('button', { name: 'Selecionar' }))
    expect(screen.getAllByRole('checkbox')).toHaveLength(2)
    expect(screen.queryByRole('button', { name: 'Registrar' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Registrar administração' })).toBeNull()
    expect(barra().getByText('Nenhum cuidado marcado')).toBeTruthy()
  })

  it('sem execucoes:criar não há seleção', async () => {
    responde([BANHO_1, BANHO_2])
    renderCom(['plantao:ler'])
    await screen.findAllByText('Banho assistido')
    await waitFor(() => expect(mockPermissoes).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: 'Selecionar' })).toBeNull()
  })

  it('marca um a um e conta; Limpar e Cancelar zeram', async () => {
    const user = userEvent.setup()
    responde([BANHO_1, BANHO_2, HIDRATACAO])
    renderCom(TUDO)

    await user.click(await screen.findByRole('button', { name: 'Selecionar' }))
    const [primeiro, segundo] = screen.getAllByRole('checkbox')
    await user.click(primeiro)
    await user.click(segundo)
    expect(primeiro.getAttribute('aria-checked')).toBe('true')
    expect(barra().getByText('2 marcados')).toBeTruthy()

    await user.click(barra().getByRole('button', { name: 'Limpar' }))
    expect(barra().getByText('Nenhum cuidado marcado')).toBeTruthy()

    await user.click(screen.getAllByRole('checkbox')[0])
    await user.click(screen.getByRole('button', { name: 'Cancelar seleção' }))
    expect(screen.queryByRole('region', { name: 'Seleção' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Selecionar' }))
    expect(screen.getAllByRole('checkbox').every(c => c.getAttribute('aria-checked') === 'false')).toBe(true)
  })

  it('Por cuidado: "Marcar até 1 h" marca só o grupo e alterna para "Desmarcar todos"', async () => {
    const user = userEvent.setup()
    responde([BANHO_1, BANHO_2, HIDRATACAO])
    renderCom(TUDO)

    await user.click(await screen.findByRole('button', { name: 'Por cuidado' }))
    await user.click(screen.getByRole('button', { name: 'Selecionar' }))
    const banho = within(screen.getByRole('region', { name: 'Banho assistido' }))
    await user.click(banho.getByRole('button', { name: 'Marcar até 1 h (2)' }))

    expect(barra().getByText('2 marcados')).toBeTruthy()
    expect(within(screen.getByRole('region', { name: 'Hidratação' })).getByRole('checkbox').getAttribute('aria-checked')).toBe('false')
    expect(banho.getByRole('button', { name: 'Desmarcar todos' })).toBeTruthy()
  })

  it('o nome acessível da caixa diz cuidado, residente e horário', async () => {
    const user = userEvent.setup()
    responde([BANHO_1])
    renderCom(TUDO)
    await user.click(await screen.findByRole('button', { name: 'Selecionar' }))
    expect(screen.getByRole('checkbox', { name: /^Banho assistido — Maria Souza, \d{2}\/\d{2} \d{2}:\d{2}$/ })).toBeTruthy()
  })
})

describe('Grau de dependência no card', () => {
  it('com grau_dependencia:ler mostra o selo do grau ativo (texto + cor)', async () => {
    responde([BANHO_1, BANHO_2])
    const padrao = mockGet.getMockImplementation()!
    mockGet.mockImplementation((url: string, ...resto: any[]) =>
      url === '/graus-dependencia/'
        ? Promise.resolve({ data: [
            { residente_id: 'r1', classificacao: 'Grau III', situacao: 'ativo' },
            { residente_id: 'r1', classificacao: 'Grau I', situacao: 'substituido' },
          ] } as any)
        : (padrao as any)(url, ...resto))
    renderCom([...TUDO, 'grau_dependencia:ler'])
    const selo = await screen.findByLabelText('Grau de dependência III')
    expect(selo.textContent).toBe('Grau III')
    expect(screen.queryByText('Grau I')).toBeNull()
  })

  it('sem grau_dependencia:ler nem consulta os graus', async () => {
    responde([BANHO_1])
    renderCom(TUDO)
    await screen.findAllByText('Banho assistido')
    await waitFor(() => expect(mockPermissoes).toHaveBeenCalled())
    expect(mockGet.mock.calls.some(c => c[0] === '/graus-dependencia/')).toBe(false)
    expect(screen.queryByLabelText(/Grau de dependência/)).toBeNull()
  })
})

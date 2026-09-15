import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Dashboard } from '../pages/Dashboard'
import { api } from '../services/api'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
})

const mockGet = vi.mocked(api.get)

const PENDENCIAS = [
  { origem: 'cuidado', registro_id: 'oc-1', residente_id: 'res-1', descricao: 'Banho assistido', previsto_em: '2026-09-15T12:00:00Z', prioridade: 'alta' },
  { origem: 'medicacao', registro_id: 'dose-1', residente_id: 'res-2', descricao: 'Dose prevista de medicacao', previsto_em: '2026-09-15T13:00:00Z', prioridade: null },
]

const RESIDENTES = [{ id: 'res-1', nome: 'Maria Silva', situacao: 'Ativo', grau_dependencia: 'II' }]

function respondeCom(opcoes: { erroPlantao?: unknown } = {}) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/plantao/') {
      return opcoes.erroPlantao ? Promise.reject(opcoes.erroPlantao) : Promise.resolve({ data: PENDENCIAS } as any)
    }
    if (url === '/residentes/') return Promise.resolve({ data: RESIDENTES } as any)
    throw new Error(`URL inesperada no Dashboard: ${url}`)
  })
}

function urlsChamadas() {
  return mockGet.mock.calls.map(c => String(c[0]))
}

function renderDashboard() {
  return render(<MemoryRouter><Dashboard /></MemoryRouter>)
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('Dashboard — não consome endpoints fail-closed', () => {
  it('1. não chama /tarefas/ nem /alertas/', async () => {
    respondeCom()
    renderDashboard()

    await waitFor(() => expect(urlsChamadas()).toContain('/plantao/'))
    expect(urlsChamadas().some(u => u.includes('tarefas'))).toBe(false)
    expect(urlsChamadas().some(u => u.includes('alertas'))).toBe(false)
  })

  it('2. pendências vêm da projeção oficial /plantao/', async () => {
    respondeCom()
    renderDashboard()

    expect(await screen.findByText('Pendências do turno')).toBeTruthy()
    await waitFor(() => expect(screen.getByText('2')).toBeTruthy())
    expect(await screen.findByText('Banho assistido')).toBeTruthy()
  })
})

describe('Dashboard — indisponibilidade nunca vira zero', () => {
  it('3. falha da projeção mostra traço, não 0', async () => {
    respondeCom({
      erroPlantao: { response: { status: 403, data: { detail: { code: 'PERMISSION_DENIED', message: 'Permissão não autorizada' } } } },
    })
    renderDashboard()

    expect(await screen.findByText('Indisponível no momento')).toBeTruthy()
    const cartao = screen.getByText('Pendências do turno').parentElement!
    expect(cartao.textContent).toContain('—')
    expect(cartao.textContent).not.toContain('0')
  })

  it('4. painel de pendências diz que a falha não significa ausência', async () => {
    respondeCom({ erroPlantao: new Error('Network Error') })
    renderDashboard()

    expect(await screen.findByText('Não foi possível carregar as pendências')).toBeTruthy()
    expect(screen.getByText('Isso não significa que não há pendências.')).toBeTruthy()
    expect(screen.queryByText('Nenhuma pendência no período')).toBeNull()
  })

  it('5. alertas aparecem como indisponíveis enquanto não há fonte oficial', async () => {
    respondeCom()
    renderDashboard()

    expect(await screen.findByText('Indisponível — sem fonte oficial')).toBeTruthy()
    const cartao = screen.getByText('Alertas ativos').parentElement!
    expect(cartao.textContent).toContain('—')
    expect(cartao.textContent).not.toContain('0')
  })

  it('6. projeção vazia legítima mostra zero e estado vazio próprio', async () => {
    mockGet.mockImplementation((url: string) =>
      url === '/plantao/'
        ? Promise.resolve({ data: [] } as any)
        : Promise.resolve({ data: RESIDENTES } as any),
    )
    renderDashboard()

    expect(await screen.findByText('Nenhuma pendência no período')).toBeTruthy()
    expect(screen.queryByText('Não foi possível carregar as pendências')).toBeNull()
  })
})

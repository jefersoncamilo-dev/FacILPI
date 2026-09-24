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

describe('Dashboard — residentes indisponíveis não viram zero (PH-01)', () => {
  it('7. falha na consulta de residentes mostra traço, não 0', async () => {
    mockGet.mockImplementation((url: string) =>
      url === '/residentes/'
        ? Promise.reject({ response: { status: 403, data: { detail: { message: 'Permissão não autorizada' } } } })
        : Promise.resolve({ data: PENDENCIAS } as any),
    )
    renderDashboard()

    const cartao = (await screen.findByText('Residentes cadastrados')).parentElement!
    await waitFor(() => expect(cartao.textContent).toContain('—'))
    expect(cartao.textContent).toContain('Indisponível no momento')
    // PH02-03: não existe mais "Ocupação" — nem com zero, nem com número algum.
    expect(cartao.textContent).not.toContain('Ocupação')
    expect(await screen.findByText('Não foi possível carregar os residentes')).toBeTruthy()
    expect(screen.queryByText('Nenhum residente cadastrado')).toBeNull()
  })

  it('8. lista vazia legítima continua mostrando zero', async () => {
    mockGet.mockImplementation((url: string) =>
      Promise.resolve({ data: url === '/residentes/' ? [] : PENDENCIAS } as any),
    )
    renderDashboard()

    expect(await screen.findByText('Nenhum residente cadastrado')).toBeTruthy()
    const cartao = screen.getByText('Residentes cadastrados').parentElement!
    // PH02-03: antes o zero era provado por "Ocupação 0%", um número calculado
    // contra a constante 40. Agora o próprio contador precisa mostrar 0.
    expect(cartao.textContent).toMatch(/^Residentes cadastrados\s*0$/)
    expect(screen.queryByText('Não foi possível carregar os residentes')).toBeNull()
  })
})

describe('Dashboard — só afirma o que tem fonte (PH-02 / #71)', () => {
  function residentes(n: number, situacao = 'Em admissao') {
    return Array.from({ length: n }, (_, i) => ({ id: `r-${i}`, nome: `Residente ${i}`, situacao, grau_dependencia: null }))
  }

  function responde(lista: unknown[] | Error) {
    mockGet.mockImplementation((url: string) => {
      if (url === '/plantao/') return Promise.resolve({ data: [] } as any)
      if (url === '/residentes/') {
        return lista instanceof Error ? Promise.reject(lista) : Promise.resolve({ data: lista } as any)
      }
      throw new Error(`URL inesperada no Dashboard: ${url}`)
    })
  }

  function semConformidadePositiva() {
    const cartao = screen.getByText('Conformidade').parentElement!
    expect(cartao.textContent).toContain('—')
    expect(cartao.textContent).toContain('Não avaliada — sem fonte oficial')
    expect(document.body.textContent).not.toMatch(/Em dia|Licenças verificadas|✅/)
  }

  it('9. conformidade nunca é afirmada — com residentes, vazio ou sem rede', async () => {
    responde(residentes(3))
    const { unmount } = renderDashboard()
    await screen.findByText('Residente 0')
    semConformidadePositiva()
    unmount()

    responde([])
    const segunda = renderDashboard()
    await screen.findByText('Nenhum residente cadastrado')
    semConformidadePositiva()
    segunda.unmount()

    responde(new Error('Network Error'))
    renderDashboard()
    await screen.findByText('Não foi possível carregar os residentes')
    semConformidadePositiva()
  })

  it('10. nenhuma ocupação é calculada — nem percentual em lugar algum', async () => {
    // Com a constante antiga, 20 residentes virariam "Ocupação 50%".
    responde(residentes(20))
    renderDashboard()
    await screen.findByText('Residente 0')
    expect(screen.queryByText(/Ocupação/)).toBeNull()
    expect(document.body.textContent).not.toMatch(/\d+\s*%/)
  })

  it('11. o total é chamado de "cadastrados", nunca de "ativos"', async () => {
    responde(residentes(2))
    renderDashboard()
    const cartao = (await screen.findByText('Residentes cadastrados')).parentElement!
    await waitFor(() => expect(cartao.textContent).toMatch(/^Residentes cadastrados\s*2$/))
    expect(screen.queryByText('Residentes ativos')).toBeNull()
  })

  it('12. nenhum selo "Ativo" é inventado — a situação exibida é a real', async () => {
    responde(residentes(1, 'Em admissao'))
    renderDashboard()
    expect(await screen.findByText(/^Em admissao •/)).toBeTruthy()
    expect(screen.queryByText('Ativo')).toBeNull()
  })

  it('13. no teto da listagem o total não é afirmado: 100 vira "100+"', async () => {
    // GET /residentes/ devolve no máximo 100 por padrão; com 100 na resposta a tela
    // não sabe se existem 100 ou 140.
    responde(residentes(100))
    renderDashboard()
    const cartao = (await screen.findByText('Residentes cadastrados')).parentElement!
    await waitFor(() => expect(cartao.textContent).toMatch(/^Residentes cadastrados\s*100\+$/))
  })

  it('14. abaixo do teto o número é exato', async () => {
    responde(residentes(99))
    renderDashboard()
    const cartao = (await screen.findByText('Residentes cadastrados')).parentElement!
    await waitFor(() => expect(cartao.textContent).toMatch(/^Residentes cadastrados\s*99$/))
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { MeuPlantao } from '../pages/MeuPlantao'
import { api } from '../services/api'

// Preserva os helpers reais (mensagemDeErro, formatDateTime); só o cliente HTTP é mockado.
vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
})

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)

const CUIDADO = {
  origem: 'cuidado',
  registro_id: 'oc-1',
  residente_id: 'res-1',
  descricao: 'Banho assistido',
  previsto_em: '2026-09-15T12:00:00Z',
  prioridade: 'alta',
}
const DOSE = {
  origem: 'medicacao',
  registro_id: 'dose-1',
  residente_id: 'res-2',
  descricao: 'Dose prevista de medicacao',
  previsto_em: '2026-09-15T13:00:00Z',
  prioridade: null,
}
const INTERCORRENCIA = {
  origem: 'intercorrencia',
  registro_id: 'int-1',
  residente_id: 'res-1',
  descricao: 'Intercorrencia aberta: queda',
  previsto_em: null,
  prioridade: null,
}
const TRES_ITENS = [CUIDADO, DOSE, INTERCORRENCIA]

const RESIDENTES = [
  { id: 'res-1', nome: 'Maria Silva' },
  { id: 'res-2', nome: 'João Souza' },
]

// A tela faz duas chamadas GET independentes: a projeção e a lista auxiliar de
// residentes. O roteamento por URL evita depender da ordem entre elas.
function respondeCom(itens: unknown[], opcoes: { residentes?: unknown[]; erroPlantao?: unknown } = {}) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/plantao/') {
      return opcoes.erroPlantao ? Promise.reject(opcoes.erroPlantao) : Promise.resolve({ data: itens } as any)
    }
    if (url === '/residentes/') {
      return Promise.resolve({ data: opcoes.residentes ?? RESIDENTES } as any)
    }
    throw new Error(`URL inesperada em MeuPlantao: ${url}`)
  })
}

function urlsChamadas() {
  return mockGet.mock.calls.map(c => c[0])
}

function renderPlantao() {
  return render(<MemoryRouter><MeuPlantao /></MemoryRouter>)
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('MeuPlantao — leitura da projeção oficial', () => {
  it('1. carrega de /plantao/ e nunca chama /tarefas/', async () => {
    respondeCom(TRES_ITENS)
    renderPlantao()

    expect(await screen.findByText('Banho assistido')).toBeTruthy()
    expect(urlsChamadas()).toContain('/plantao/')
    expect(urlsChamadas()).not.toContain('/tarefas/')
    expect(urlsChamadas().some(u => String(u).includes('tarefas'))).toBe(false)
  })

  it('2. renderiza as três origens suportadas', async () => {
    respondeCom(TRES_ITENS)
    renderPlantao()

    expect(await screen.findByText('Banho assistido')).toBeTruthy()
    expect(screen.getByText('Dose prevista de medicação')).toBeTruthy()
    expect(screen.getByText('Intercorrência aberta: queda')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Registrar execução' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Registrar administração' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Encerrar' })).toBeTruthy()
  })

  it('3. resolve o nome do residente e cai no id quando a lista falha', async () => {
    // res-1 aparece em dois itens (cuidado e intercorrência), por isso findAll.
    respondeCom(TRES_ITENS)
    renderPlantao()
    expect((await screen.findAllByText(/Maria Silva/)).length).toBeGreaterThan(0)

    vi.clearAllMocks()
    mockGet.mockImplementation((url: string) =>
      url === '/plantao/' ? Promise.resolve({ data: [CUIDADO] } as any) : Promise.reject(new Error('sem permissão')),
    )
    renderPlantao()
    expect((await screen.findAllByText(/res-1/)).length).toBeGreaterThan(0)
  })
})

describe('MeuPlantao — erro nunca vira "nenhuma pendência"', () => {
  it('4. 403 exibe mensagem de erro e não o estado vazio', async () => {
    respondeCom([], {
      erroPlantao: { response: { status: 403, data: { detail: { code: 'PERMISSION_DENIED', message: 'Permissão não autorizada' } } } },
    })
    renderPlantao()

    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText('Permissão não autorizada')).toBeTruthy()
    expect(screen.queryByText('Nenhuma pendência neste filtro')).toBeNull()
  })

  it('5. lista vazia legítima mostra estado vazio, sem alerta de erro', async () => {
    respondeCom([])
    renderPlantao()

    expect(await screen.findByText('Nenhuma pendência neste filtro')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('MeuPlantao — ações usam o endpoint oficial de cada origem', () => {
  it('6. cuidado registra execução em /execucoes-cuidado/', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderPlantao()

    await user.click(await screen.findByRole('button', { name: 'Registrar execução' }))
    await user.click(screen.getByRole('button', { name: 'Confirmar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    const [url, payload] = mockPost.mock.calls[0]
    expect(url).toBe('/execucoes-cuidado/')
    expect(payload).toMatchObject({ ocorrencia_id: 'oc-1', resultado: 'executada' })
    expect(payload).toHaveProperty('ocorrido_em')
  })

  it('7. medicação registra administração em /administracoes/ com quantidade', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderPlantao()

    await user.click(await screen.findByRole('button', { name: 'Registrar administração' }))
    await user.type(screen.getByPlaceholderText('Quantidade realizada (obrigatória)'), '2')
    await user.click(screen.getByRole('button', { name: 'Confirmar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    const [url, payload] = mockPost.mock.calls[0]
    expect(url).toBe('/administracoes/')
    expect(payload).toMatchObject({ dose_prevista_id: 'dose-1', resultado: 'administrada', quantidade_realizada: 2 })
  })

  it('8. intercorrência encerra em /intercorrencias/{id}/encerrar', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderPlantao()

    await user.click(await screen.findByRole('button', { name: 'Encerrar' }))
    await user.type(screen.getByPlaceholderText('Desfecho (obrigatório)'), 'Avaliada sem lesão')
    await user.click(screen.getByRole('button', { name: 'Confirmar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect(mockPost.mock.calls[0][0]).toBe('/intercorrencias/int-1/encerrar')
    expect(mockPost.mock.calls[0][1]).toEqual({ desfecho: 'Avaliada sem lesão' })
  })

  it('9. sucesso recarrega a projeção', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderPlantao()

    await user.click(await screen.findByRole('button', { name: 'Encerrar' }))
    await user.type(screen.getByPlaceholderText('Desfecho (obrigatório)'), 'Resolvida')
    await user.click(screen.getByRole('button', { name: 'Confirmar' }))

    await waitFor(() => expect(urlsChamadas().filter(u => u === '/plantao/').length).toBeGreaterThanOrEqual(2))
  })
})

describe('MeuPlantao — validações condicionais espelham o backend', () => {
  it('10. cuidado recusado exige justificativa antes de chamar a API', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    renderPlantao()

    await user.click(await screen.findByRole('button', { name: 'Registrar execução' }))
    await user.selectOptions(screen.getByLabelText('Resultado'), 'recusada')
    await user.click(screen.getByRole('button', { name: 'Confirmar' }))

    expect(await screen.findByText('Justificativa obrigatória para recusa ou omissão.')).toBeTruthy()
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('11. dose administrada exige quantidade maior que zero', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    renderPlantao()

    await user.click(await screen.findByRole('button', { name: 'Registrar administração' }))
    await user.click(screen.getByRole('button', { name: 'Confirmar' }))

    expect(await screen.findByText('Informe a quantidade realizada (maior que zero).')).toBeTruthy()
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('12. desfecho vazio bloqueia o encerramento', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    renderPlantao()

    await user.click(await screen.findByRole('button', { name: 'Encerrar' }))
    await user.click(screen.getByRole('button', { name: 'Confirmar' }))

    expect(await screen.findByText('Informe o desfecho da intercorrência.')).toBeTruthy()
    expect(mockPost).not.toHaveBeenCalled()
  })
})

describe('MeuPlantao — conflito de concorrência', () => {
  it('13. erro do backend é exibido e a projeção é recarregada', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    mockPost.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'Ocorrencia ja possui execucao vigente' } },
    })
    renderPlantao()

    await user.click(await screen.findByRole('button', { name: 'Registrar execução' }))
    await user.click(screen.getByRole('button', { name: 'Confirmar' }))

    expect(await screen.findByText('Ocorrencia ja possui execucao vigente')).toBeTruthy()
    await waitFor(() => expect(urlsChamadas().filter(u => u === '/plantao/').length).toBeGreaterThanOrEqual(2))
  })
})

describe('MeuPlantao — criação de tarefa avulsa foi removida', () => {
  it('14. não há botão de nova tarefa nem POST /tarefas/', async () => {
    respondeCom(TRES_ITENS)
    renderPlantao()

    await screen.findByText('Banho assistido')
    expect(screen.queryByRole('button', { name: /nova tarefa/i })).toBeNull()
    expect(mockPost).not.toHaveBeenCalled()
  })
})

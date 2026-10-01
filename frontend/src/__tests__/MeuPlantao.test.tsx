import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { MeuPlantao } from '../pages/MeuPlantao'
import { api } from '../services/api'
import { horaAtual } from '../lib/horarioReal'

// Preserva os helpers reais (mensagemDeErro, formatDateTime); só o cliente HTTP é mockado.
vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
})

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)

const HORA = 60 * 60 * 1000
const CUIDADO = {
  origem: 'cuidado',
  registro_id: 'oc-1',
  residente_id: 'res-1',
  descricao: 'Banho assistido',
  previsto_em: new Date(Date.now() - HORA).toISOString(),
  prioridade: 'alta',
}
const CUIDADO_2 = {
  origem: 'cuidado',
  registro_id: 'oc-2',
  residente_id: 'res-2',
  descricao: 'Troca de fralda',
  previsto_em: new Date(Date.now() + HORA).toISOString(),
  prioridade: null,
}
const DOSE = {
  origem: 'medicacao',
  registro_id: 'dose-1',
  residente_id: 'res-2',
  descricao: 'Dose prevista de medicacao',
  previsto_em: new Date(Date.now() + 2 * HORA).toISOString(),
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

// A tela faz chamadas GET independentes: a projeção, a lista auxiliar de
// residentes e o resumo da área. O roteamento por URL evita depender da ordem.
function respondeCom(itens: unknown[], opcoes: { residentes?: unknown[]; erroPlantao?: unknown } = {}) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/plantao/') {
      return opcoes.erroPlantao ? Promise.reject(opcoes.erroPlantao) : Promise.resolve({ data: itens } as any)
    }
    if (url === '/residentes/') {
      return Promise.resolve({ data: opcoes.residentes ?? RESIDENTES } as any)
    }
    if (url === '/meu-plantao/') return Promise.reject(new Error('sem plantão'))
    throw new Error(`URL inesperada em MeuPlantao: ${url}`)
  })
}

function urlsChamadas() {
  return mockGet.mock.calls.map(c => c[0])
}

function renderPlantao() {
  return render(<MemoryRouter><MeuPlantao /></MemoryRouter>)
}

async function abrirCuidado(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /^Registrar execução: Banho assistido/ }))
  return screen.getByRole('dialog')
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
})

describe('MeuPlantao — leitura da projeção oficial', () => {
  it('1. carrega de /plantao/ e nunca chama /tarefas/', async () => {
    respondeCom(TRES_ITENS)
    renderPlantao()

    expect(await screen.findByText('Banho assistido')).toBeTruthy()
    expect(urlsChamadas()).toContain('/plantao/')
    expect(urlsChamadas().some(u => String(u).includes('tarefas'))).toBe(false)
  })

  it('2. renderiza as três origens, cada uma com a sua ação', async () => {
    respondeCom(TRES_ITENS)
    renderPlantao()

    expect(await screen.findByText('Banho assistido')).toBeTruthy()
    expect(screen.getByText('Dose prevista de medicação')).toBeTruthy()
    expect(screen.getByText('Intercorrência aberta: queda')).toBeTruthy()
    expect(screen.getByRole('button', { name: /^Registrar execução:/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /^Registrar administração:/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /^Encerrar:/ })).toBeTruthy()
  })

  it('3. resolve o nome do residente e cai no id quando a lista falha', async () => {
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

describe('MeuPlantao — registro individual (#136)', () => {
  it('6. nenhum resultado vem marcado e salvar fica bloqueado até escolher', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    renderPlantao()

    const painel = await abrirCuidado(user)
    expect(within(painel).getByText('Maria Silva')).toBeTruthy()
    for (const nome of ['Realizado', 'Recusado', 'Não realizado']) {
      expect((within(painel).getByRole('radio', { name: nome }) as HTMLInputElement).checked).toBe(false)
    }
    expect((within(painel).getByRole('button', { name: 'Salvar' }) as HTMLButtonElement).disabled).toBe(true)
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('7. realizado registra em /execucoes-cuidado/ com o horário real informado', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderPlantao()

    const painel = await abrirCuidado(user)
    await user.click(within(painel).getByRole('radio', { name: 'Realizado' }))
    const hora = horaAtual(new Date(Date.now() - 20 * 60 * 1000))
    const campo = within(painel).getByLabelText('Horário real do cuidado')
    await user.clear(campo)
    await user.type(campo, hora)
    await user.click(within(painel).getByRole('button', { name: 'Salvar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    const [url, payload] = mockPost.mock.calls[0] as [string, any]
    expect(url).toBe('/execucoes-cuidado/')
    expect(payload).toMatchObject({ ocorrencia_id: 'oc-1', resultado: 'executada' })
    expect(horaAtual(new Date(payload.ocorrido_em))).toBe(hora)
    expect(payload).not.toHaveProperty('justificativa')
  })

  it('8. recusa exige motivo e grava como recusada + justificativa', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderPlantao()

    const painel = await abrirCuidado(user)
    await user.click(within(painel).getByRole('radio', { name: 'Recusado' }))
    await user.click(within(painel).getByRole('button', { name: 'Salvar' }))
    expect(await within(painel).findByText('Descreva o motivo da recusa.')).toBeTruthy()
    expect(mockPost).not.toHaveBeenCalled()

    await user.type(within(painel).getByLabelText('Motivo da recusa (obrigatório)'), 'Pediu para depois do almoço')
    await user.click(within(painel).getByRole('button', { name: 'Salvar' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect(mockPost.mock.calls[0][1]).toMatchObject({ resultado: 'recusada', justificativa: 'Pediu para depois do almoço' })
  })

  it('9. não realizado exige motivo e grava como omitida + justificativa', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderPlantao()

    const painel = await abrirCuidado(user)
    await user.click(within(painel).getByRole('radio', { name: 'Não realizado' }))
    await user.click(within(painel).getByRole('button', { name: 'Salvar' }))
    expect(await within(painel).findByText('Escolha o motivo.')).toBeTruthy()

    await user.selectOptions(within(painel).getByLabelText(/Por que não foi realizado/), 'Residente dormindo')
    await user.click(within(painel).getByRole('button', { name: 'Salvar' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect(mockPost.mock.calls[0][1]).toMatchObject({ resultado: 'omitida', justificativa: 'Residente dormindo' })
  })

  it('10. horário no futuro é recusado antes de chamar a API', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    renderPlantao()

    const painel = await abrirCuidado(user)
    await user.click(within(painel).getByRole('radio', { name: 'Realizado' }))
    const campo = within(painel).getByLabelText('Horário real do cuidado')
    await user.clear(campo)
    await user.type(campo, horaAtual(new Date(Date.now() + 2 * HORA)))
    await user.click(within(painel).getByRole('button', { name: 'Salvar' }))

    expect(await within(painel).findByText(/não pode estar no futuro|mais de 12 horas/)).toBeTruthy()
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('11. sucesso mantém o item na mesma posição com o resultado, sem ação nova', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderPlantao()

    const painel = await abrirCuidado(user)
    respondeCom([DOSE, INTERCORRENCIA]) // a projeção deixa de trazer o cuidado registrado
    await user.click(within(painel).getByRole('radio', { name: 'Realizado' }))
    await user.click(within(painel).getByRole('button', { name: 'Salvar' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(await screen.findByText(/Execução registrada: Banho assistido/)).toBeTruthy()
    const atrasadas = screen.getByRole('region', { name: 'Atrasadas' })
    expect(within(atrasadas).getByText('Banho assistido')).toBeTruthy()
    expect(within(atrasadas).getByText(/^Realizado às/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /^Registrar execução: Banho assistido/ })).toBeNull()
    // Recarga silenciosa: a lista não foi trocada por "Carregando".
    await waitFor(() => expect(urlsChamadas().filter(u => u === '/plantao/').length).toBeGreaterThanOrEqual(2))
    expect(screen.queryByText('Carregando plantão…')).toBeNull()
  })

  it('12. falha de rede preserva o preenchimento e permite tentar de novo', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    mockPost.mockRejectedValueOnce(new Error('Network Error'))
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderPlantao()

    const painel = await abrirCuidado(user)
    await user.click(within(painel).getByRole('radio', { name: 'Recusado' }))
    await user.type(within(painel).getByLabelText('Motivo da recusa (obrigatório)'), 'Sem fome')
    await user.click(within(painel).getByRole('button', { name: 'Salvar' }))

    expect(await within(painel).findByText(/Sem conexão com o servidor. Nada foi confirmado/)).toBeTruthy()
    expect((within(painel).getByRole('radio', { name: 'Recusado' }) as HTMLInputElement).checked).toBe(true)
    expect((within(painel).getByLabelText('Motivo da recusa (obrigatório)') as HTMLTextAreaElement).value).toBe('Sem fome')

    await user.click(within(painel).getByRole('button', { name: 'Tentar de novo' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(2))
    expect(mockPost.mock.calls[1][1]).toMatchObject({ resultado: 'recusada', justificativa: 'Sem fome' })
  })

  it('13. 409 com o item fora da projeção: "não está mais pendente", sem duplicar', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    mockPost.mockRejectedValueOnce({ response: { status: 409, data: { detail: { code: 'ROTINA_CONFLITO', message: 'Ocorrencia ja possui execucao vigente' } } } })
    renderPlantao()

    const painel = await abrirCuidado(user)
    respondeCom([DOSE, INTERCORRENCIA])
    await user.click(within(painel).getByRole('radio', { name: 'Realizado' }))
    await user.click(within(painel).getByRole('button', { name: 'Salvar' }))

    expect(await screen.findByText(/não está mais pendente. Nenhum registro duplicado/)).toBeTruthy()
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(mockPost).toHaveBeenCalledTimes(1)
  })

  it('14. 409 com o item ainda pendente mostra a mensagem do servidor e mantém o painel', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    mockPost.mockRejectedValueOnce({ response: { status: 409, data: { detail: { code: 'ROTINA_CONFLITO', message: 'Intervencao inativa nao admite execucao' } } } })
    renderPlantao()

    const painel = await abrirCuidado(user)
    await user.click(within(painel).getByRole('radio', { name: 'Realizado' }))
    await user.click(within(painel).getByRole('button', { name: 'Salvar' }))

    expect(await within(painel).findByText('Intervencao inativa nao admite execucao')).toBeTruthy()
    expect(screen.getByRole('dialog')).toBeTruthy()
  })

  it('15. "Salvar e próximo" abre o próximo cuidado pendente, sem passar por medicação', async () => {
    const user = userEvent.setup()
    respondeCom([CUIDADO, DOSE, CUIDADO_2, INTERCORRENCIA])
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderPlantao()

    const painel = await abrirCuidado(user)
    await user.click(within(painel).getByRole('radio', { name: 'Realizado' }))
    await user.click(within(painel).getByRole('button', { name: 'Salvar e próximo' }))

    await waitFor(() => expect(within(screen.getByRole('dialog')).getByRole('heading', { name: 'Troca de fralda' })).toBeTruthy())
    expect(within(screen.getByRole('dialog')).getByText('João Souza')).toBeTruthy()
    expect((within(screen.getByRole('dialog')).getByRole('radio', { name: 'Realizado' }) as HTMLInputElement).checked).toBe(false)
  })

  it('16. fechar sem salvar guarda o rascunho do item', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    renderPlantao()

    let painel = await abrirCuidado(user)
    await user.click(within(painel).getByRole('radio', { name: 'Recusado' }))
    await user.type(within(painel).getByLabelText('Motivo da recusa (obrigatório)'), 'Rascunho')
    await user.click(within(painel).getByRole('button', { name: 'Fechar' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())

    painel = await abrirCuidado(user)
    expect((within(painel).getByRole('radio', { name: 'Recusado' }) as HTMLInputElement).checked).toBe(true)
    expect((within(painel).getByLabelText('Motivo da recusa (obrigatório)') as HTMLTextAreaElement).value).toBe('Rascunho')
  })
})

describe('MeuPlantao — doses e intercorrências mantêm o fluxo próprio', () => {
  it('17. medicação registra administração em /administracoes/ com quantidade', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderPlantao()

    await user.click(await screen.findByRole('button', { name: /^Registrar administração:/ }))
    const painel = screen.getByRole('dialog')
    await user.click(within(painel).getByRole('radio', { name: 'Administrada' }))
    await user.click(within(painel).getByRole('button', { name: 'Registrar administração' }))
    expect(await within(painel).findByText('Informe a quantidade realizada (maior que zero).')).toBeTruthy()
    expect(mockPost).not.toHaveBeenCalled()

    await user.type(within(painel).getByLabelText('Quantidade realizada (obrigatória)'), '2')
    await user.click(within(painel).getByRole('button', { name: 'Registrar administração' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    const [url, payload] = mockPost.mock.calls[0]
    expect(url).toBe('/administracoes/')
    expect(payload).toMatchObject({ dose_prevista_id: 'dose-1', resultado: 'administrada', quantidade_realizada: 2 })
  })

  it('18. intercorrência exige desfecho e encerra em /intercorrencias/{id}/encerrar', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderPlantao()

    await user.click(await screen.findByRole('button', { name: /^Encerrar:/ }))
    const painel = screen.getByRole('dialog')
    await user.click(within(painel).getByRole('button', { name: 'Encerrar intercorrência' }))
    expect(await within(painel).findByText('Informe o desfecho da intercorrência.')).toBeTruthy()
    expect(mockPost).not.toHaveBeenCalled()

    await user.type(within(painel).getByLabelText('Desfecho (obrigatório)'), 'Avaliada sem lesão')
    await user.click(within(painel).getByRole('button', { name: 'Encerrar intercorrência' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect(mockPost.mock.calls[0][0]).toBe('/intercorrencias/int-1/encerrar')
    expect(mockPost.mock.calls[0][1]).toEqual({ desfecho: 'Avaliada sem lesão' })
  })

  it('19. erro do backend é exibido e a projeção é relida', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    mockPost.mockRejectedValueOnce({ response: { status: 400, data: { detail: 'Intervalo invalido' } } })
    renderPlantao()

    const painel = await abrirCuidado(user)
    await user.click(within(painel).getByRole('radio', { name: 'Realizado' }))
    await user.click(within(painel).getByRole('button', { name: 'Salvar' }))

    expect(await within(painel).findByText('Intervalo invalido')).toBeTruthy()
    await waitFor(() => expect(urlsChamadas().filter(u => u === '/plantao/').length).toBeGreaterThanOrEqual(2))
  })
})

describe('MeuPlantao — filtros e visão', () => {
  it('20. "Por residente" agrupa por pessoa e o filtro fica salvo ao voltar', async () => {
    const user = userEvent.setup()
    respondeCom(TRES_ITENS)
    const { unmount } = renderPlantao()

    await screen.findByText('Banho assistido')
    await user.click(screen.getByRole('button', { name: 'Por residente' }))
    await user.click(screen.getByRole('button', { name: /^Atrasados/ }))
    const maria = screen.getByRole('region', { name: 'Maria Silva' })
    expect(within(maria).getByText('Banho assistido')).toBeTruthy()
    expect(screen.queryByText('Dose prevista de medicação')).toBeNull()

    unmount()
    renderPlantao()
    await screen.findByText('Banho assistido')
    expect(screen.getByRole('button', { name: /^Atrasados/ }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('button', { name: 'Por residente' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('22. com a tela aberta, o item passa a "Atrasada" quando o horário chega', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const quase = { ...CUIDADO_2, previsto_em: new Date(Date.now() + 10_000).toISOString() }
      respondeCom([quase])
      renderPlantao()
      expect(await screen.findByRole('region', { name: 'Próximas' })).toBeTruthy()
      await vi.advanceTimersByTimeAsync(31_000)
      await waitFor(() => expect(screen.getByRole('region', { name: 'Atrasadas' })).toBeTruthy())
      expect(within(screen.getByRole('region', { name: 'Atrasadas' })).getByText('Atrasada')).toBeTruthy()
    } finally {
      vi.useRealTimers()
    }
  })

  it('21. não há botão de nova tarefa nem POST /tarefas/', async () => {
    respondeCom(TRES_ITENS)
    renderPlantao()

    await screen.findByText('Banho assistido')
    expect(screen.queryByRole('button', { name: /nova tarefa/i })).toBeNull()
    expect(mockPost).not.toHaveBeenCalled()
  })
})

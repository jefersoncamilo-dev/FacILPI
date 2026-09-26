import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { PassagemPlantao } from '../pages/PassagemPlantao'
import { MeuPlantao, lerDesde } from '../pages/MeuPlantao'
import { api } from '../services/api'
import { contextApi } from '../services/context'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn() } }
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

const H = 3600_000
const em = (deltaMs: number) => new Date(Date.now() + deltaMs).toISOString()
const RESIDENTES = [
  { id: 'r1', nome: 'Antônia Ribeiro' }, { id: 'r2', nome: 'Benedito Carvalho' },
  { id: 'r3', nome: 'Carmem Dias' }, { id: 'r4', nome: 'Davi Esteves' },
]
function fixtures() {
  return {
    plantao: [
      { origem: 'cuidado', registro_id: 'o1', residente_id: 'r1', descricao: 'Mudança de decúbito', previsto_em: em(-2 * H), prioridade: 'alta' },
      { origem: 'medicacao', registro_id: 'd1', residente_id: 'r1', descricao: 'Dose prevista de medicacao', previsto_em: em(-1 * H) },
      { origem: 'cuidado', registro_id: 'o2', residente_id: 'r4', descricao: 'Banho', previsto_em: em(2 * H) },
      { origem: 'intercorrencia', registro_id: 'i1', residente_id: 'r1', descricao: 'Intercorrencia aberta: Queda', previsto_em: null },
    ],
    intercorrencias: [
      { id: 'i1', residente_id: 'r1', tipo: 'Queda', gravidade: 'moderada', situacao: 'aberta', ocorrido_em: em(-3 * H), sbar_recomendacao: 'Observar dor no quadril' },
      { id: 'i2', residente_id: 'r3', tipo: 'Febre', gravidade: 'leve', situacao: 'encerrada', ocorrido_em: em(-5 * H), desfecho: 'Resolvida com antitérmico' },
      { id: 'i3', residente_id: 'r3', tipo: 'Antiga', gravidade: 'leve', situacao: 'encerrada', ocorrido_em: em(-48 * H), desfecho: 'x' },
    ],
    ausencias: [
      { id: 'a1', residente_id: 'r2', quarto_leito_id: null, tipo: 'hospitalizacao', data_inicio: em(-20 * H), data_fim: null, motivo: 'Pneumonia', observacoes: null },
    ],
  }
}
const TUDO = ['plantao:ler', 'intercorrencias:ler', 'ausencias:ler', 'residentes:ler', 'execucoes:criar', 'administracoes:criar']

function responde(sobrescrever: Partial<Record<'plantao' | 'intercorrencias' | 'ausencias', unknown>> = {}) {
  const dados = { ...fixtures(), ...sobrescrever }
  mockGet.mockImplementation((url: string) => {
    const de = (x: unknown) => (x instanceof Error || (x as any)?.response ? Promise.reject(x) : Promise.resolve({ data: x } as any))
    if (url === '/plantao/') return de(dados.plantao)
    if (url === '/intercorrencias/') return de(dados.intercorrencias)
    if (url === '/ausencias/') return de(dados.ausencias)
    if (url === '/residentes/') return de(RESIDENTES)
    throw new Error(`URL inesperada: ${url}`)
  })
}

function renderTela(tela = <PassagemPlantao />, permissoes = TUDO, rota = '/passagem') {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes } } as any)
  return render(<AuthProvider><MemoryRouter initialEntries={[rota]}><PermissoesProvider>{tela}</PermissoesProvider></MemoryRouter></AuthProvider>)
}

const numero = (rotulo: string) => within(screen.getByRole('region', { name: 'Resumo do período' })).getByText(rotulo).nextElementSibling?.textContent

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  responde()
})

describe('Passagem de plantão — leitura do período', () => {
  it('resume e organiza por residente só com as fontes existentes', async () => {
    renderTela()
    const residentes = within(await screen.findByRole('region', { name: 'Residentes com pontos de atenção' }))
    await residentes.findByText('Carmem Dias')
    expect(numero('Intercorrências no período')).toBe('2')
    expect(numero('Sem registro no período')).toBe('2')
    expect(numero('Intercorrências abertas')).toBe('1')
    expect(numero('Ausentes agora')).toBe('1')
    expect(numero('Previstos nas próximas 12 h')).toBe('1')

    const cartoes = residentes.getAllByRole('listitem').filter(li => li.parentElement?.parentElement?.getAttribute('aria-label') === 'Residentes com pontos de atenção')
    // Com intercorrência aberta primeiro; quem só tem itens futuros não entra.
    expect(cartoes.map(c => within(c).getByRole('link').textContent)).toEqual(['Antônia Ribeiro', 'Benedito Carvalho', 'Carmem Dias'])
    const antonia = within(cartoes[0])
    expect(antonia.getByText(/Queda · Moderada/)).toBeTruthy()
    expect(antonia.getByText('Observar dor no quadril')).toBeTruthy()
    expect(antonia.getByText('Mudança de decúbito')).toBeTruthy()
    expect(antonia.getByText('Dose prevista de medicação')).toBeTruthy()
    expect(within(cartoes[1]).getByText(/Hospitalização desde .* — Pneumonia/)).toBeTruthy()
    expect(within(cartoes[2]).getByText(/Resolvida com antitérmico/)).toBeTruthy()
    expect(screen.queryByText('Antiga')).toBeNull()
  })

  it('consulta a janela escolhida e leva ao Meu Plantão a partir do início do período', async () => {
    const user = userEvent.setup()
    renderTela()
    const link = await screen.findByRole('link', { name: /Registrar no Meu Plantão/ })
    const chamada = mockGet.mock.calls.filter(([url]) => url === '/plantao/').at(-1)![1] as any
    const { a_partir_de, ate, limit } = chamada.params
    expect(limit).toBe(1000)
    expect(Date.parse(ate) - Date.parse(a_partir_de)).toBe(24 * H)
    expect(link.getAttribute('href')).toBe(`/plantao?desde=${encodeURIComponent(a_partir_de)}`)

    await user.click(screen.getByRole('button', { name: 'Últimas 6 h' }))
    const chamadas = () => mockGet.mock.calls.filter(([url]) => url === '/plantao/').map(([, c]) => (c as any).params)
    await waitFor(() => expect(chamadas().at(-1) && Date.parse(chamadas().at(-1).ate) - Date.parse(chamadas().at(-1).a_partir_de)).toBe(12 * H))
    const nova = chamadas().at(-1)
    await waitFor(() => expect(screen.getByRole('link', { name: /Registrar no Meu Plantão/ }).getAttribute('href')).toBe(`/plantao?desde=${encodeURIComponent(nova.a_partir_de)}`))
  })

  it('falha de uma fonte vira "visão parcial", nunca zero; falha do plantão não vira "nenhum ponto"', async () => {
    responde({ intercorrencias: new Error('rede') })
    const parcial = renderTela()
    expect(await screen.findByText('Visão parcial')).toBeTruthy()
    expect(numero('Intercorrências no período')).toBe('—')
    // A aberta continua aparecendo pelo resumo do plantão.
    expect(screen.getByText('Intercorrência aberta: Queda')).toBeTruthy()
    parcial.unmount()

    responde({ plantao: { response: { status: 403, data: { detail: 'x' } } } })
    const sem = renderTela()
    expect(await screen.findByText('Sem acesso à passagem de plantão')).toBeTruthy()
    sem.unmount()
    responde({ plantao: new Error('rede') })
    renderTela()
    expect(await screen.findByText('Não foi possível montar a passagem de plantão')).toBeTruthy()
    expect(screen.queryByText('Nenhum ponto de atenção registrado no período')).toBeNull()
  })

  it('sem permissão para intercorrências e ausências, não consulta e mostra "—"; sem pontos, estado vazio', async () => {
    responde({ plantao: [] })
    renderTela(<PassagemPlantao />, ['plantao:ler', 'residentes:ler'])
    expect(await screen.findByText('Nenhum ponto de atenção registrado no período')).toBeTruthy()
    await waitFor(() => expect(numero('Ausentes agora')).toBe('—'))
    expect(mockGet).not.toHaveBeenCalledWith('/intercorrencias/', expect.anything())
    expect(mockGet).not.toHaveBeenCalledWith('/ausencias/', expect.anything())
    expect(screen.queryByText('Visão parcial')).toBeNull()
    expect(screen.queryByRole('link', { name: /Registrar no Meu Plantão/ })).toBeNull()
  })
})

describe('Meu Plantão — ?desde= vindo da passagem', () => {
  it('aceita só instante válido no passado', () => {
    const agora = Date.parse('2026-09-25T15:00:00Z')
    expect(lerDesde('2026-09-25T03:00:00.000Z', agora)).toBe('2026-09-25T03:00:00.000Z')
    expect(lerDesde('2026-09-26T03:00:00Z', agora)).toBeNull()
    expect(lerDesde('ontem', agora)).toBeNull()
    expect(lerDesde(null, agora)).toBeNull()
  })

  it('amplia a projeção para trás e mostra o atrasado com as ações de sempre', async () => {
    const desde = em(-12 * H)
    responde()
    renderTela(<MeuPlantao />, TUDO, `/plantao?desde=${encodeURIComponent(desde)}`)
    expect(await screen.findByText('Mudança de decúbito')).toBeTruthy()
    expect(mockGet).toHaveBeenCalledWith('/plantao/', { params: { a_partir_de: new Date(Date.parse(desde)).toISOString() } })
    expect(screen.getByRole('link', { name: 'ver só a partir de agora' }).getAttribute('href')).toBe('/plantao')
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router'
import { PermissoesProvider } from '../context/PermissoesContext'
import { ResidenteProntuario } from '../pages/ResidenteProntuario'
import { MONITORAMENTO_LIMIT, seriesDaMedida, valorDaMedida } from '../components/prontuario/MonitoramentoSinais'
import { api } from '../services/api'
import { contextApi } from '../services/context'
import { limparCentralAlertas } from '../hooks/useCentralAlertas'

// UX-NAV-4 (#298). Dados sintéticos: nomes fictícios, nenhum dado real.
vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() } }
})
vi.mock('../services/context', () => ({ contextApi: { permissoesDaSessao: vi.fn() } }))

const mockGet = vi.mocked(api.get)
const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

const dias = (n: number) => new Date(Date.now() - n * 24 * 60 * 60 * 1000).toISOString()

const SINAIS = [
  { id: 's3', residente_id: 'r1', pressao_sistolica: 131, pressao_diastolica: 79, temperatura: 36.4, data: dias(1), profissional: 'Téc. Sintética' },
  { id: 's2', residente_id: 'r1', pressao_sistolica: 140, pressao_diastolica: 88, glicemia: 118, data: dias(5), profissional: 'Enf. Sintético' },
  { id: 's1', residente_id: 'r1', pressao_sistolica: 125, pressao_diastolica: 80, peso: 61.4, data: dias(20), profissional: 'Enf. Sintético' },
]

let sinais: unknown[] = SINAIS

function fontes(url: string) {
  if (url === '/residentes/r1') return { id: 'r1', nome: 'Ana Sintética', situacao: 'Ativo' }
  if (url === '/residentes/r1/prontuario') return { items: [], next_cursor: null, has_more: false }
  if (url === '/sinais-vitais/') return sinais
  return []
}

function Url() {
  const { search } = useLocation()
  return <output data-testid="url">{search}</output>
}

function renderMonitoramento(permissoes: string[] = ['residentes:ler', 'sinais_vitais:ler'], busca = '?aba=monitoramento') {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', ilpi_id: 'ilpi1', permissoes } } as any)
  mockGet.mockImplementation(((url: string) => Promise.resolve({ data: fontes(url) })) as any)
  return render(
    <PermissoesProvider>
      <MemoryRouter initialEntries={[`/residentes/r1${busca}`]}>
        <Routes>
          <Route path="/residentes/:id" element={<><ResidenteProntuario /><Url /></>} />
        </Routes>
      </MemoryRouter>
    </PermissoesProvider>,
  )
}

const url = () => screen.getByTestId('url').textContent ?? ''
const medidas = () => within(screen.getByRole('list', { name: 'Medidas' })).getAllByRole('button')
const detalhe = () => document.getElementById('monitoramento-detalhe') as HTMLElement

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  limparCentralAlertas()
  sinais = SINAIS
})

describe('UX-NAV-4 — aba Monitoramento', () => {
  it('um cartão por medida registrada, na ordem definida, com último valor e autoria', async () => {
    renderMonitoramento()
    await waitFor(() => expect(medidas()).toHaveLength(4))
    expect(medidas().map(b => b.textContent?.split(/\d/)[0])).toEqual(['Pressão arterial', 'Temperatura', 'Glicemia', 'Peso'])
    expect(medidas()[0].textContent).toContain('131/79')
    expect(medidas()[0].textContent).toContain('Téc. Sintética')
  })

  it('busca um lote maior, só do residente da ficha', async () => {
    renderMonitoramento()
    await waitFor(() => expect(medidas()).toHaveLength(4))
    expect(mockGet).toHaveBeenCalledWith('/sinais-vitais/', { params: { residente_id: 'r1', limit: MONITORAMENTO_LIMIT } })
  })

  it('abre a primeira medida e troca pelo clique, guardando ?medida= na URL', async () => {
    const user = userEvent.setup()
    renderMonitoramento()
    await waitFor(() => expect(medidas()).toHaveLength(4))
    expect(medidas()[0].getAttribute('aria-pressed')).toBe('true')
    expect(detalhe().getAttribute('aria-live')).toBe('polite')
    expect(within(detalhe()).getByRole('img').getAttribute('aria-label')).toMatch(/^Pressão arterial\./)

    await user.click(medidas()[2])
    expect(medidas()[2].getAttribute('aria-pressed')).toBe('true')
    expect(medidas()[0].getAttribute('aria-pressed')).toBe('false')
    expect(url()).toContain('medida=glicemia')
    // O valor aparece no rótulo do gráfico e na tabela.
    expect(within(detalhe()).getAllByText('118').length).toBeGreaterThan(0)
  })

  it('?medida= válida abre direto; inválida cai na primeira e sai da URL', async () => {
    const { unmount } = renderMonitoramento(undefined, '?aba=monitoramento&medida=peso')
    await waitFor(() => expect(medidas()).toHaveLength(4))
    expect(medidas()[3].getAttribute('aria-pressed')).toBe('true')
    unmount()

    renderMonitoramento(undefined, '?aba=monitoramento&medida=inexistente')
    await waitFor(() => expect(medidas()).toHaveLength(4))
    expect(medidas()[0].getAttribute('aria-pressed')).toBe('true')
    await waitFor(() => expect(url()).not.toContain('medida='))
  })

  it('período filtra o gráfico e a tabela; o padrão é 14 dias', async () => {
    const user = userEvent.setup()
    renderMonitoramento(undefined, '?aba=monitoramento&medida=peso')
    await waitFor(() => expect(medidas()).toHaveLength(4))
    expect(screen.getByRole('button', { name: '14 dias' }).getAttribute('aria-pressed')).toBe('true')
    // Peso só tem registro de 20 dias atrás: fora dos 14 dias.
    expect(within(detalhe()).getByText('Nenhum registro desta medida nos últimos 14 dias.')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '30 dias' }))
    expect(url()).toContain('periodo=30')
    expect(within(detalhe()).getAllByText('61,4').length).toBeGreaterThan(0)
    expect(within(detalhe()).getByRole('img')).toBeTruthy()
  })

  it('sem registros mostra estado vazio', async () => {
    sinais = []
    renderMonitoramento()
    expect(await screen.findByText('Sem aferições ainda')).toBeTruthy()
  })

  it('a aba só existe com sinais_vitais:ler', async () => {
    renderMonitoramento(['residentes:ler'], '?aba=monitoramento')
    expect(await screen.findByText('Monitoramento não está liberada para você. Mostrando a aba Resumo.')).toBeTruthy()
    expect(screen.queryByRole('tab', { name: 'Monitoramento' })).toBeNull()
  })

  it('não julga valores: nenhuma faixa, meta ou selo de normal/atenção', async () => {
    renderMonitoramento()
    await waitFor(() => expect(medidas()).toHaveLength(4))
    expect(document.body.textContent).not.toMatch(/normal|atenção|alterad|meta|referência|acima|abaixo/i)
  })
})

describe('UX-NAV-4 — funções da medida', () => {
  it('valor da pressão junta sistólica e diastólica; sem valor é null', () => {
    expect(valorDaMedida({ id: 'x', residente_id: 'r', pressao_sistolica: 120, pressao_diastolica: 80 }, ['pressao_sistolica', 'pressao_diastolica'])).toBe('120/80')
    expect(valorDaMedida({ id: 'x', residente_id: 'r', temperatura: 36.45 }, ['temperatura'])).toBe('36,5')
    expect(valorDaMedida({ id: 'x', residente_id: 'r' }, ['peso'])).toBeNull()
  })

  it('séries em ordem de data, a segunda tracejada', () => {
    const series = seriesDaMedida(SINAIS as any, ['pressao_sistolica', 'pressao_diastolica'])
    expect(series.map(s => s.pontos.map(p => p.valor))).toEqual([[125, 140, 131], [80, 88, 79]])
    expect(series[1].tracejado).toBe(true)
  })
})

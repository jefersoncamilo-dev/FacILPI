import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router'
import { PermissoesProvider } from '../context/PermissoesContext'
import { ResidenteProntuario } from '../pages/ResidenteProntuario'
import { api } from '../services/api'
import { contextApi } from '../services/context'
import { limparCentralAlertas } from '../hooks/useCentralAlertas'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() } }
})
vi.mock('../services/context', () => ({
  contextApi: { permissoesDaSessao: vi.fn() },
}))

const mockGet = vi.mocked(api.get)
const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

const TODAS = ['residentes:ler', 'planos_cuidados:ler', 'prescricoes:ler', 'sinais_vitais:ler', 'intercorrencias:ler', 'alertas:ler']

const FONTES: Record<string, unknown> = {
  '/residentes/r1': { id: 'r1', nome: 'Maria da Silva', situacao: 'Ativo' },
  '/residentes/r1/prontuario': { items: [], next_cursor: null, has_more: false },
  '/planos-cuidados/': [
    { id: 'p0', residente_id: 'r1', versao: 1, situacao: 'substituido', data_inicial: '2026-01-01', data_final: null, objetivos: 'Antigo' },
    { id: 'p1', residente_id: 'r1', versao: 2, situacao: 'vigente', data_inicial: '2026-06-01', data_final: null, objetivos: 'Manter mobilidade' },
  ],
  '/prescricoes/': [
    { id: 'm1', situacao: 'ativa', dose: '1', unidade: 'comprimido', via: 'oral', frequencia: '8/8h', medicamento_snapshot: { nome: 'Losartana' } },
    { id: 'm2', situacao: 'suspensa', dose: '1', unidade: null, via: null, frequencia: null, medicamento_snapshot: { nome: 'Dipirona' } },
  ],
  '/sinais-vitais/': [{ id: 's1', residente_id: 'r1', data: '2026-10-23T10:00:00Z', temperatura: 36.5, saturacao: 97 }],
  '/intercorrencias/': [
    { id: 'i1', residente_id: 'r1', tipo: 'Queda', gravidade: 'grave', situacao: 'aberta', ocorrido_em: '2026-10-23T09:00:00Z' },
    { id: 'i2', residente_id: 'r1', tipo: 'Febre', gravidade: 'leve', situacao: 'encerrada', ocorrido_em: '2026-10-20T09:00:00Z' },
  ],
  '/central-alertas/': {
    gerado_em: '2026-10-24T00:00:00Z',
    contagem: { total: 2 },
    alertas: [
      { id: 'a1', regra: 'grau_vencido', categoria: 'avaliacao_grau_pais', gravidade: 'atencao', natureza: 'pendencia', titulo: 'Grau de dependência vencido', residente_id: 'r1', referencia_id: null },
      { id: 'a2', regra: 'grau_vencido', categoria: 'avaliacao_grau_pais', gravidade: 'atencao', natureza: 'pendencia', titulo: 'Alerta de outro residente', residente_id: 'r2', referencia_id: null },
    ],
  },
}

function renderTela(permissoes: string[], trocas: Record<string, unknown> = {}) {
  const fontes = { ...FONTES, ...trocas }
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', ilpi_id: 'ilpi1', permissoes } } as any)
  mockGet.mockImplementation(((url: string) => {
    const f = url in fontes ? fontes[url] : []
    return f instanceof Error ? Promise.reject(f) : Promise.resolve({ data: f })
  }) as any)
  return render(
    <PermissoesProvider>
      <MemoryRouter initialEntries={['/residentes/r1']}>
        <Routes>
          <Route path="/residentes/:id" element={<ResidenteProntuario />} />
        </Routes>
      </MemoryRouter>
    </PermissoesProvider>,
  )
}

const chamou = (url: string) => mockGet.mock.calls.some(c => c[0] === url)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  limparCentralAlertas()
})

describe('M4 — Resumo do residente', () => {
  it('Resumo é a aba padrão e mostra cada card com a sua fonte', async () => {
    renderTela(TODAS)
    expect(screen.getByRole('tab', { name: 'Resumo' }).getAttribute('aria-selected')).toBe('true')

    const pais = await screen.findByRole('region', { name: 'PAIS vigente' })
    expect(await within(pais).findByText(/Versão 2/)).toBeTruthy()
    expect(within(pais).getByText('Manter mobilidade')).toBeTruthy()

    const presc = screen.getByRole('region', { name: 'Prescrições ativas' })
    expect(await within(presc).findByText('Losartana')).toBeTruthy()
    expect(within(presc).queryByText('Dipirona')).toBeNull()

    const sinais = screen.getByRole('region', { name: 'Última aferição' })
    expect(await within(sinais).findByText(/Saturação/)).toBeTruthy()

    const inter = screen.getByRole('region', { name: 'Intercorrências abertas' })
    expect(await within(inter).findByText('Queda')).toBeTruthy()
    expect(within(inter).queryByText('Febre')).toBeNull()

    const alertas = screen.getByRole('region', { name: 'Alertas do residente' })
    expect(await within(alertas).findByText('Grau de dependência vencido')).toBeTruthy()
    expect(within(alertas).queryByText('Alerta de outro residente')).toBeNull()

    expect(mockGet).toHaveBeenCalledWith('/sinais-vitais/', { params: { residente_id: 'r1', limit: 1 } })
    expect(mockGet).toHaveBeenCalledWith('/planos-cuidados/', { params: { residente_id: 'r1' } })
  })

  it('card sem permissão não aparece nem faz requisição', async () => {
    renderTela(['residentes:ler', 'sinais_vitais:ler'])
    expect(await screen.findByRole('region', { name: 'Última aferição' })).toBeTruthy()
    for (const titulo of ['PAIS vigente', 'Prescrições ativas', 'Intercorrências abertas', 'Alertas do residente']) {
      expect(screen.queryByRole('region', { name: titulo })).toBeNull()
    }
    for (const url of ['/planos-cuidados/', '/prescricoes/', '/intercorrencias/', '/central-alertas/']) {
      expect(chamou(url)).toBe(false)
    }
  })

  it('estados vazios e falha isolada por card', async () => {
    renderTela(TODAS, { '/prescricoes/': new Error('500'), '/intercorrencias/': [], '/planos-cuidados/': [] })
    expect(await screen.findByText('Não foi possível carregar.')).toBeTruthy()
    expect(within(screen.getByRole('region', { name: 'Prescrições ativas' })).getByText('Não foi possível carregar.')).toBeTruthy()
    expect(await screen.findByText('Nenhuma intercorrência aberta.')).toBeTruthy()
    expect(await screen.findByText('Nenhum PAIS vigente.')).toBeTruthy()
    // As outras fontes seguem normais.
    expect(await screen.findByText(/Saturação/)).toBeTruthy()
  })

  it('a linha do tempo segue disponível na segunda aba', async () => {
    renderTela(TODAS)
    screen.getByRole('tab', { name: 'Linha do tempo' }).click()
    expect(await screen.findByText('Nenhum evento encontrado')).toBeTruthy()
    expect(screen.getByRole('tab', { name: 'Linha do tempo' }).getAttribute('aria-selected')).toBe('true')
    expect(screen.queryByRole('region', { name: 'PAIS vigente' })).toBeNull()
  })
})

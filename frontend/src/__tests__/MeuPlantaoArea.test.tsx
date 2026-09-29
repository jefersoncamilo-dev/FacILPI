import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { MinhaArea } from '../components/plantao/MinhaArea'
import { api } from '../services/api'
import { destinoAposLogin, type MeuPlantaoResumo } from '../services/meuPlantao'
import type { Alerta } from '../services/alertas'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
})

const mockGet = vi.mocked(api.get)

const QUEDA: Alerta = {
  id: 'intercorrencia_grave_aberta:i1', regra: 'intercorrencia_grave_aberta', categoria: 'plantao', gravidade: 'critico',
  natureza: 'alerta', titulo: 'Intercorrência grave aberta: Queda', detalhe: null, residente_id: 'r1', residente_nome: 'Hilda Sintetica',
  referencia_id: 'i1', unidade: 'Ala B', quarto: '12', leito: 'A', local: 'Ala B · Quarto 12 · Leito A', desde: null, prazo: null, estado: null,
}

function resumo(parcial: Partial<MeuPlantaoResumo> = {}): MeuPlantaoResumo {
  return {
    gerado_em: '2026-09-28T12:00:00Z',
    plantao: {
      id: 'p1', funcionario_id: 'f1', funcionario_nome: 'Ana', turno_id: null, turno_nome: 'Diurno', inicio_em: '2026-09-28T10:00:00Z',
      fim_em: null, situacao: 'em_andamento', escala_id: null, responsabilidades: [],
    },
    escalas_pendentes: [],
    areas: [{ id: 'a1', nome: 'Ala B' }],
    residentes: [
      { id: 'r1', nome: 'Hilda Sintetica', local: 'Ala B · Quarto 12 · Leito A', em_atencao: true, motivos: ['Intercorrência grave aberta: Queda'] },
      { id: 'r2', nome: 'Rita Sintetica', local: 'Ala B · Quarto 12 · Leito B', em_atencao: false, motivos: [] },
    ],
    prioridades: [QUEDA],
    atividades: { atrasadas: [{ origem: 'cuidado', registro_id: 'o1', residente_id: 'r2', residente_nome: 'Rita Sintetica', descricao: 'Banho', previsto_em: '2026-09-28T11:45:00Z' }], proximas: [] },
    passagens_a_receber: 1,
    ...parcial,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('Minha área agora (#126)', () => {
  it('mostra área, residentes em atenção, prioridades e passagem a receber, levando à origem', () => {
    render(<MemoryRouter><MinhaArea resumo={resumo()} podeAssumir onMudou={() => {}} /></MemoryRouter>)
    const secao = screen.getByRole('region', { name: 'Minha área agora' })
    expect(within(secao).getByText('Ala B · 2 residentes · 1 em atenção · 1 prioridade')).toBeTruthy()
    expect(within(secao).getByRole('link', { name: 'Hilda Sintetica' }).getAttribute('href')).toBe('/residentes/r1')
    expect(within(secao).queryByRole('link', { name: 'Rita Sintetica' })).toBeNull()
    expect(within(secao).getByRole('link', { name: 'Ver intercorrência em Intercorrências' }).getAttribute('href')).toBe('/intercorrencias')
    expect(within(secao).getByRole('button', { name: /^Assumir/ })).toBeTruthy()
    expect(within(secao).getByRole('link', { name: /1 passagem de plantão aguardando você/ }).getAttribute('href')).toBe('/passagem')
    expect(within(secao).getByText(/1 atrasada/)).toBeTruthy()
    // Atrasadas listadas, com o caminho para registrá-las a partir do horário mais antigo.
    expect(within(within(secao).getByRole('list', { name: 'Atividades atrasadas' })).getByText(/Rita Sintetica/)).toBeTruthy()
    expect(within(secao).getByRole('link', { name: /Registrar as atrasadas/ }).getAttribute('href'))
      .toBe('/plantao?desde=2026-09-28T11%3A45%3A00Z')
  })

  it('sem plantão ou sem área não aparece; blocos sem leitura ficam de fora', () => {
    const { container, rerender } = render(<MemoryRouter><MinhaArea resumo={resumo({ plantao: null, areas: [] })} podeAssumir={false} onMudou={() => {}} /></MemoryRouter>)
    expect(container.textContent).toBe('')
    rerender(<MemoryRouter><MinhaArea resumo={resumo({ residentes: null, prioridades: null, atividades: null, passagens_a_receber: null })} podeAssumir={false} onMudou={() => {}} /></MemoryRouter>)
    expect(screen.getByText('Ala B')).toBeTruthy()
    expect(screen.queryByText(/Residentes em atenção/)).toBeNull()
    expect(screen.queryByText(/Prioridades da área/)).toBeNull()
  })
})

describe('Destino após o login (#126)', () => {
  it('com plantão ativo vai para Meu Plantão; sem plantão ou com falha, Início', async () => {
    mockGet.mockResolvedValueOnce({ data: { pode_registrar: true, funcionario_id: 'f1', plantao: { id: 'p1' } } } as any)
    expect(await destinoAposLogin()).toBe('/plantao')
    mockGet.mockResolvedValueOnce({ data: { pode_registrar: true, funcionario_id: 'f1', plantao: null } } as any)
    expect(await destinoAposLogin()).toBe('/')
    mockGet.mockRejectedValueOnce(new Error('rede'))
    expect(await destinoAposLogin()).toBe('/')
    expect(mockGet).toHaveBeenCalledWith('/plantoes/atual')

    // Sem resposta: em 3 s segue para o Início (o login nunca fica preso).
    vi.useFakeTimers()
    try {
      mockGet.mockReturnValueOnce(new Promise(() => {}) as any)
      const destino = destinoAposLogin()
      await vi.advanceTimersByTimeAsync(3000)
      expect(await destino).toBe('/')
    } finally {
      vi.useRealTimers()
    }
  })
})

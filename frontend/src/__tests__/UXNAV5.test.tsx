import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { RotinaIlpi, piorSituacao, resumoDoTurno } from '../pages/RotinaIlpi'
import { api } from '../services/api'

// UX-NAV-5 (#302). Dados sintéticos: nomes fictícios, nenhum dado real.
vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn() } }
})
const mockGet = vi.mocked(api.get)

const item = (id: string, residente_id: string, hora: string, situacao: string, origem = 'cuidado') =>
  ({ origem, registro_id: id, residente_id, descricao: `Item ${id}`, previsto_em: `2026-11-22T${hora}:00:00Z`, situacao })

const MAPA = {
  dia: '2026-11-22', turno: 'manha', inicio: '2026-11-22T10:00:00Z', fim: '2026-11-22T16:00:00Z',
  fuso: 'UTC', agora: '2026-11-22T11:30:00Z', ve_medicacao: true,
  residentes: [
    { id: 'r1', nome: 'Ana Sintética', ala: 'Ala A', local: 'Ala A · Quarto 1' },
    { id: 'r2', nome: 'Beto Sintético', ala: 'Ala B', local: 'Ala B · Quarto 7' },
  ],
  itens: [
    item('a', 'r1', '10', 'concluido'), item('b', 'r1', '11', 'ressalva', 'medicacao'),
    item('c', 'r2', '10', 'atrasado'), item('d', 'r2', '11', 'concluido', 'medicacao'),
  ],
}

beforeEach(() => {
  mockGet.mockReset()
  mockGet.mockResolvedValue({ data: MAPA } as any)
})

describe('Rotina da ILPI (#302)', () => {
  it('calcula a pior situação e o resumo sem contar n.a.', () => {
    expect(piorSituacao([])).toBe('nao_se_aplica')
    expect(piorSituacao(MAPA.itens.slice(0, 2) as any)).toBe('ressalva')
    expect(resumoDoTurno(MAPA.itens as any)).toEqual({ concluida: 50, medicacao: 50, ressalvas: 1, atrasados: 1 })
  })

  it('mostra o mapa, destaca a hora atual, busca, filtra por ala e leva à ficha', async () => {
    render(<MemoryRouter><RotinaIlpi /></MemoryRouter>)
    const ana = await screen.findByRole('link', { name: 'Ana Sintética' })
    expect(ana).toHaveAttribute('href', '/residentes/r1?aba=monitoramento')
    expect(mockGet).toHaveBeenCalledWith('/plantao/mapa', expect.objectContaining({ params: expect.objectContaining({ turno: expect.any(String) }) }))
    expect(screen.getByRole('columnheader', { name: /11h.*agora/ })).toBeInTheDocument()
    const linhaBeto = screen.getByRole('row', { name: /Beto Sintético/ })
    expect(within(linhaBeto).getByLabelText(/10h: Item c: Atrasado/)).toHaveAttribute('data-situacao', 'atrasado')

    await userEvent.type(screen.getByPlaceholderText('Buscar por nome ou quarto'), 'quarto 7')
    expect(screen.queryByRole('link', { name: 'Ana Sintética' })).not.toBeInTheDocument()
    await userEvent.clear(screen.getByPlaceholderText('Buscar por nome ou quarto'))
    await userEvent.selectOptions(screen.getByLabelText('Filtrar por ala'), 'Ala A')
    expect(screen.queryByRole('link', { name: 'Beto Sintético' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ana Sintética' })).toBeInTheDocument()
  })

  it('navega por dia e turno pedindo o mapa ao backend', async () => {
    render(<MemoryRouter><RotinaIlpi /></MemoryRouter>)
    await screen.findByRole('link', { name: 'Ana Sintética' })
    await userEvent.click(screen.getByRole('tab', { name: /Noite/ }))
    expect(mockGet).toHaveBeenLastCalledWith('/plantao/mapa', { params: expect.objectContaining({ turno: 'noite' }) })
    const antes = (mockGet.mock.lastCall![1] as any).params.dia
    await userEvent.click(screen.getByRole('button', { name: 'Dia anterior' }))
    expect((mockGet.mock.lastCall![1] as any).params.dia < antes).toBe(true)
  })
})

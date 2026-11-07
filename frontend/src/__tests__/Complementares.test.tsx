import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { Agenda, Estoque, Financeiro, Multidisciplinar, Pia } from '../pages/Complementares'
import { api } from '../services/api'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn() } }
})
const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)
const RES = { id: 'r1', nome: 'Dona Sintética' }

function responder(rotas: Record<string, unknown>) {
  mockGet.mockImplementation((url: string) => Promise.resolve({ data: url === '/residentes/' ? [RES] : rotas[url] ?? [] }) as any)
}

describe('Complementares', () => {
  beforeEach(() => { vi.clearAllMocks(); mockPost.mockResolvedValue({ data: {} } as any) })

  it('Agenda lista o evento com o residente', async () => {
    responder({ '/agenda/': [{ id: 'e', residente_id: 'r1', motivo: 'Consulta', especialidade: null, profissional: null, local: null, inicio_em: '2030-01-10T12:00:00Z', situacao: 'agendado', resultado: null, motivo_cancelamento: null }] })
    render(<MemoryRouter><Agenda /></MemoryRouter>)
    expect(await screen.findByText('Consulta')).toBeTruthy()
    await waitFor(() => expect(screen.getByText(/· Dona Sintética/)).toBeTruthy())
  })

  it('Agenda cancela pelo diálogo, com motivo obrigatório', async () => {
    responder({ '/agenda/': [{ id: 'e', residente_id: 'r1', motivo: 'Consulta', especialidade: null, profissional: null, local: null, inicio_em: '2030-01-10T12:00:00Z', situacao: 'agendado', resultado: null, motivo_cancelamento: null }] })
    render(<MemoryRouter><Agenda /></MemoryRouter>)
    await userEvent.click(await screen.findByRole('button', { name: 'Cancelar' }))
    await userEvent.type(await screen.findByLabelText('Por que foi cancelado?'), 'Família remarcou')
    await userEvent.click(screen.getByRole('button', { name: 'Confirmar' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/agenda/e/cancelar', { texto: 'Família remarcou' }))
  })

  it('Multidisciplinar usa a área da rota; 403 mostra sem acesso', async () => {
    mockGet.mockRejectedValue({ response: { status: 403 } })
    render(<MemoryRouter initialEntries={['/multidisciplinar/nutricao']}><Routes><Route path="/multidisciplinar/:area" element={<Multidisciplinar />} /></Routes></MemoryRouter>)
    expect(await screen.findByText('Sem acesso')).toBeTruthy()
    expect(mockGet).toHaveBeenCalledWith('/multidisciplinar/nutricao')
  })

  it('PIA salva nova versão do residente escolhido', async () => {
    responder({})
    render(<MemoryRouter><Pia /></MemoryRouter>)
    await screen.findByRole('option', { name: 'Dona Sintética' })
    await userEvent.selectOptions(screen.getByLabelText('Residente'), 'r1')
    await userEvent.type(await screen.findByLabelText('Apoio social'), 'Filha')
    await userEvent.click(screen.getByRole('button', { name: 'Salvar nova versão' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalled())
    expect(mockPost.mock.calls[0][0]).toBe('/pia/r1')
    expect(mockPost.mock.calls[0][1]).toMatchObject({ apoio_social: 'Filha' })
  })

  it('Estoque avisa abaixo do mínimo', async () => {
    responder({ '/estoque/itens': [{ id: 'i', nome: 'Luva', unidade: 'cx', categoria: null, localizacao: null, estoque_minimo: 5, saldo: 2, abaixo_do_minimo: true, lotes: [{ lote: 'L1', validade: null, saldo: 2 }] }] })
    render(<MemoryRouter><Estoque /></MemoryRouter>)
    expect(await screen.findByText('Abaixo do mínimo')).toBeTruthy()
  })

  it('Financeiro lança valor em centavos', async () => {
    responder({})
    render(<MemoryRouter><Financeiro /></MemoryRouter>)
    await screen.findByRole('option', { name: 'Dona Sintética' })
    await userEvent.selectOptions(screen.getByLabelText('Residente'), 'r1')
    await userEvent.type(screen.getByLabelText('Competência'), '2030-01')
    await userEvent.type(screen.getByLabelText('Valor (R$)'), '3500,50')
    await userEvent.type(screen.getByLabelText('Vencimento'), '2030-01-10')
    await userEvent.click(screen.getByRole('button', { name: 'Lançar mensalidade' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalled())
    expect(mockPost.mock.calls[0][1]).toMatchObject({ valor_centavos: 350050, competencia: '2030-01' })
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router'
import { Medicacao } from '../pages/Medicacao'
import { PermissoesProvider } from '../context/PermissoesContext'
import { api } from '../services/api'

// M9: ciclo completo da prescrição pela tela, com o cliente HTTP mockado.
vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() } }
})

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)

const TODAS = [
  'medicamentos:ler', 'medicamentos:criar', 'prescricoes:ler', 'prescricoes:criar',
  'prescricoes:atualizar', 'doses_previstas:ler',
]

const BASE = {
  residente_id: 'res-1', medicamento_id: 'med-1', prescritor: 'Dr Externo', prescritor_nome: 'Dr Externo',
  prescritor_categoria: 'Médico', prescritor_conselho: 'CRM', prescritor_numero: '123', prescritor_uf: 'SP',
  dose: '1', unidade: 'cp', via: 'oral', frequencia: null, inicio: '2026-10-27', orientacoes: null,
  medicamento_snapshot: { nome: 'Losartana' },
}

let prescricoes: any[] = []

function montar(permissoes: string[], rota = '/residentes/res-1/medicacao') {
  mockGet.mockImplementation((url: string) => {
    const r = (data: unknown) => Promise.resolve({ data } as any)
    if (url === '/context/permissoes' || url.includes('permissoes')) return r({ permissoes })
    if (url === '/residentes/') return r([{ id: 'res-1', nome: 'Maria Silva' }])
    if (url === '/medicamentos/') return r([{ id: 'med-1', nome: 'Losartana', situacao: 'ativo' }])
    if (url === '/prescricoes/') return r(prescricoes)
    if (url === '/doses-previstas/') return r([
      { id: 'd1', residente_id: 'res-1', prescricao_id: 'p-ativa', previsto_em: '2026-10-27T11:00:00Z', situacao: 'prevista', pendente: true },
    ])
    throw new Error(`URL inesperada: ${url}`)
  })
  return render(
    <PermissoesProvider>
      <MemoryRouter initialEntries={[rota]}>
        <Routes>
          <Route path="/residentes/:id/medicacao" element={<Medicacao />} />
          <Route path="/medicacao" element={<Medicacao />} />
        </Routes>
      </MemoryRouter>
    </PermissoesProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  prescricoes = []
})

describe('Medicacao (M9)', () => {
  it('cria rascunho com prescritor externo e ativa com horários fixos', async () => {
    const user = userEvent.setup()
    mockPost.mockImplementation((url: string) => {
      if (url === '/prescricoes/') {
        prescricoes = [{ ...BASE, id: 'p-1', situacao: 'rascunho' }]
        return Promise.resolve({ data: prescricoes[0] } as any)
      }
      if (url === '/prescricoes/p-1/ativar') {
        prescricoes = [{ ...BASE, id: 'p-1', situacao: 'ativa', programacao: { id: 'g', horarios: ['08:00', '20:00'], timezone: 'America/Sao_Paulo', vigencia_inicio: '2026-10-27T00:00:00Z', situacao: 'ativa' } }]
        return Promise.resolve({ data: prescricoes[0] } as any)
      }
      throw new Error(url)
    })
    montar(TODAS)
    await user.click(await screen.findByRole('button', { name: 'Nova prescrição' }))
    const form = screen.getByRole('form', { name: 'Nova prescrição' })
    await user.selectOptions(within(form).getByLabelText('Medicamento'), 'med-1')
    await user.type(within(form).getByLabelText('Prescritor'), 'Dr Externo')
    await user.type(within(form).getByLabelText('Número no conselho'), '123')
    await user.type(within(form).getByLabelText('Dose'), '1')
    await user.type(within(form).getByLabelText('Unidade'), 'cp')
    await user.click(within(form).getByRole('button', { name: 'Salvar rascunho' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/prescricoes/', expect.objectContaining({
      residente_id: 'res-1', medicamento_id: 'med-1', prescritor_nome: 'Dr Externo', prescritor_numero: '123',
      dose: '1', unidade: 'cp', via: 'oral',
    })))
    const enviado = mockPost.mock.calls[0][1] as Record<string, unknown>
    expect(enviado).not.toHaveProperty('frequencia')
    expect(enviado).not.toHaveProperty('ilpi_id')
    expect(await screen.findByText('Rascunho de prescrição criado.')).toBeInTheDocument()

    const rascunhos = await screen.findByRole('region', { name: 'Rascunhos' })
    await user.click(within(rascunhos).getByRole('button', { name: 'Ativar' }))
    await user.type(within(rascunhos).getByLabelText(/Horários fixos/), '20:00, 08:00')
    await user.click(within(rascunhos).getByRole('button', { name: 'Confirmar' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/prescricoes/p-1/ativar', expect.objectContaining({
      horarios: ['08:00', '20:00'], timezone: expect.any(String), vigencia_inicio: expect.any(String),
    })))
    const ativas = await screen.findByRole('region', { name: 'Ativas' })
    expect(within(ativas).getByText('Horários: 08:00, 20:00')).toBeInTheDocument()
  })

  it('suspende, encerra e substitui exigindo motivo', async () => {
    const user = userEvent.setup()
    prescricoes = [
      { ...BASE, id: 'p-ativa', situacao: 'ativa', programacao: { id: 'g', horarios: ['08:00'], timezone: 'UTC', vigencia_inicio: 'x', situacao: 'ativa' } },
    ]
    mockPost.mockResolvedValue({ data: {} } as any)
    montar(TODAS)
    const ativas = await screen.findByRole('region', { name: 'Ativas' })

    await user.click(within(ativas).getByRole('button', { name: 'Suspender' }))
    expect(within(ativas).getByLabelText('Motivo')).toBeRequired()
    await user.type(within(ativas).getByLabelText('Motivo'), 'Hipotensão')
    await user.click(within(ativas).getByRole('button', { name: 'Confirmar' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/prescricoes/p-ativa/suspender', { motivo: 'Hipotensão' }))

    await user.click(await within(ativas).findByRole('button', { name: 'Encerrar' }))
    await user.type(within(ativas).getByLabelText('Motivo'), 'Fim do tratamento')
    await user.click(within(ativas).getByRole('button', { name: 'Confirmar' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/prescricoes/p-ativa/encerrar', { motivo: 'Fim do tratamento' }))

    await user.click(await within(ativas).findByRole('button', { name: 'Substituir' }))
    const dose = within(ativas).getByLabelText('Nova dose')
    await user.clear(dose)
    await user.type(dose, '2')
    await user.type(within(ativas).getByLabelText('Motivo'), 'Ajuste de dose')
    await user.click(within(ativas).getByRole('button', { name: 'Confirmar' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/prescricoes/p-ativa/substituir', expect.objectContaining({
      motivo: 'Ajuste de dose',
      programacao: expect.objectContaining({ horarios: ['08:00'] }),
      prescricao: expect.objectContaining({ residente_id: 'res-1', medicamento_id: 'med-1', dose: '2', prescritor_nome: 'Dr Externo' }),
    })))
  })

  it('mostra a grade de doses do dia só para leitura', async () => {
    prescricoes = [{ ...BASE, id: 'p-ativa', situacao: 'ativa' }]
    montar(TODAS)
    const grade = await screen.findByRole('region', { name: 'Doses de hoje' })
    expect(await within(grade).findByText(/Losartana 1 cp/)).toBeInTheDocument()
    expect(within(grade).getByText('Prevista')).toBeInTheDocument()
    expect(within(grade).queryByRole('button')).toBeNull()
  })

  it('sem permissão de escrita, não oferece criar nem transições', async () => {
    prescricoes = [{ ...BASE, id: 'p-ativa', situacao: 'ativa' }, { ...BASE, id: 'p-r', situacao: 'rascunho' }]
    montar(['prescricoes:ler', 'medicamentos:ler'])
    expect(await screen.findByRole('region', { name: 'Ativas' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Nova prescrição' })).toBeNull()
    for (const nome of ['Ativar', 'Suspender', 'Encerrar', 'Substituir']) {
      expect(screen.queryByRole('button', { name: nome })).toBeNull()
    }
    expect(screen.queryByRole('region', { name: 'Doses de hoje' })).toBeNull()
    expect(mockGet).not.toHaveBeenCalledWith('/doses-previstas/', expect.anything())
  })

  it('em /medicacao pede o residente antes de listar', async () => {
    const user = userEvent.setup()
    montar(TODAS, '/medicacao')
    expect(await screen.findByText('Escolha um residente')).toBeInTheDocument()
    await user.selectOptions(await screen.findByLabelText('Residente'), 'res-1')
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/prescricoes/', { params: { residente_id: 'res-1', limit: 500 } }))
  })
})

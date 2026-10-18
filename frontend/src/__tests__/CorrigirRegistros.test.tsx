import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { MeuPlantao } from '../pages/MeuPlantao'
import { api } from '../services/api'
import { contextApi } from '../services/context'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
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
const mockPost = vi.mocked(api.post)
const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

const HA_10_MIN = new Date(Date.now() - 10 * 60_000).toISOString()
const REALIZADO = {
  id: 'e1', residente_id: 'r1', ocorrencia_id: 'o1', resultado: 'executada', ocorrido_em: HA_10_MIN,
  descricao: 'Banho assistido', executor_nome: 'Ana Cuidadora', estornado_em: null, substitui_id: null,
}
const JA_CORRIGIDO = {
  id: 'e0', residente_id: 'r1', ocorrencia_id: 'o0', resultado: 'executada', ocorrido_em: HA_10_MIN,
  descricao: 'Hidratação', executor_nome: 'Ana Cuidadora', estornado_em: HA_10_MIN, motivo_estorno: 'Residente errado',
}

function responde(registros: unknown[]) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/execucoes-cuidado/') return Promise.resolve({ data: registros } as any)
    if (url === '/residentes/') return Promise.resolve({ data: [{ id: 'r1', nome: 'Maria Souza' }] } as any)
    if (url === '/meu-plantao/') return Promise.resolve({ data: { gerado_em: new Date().toISOString(), areas: [] } } as any)
    return Promise.resolve({ data: [] } as any)
  })
  mockPost.mockResolvedValue({ data: {} } as any)
}

function renderCom(permissoes: string[]) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes } } as any)
  return render(<AuthProvider><MemoryRouter><PermissoesProvider><MeuPlantao /></PermissoesProvider></MemoryRouter></AuthProvider>)
}

const CUIDADOR = ['plantao:ler', 'execucoes:ler', 'execucoes:criar']
const ENFERMAGEM = [...CUIDADOR, 'execucoes:corrigir']
const dialogo = () => within(screen.getByRole('dialog'))

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
})

describe('UX-01F — corrigir registros (decisão A)', () => {
  it('o cuidador registra, mas não vê a correção', async () => {
    responde([REALIZADO])
    renderCom(CUIDADOR)
    await waitFor(() => expect(mockPermissoes).toHaveBeenCalled())
    await screen.findByRole('heading', { level: 1 })
    expect(screen.queryByRole('button', { name: 'Corrigir registros' })).toBeNull()
  })

  it('lista as últimas 24 h com o que foi feito e por quem; corrigido fica visível, sem novo Corrigir', async () => {
    const user = userEvent.setup()
    responde([REALIZADO, JA_CORRIGIDO])
    renderCom(ENFERMAGEM)
    await user.click(await screen.findByRole('button', { name: 'Corrigir registros' }))

    expect(await dialogo().findByText(/Banho assistido/)).toBeTruthy()
    expect(dialogo().getAllByText('Registrado por Ana Cuidadora')).toHaveLength(2)
    expect(dialogo().getByText('Corrigido: Residente errado')).toBeTruthy()
    expect(dialogo().getAllByRole('button', { name: /^Corrigir — / })).toHaveLength(1)
    const chamada = mockGet.mock.calls.find(c => c[0] === '/execucoes-cuidado/')
    const desde = new Date((chamada?.[1] as any).params.a_partir_de).getTime()
    expect(Math.abs(Date.now() - 24 * 3600_000 - desde)).toBeLessThan(60_000)
  })

  it('troca o resultado mantendo o horário do fato e exige os dois motivos', async () => {
    const user = userEvent.setup()
    responde([REALIZADO])
    renderCom(ENFERMAGEM)
    await user.click(await screen.findByRole('button', { name: 'Corrigir registros' }))
    await user.click(await dialogo().findByRole('button', { name: /^Corrigir — Maria Souza, Banho assistido/ }))

    await user.click(dialogo().getByRole('button', { name: 'Não realizado' }))
    await user.click(dialogo().getByRole('button', { name: 'Salvar correção' }))
    expect(dialogo().getByRole('alert').textContent).toBe('Informe o motivo do resultado.')
    await user.type(dialogo().getByLabelText(/Motivo do resultado/), 'Residente dormindo')
    await user.click(dialogo().getByRole('button', { name: 'Salvar correção' }))
    expect(dialogo().getByRole('alert').textContent).toBe('Informe o motivo da correção.')
    expect(mockPost).not.toHaveBeenCalled()

    await user.type(dialogo().getByLabelText(/Motivo da correção/), 'Marcado como feito por engano')
    await user.click(dialogo().getByRole('button', { name: 'Salvar correção' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/execucoes-cuidado/e1/estornar', {
      motivo: 'Marcado como feito por engano',
      substituto: { ocorrencia_id: 'o1', resultado: 'omitida', ocorrido_em: HA_10_MIN, justificativa: 'Residente dormindo' },
    }))
    expect(await screen.findByText('Registro corrigido.')).toBeTruthy()
  })

  it('anular estorna sem substituto e recarrega a fila', async () => {
    const user = userEvent.setup()
    responde([REALIZADO])
    renderCom(ENFERMAGEM)
    await user.click(await screen.findByRole('button', { name: 'Corrigir registros' }))
    await user.click(await dialogo().findByRole('button', { name: /^Corrigir — / }))
    await user.click(dialogo().getByRole('button', { name: 'Anular registro' }))
    await user.type(dialogo().getByLabelText(/Motivo da correção/), 'Residente errado')
    const filasAntes = mockGet.mock.calls.filter(c => c[0] === '/plantao/').length
    await user.click(dialogo().getByRole('button', { name: 'Salvar correção' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/execucoes-cuidado/e1/estornar', { motivo: 'Residente errado' }))
    expect(await screen.findByText('Registro anulado. O cuidado voltou para a fila.')).toBeTruthy()
    await waitFor(() => expect(mockGet.mock.calls.filter(c => c[0] === '/plantao/').length).toBeGreaterThan(filasAntes))
  })

  it('falha do servidor mantém o formulário com a mensagem', async () => {
    const user = userEvent.setup()
    responde([REALIZADO])
    mockPost.mockRejectedValueOnce({ response: { status: 409, data: { detail: 'Execucao ja estornada' } } })
    renderCom(ENFERMAGEM)
    await user.click(await screen.findByRole('button', { name: 'Corrigir registros' }))
    await user.click(await dialogo().findByRole('button', { name: /^Corrigir — / }))
    await user.click(dialogo().getByRole('button', { name: 'Realizado' }))
    await user.type(dialogo().getByLabelText(/Motivo da correção/), 'x')
    await user.click(dialogo().getByRole('button', { name: 'Salvar correção' }))
    expect(await dialogo().findByRole('alert')).toBeTruthy()
    expect(dialogo().getByRole('button', { name: 'Salvar correção' })).toBeTruthy()
  })
})

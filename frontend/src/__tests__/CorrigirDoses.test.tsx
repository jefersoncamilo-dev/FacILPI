import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
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
const DADA = {
  id: 'a1', residente_id: 'r1', dose_prevista_id: 'd1', resultado: 'administrada', ocorrido_em: HA_10_MIN,
  quantidade_realizada: '1.0000', descricao: 'Losartana 50 mg', executor_nome: 'Bia Enfermeira', estornado_em: null, substitui_id: null,
}
const JA_ESTORNADA = {
  id: 'a0', residente_id: 'r1', dose_prevista_id: 'd0', resultado: 'administrada', ocorrido_em: HA_10_MIN,
  descricao: 'Dipirona', executor_nome: 'Bia Enfermeira', estornado_em: HA_10_MIN, motivo_estorno: 'Residente errado',
}

function responde(registros: unknown[]) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/administracoes/') return Promise.resolve({ data: registros } as any)
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

// Cuidador, médico e ilpi_admin não têm `administracoes:corrigir` (D2 = sim).
const SEM_CORRECAO = ['plantao:ler', 'administracoes:ler', 'administracoes:criar', 'execucoes:ler', 'execucoes:corrigir']
const ENFERMAGEM = [...SEM_CORRECAO, 'administracoes:corrigir']
const dialogo = () => within(screen.getByRole('dialog'))

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
})

describe('#11 — corrigir doses (D2 = sim)', () => {
  it('sem administracoes:corrigir, não há "Corrigir doses"', async () => {
    responde([DADA])
    renderCom(SEM_CORRECAO)
    await waitFor(() => expect(mockPermissoes).toHaveBeenCalled())
    await screen.findByRole('button', { name: 'Corrigir registros' })
    expect(screen.queryByRole('button', { name: 'Corrigir doses' })).toBeNull()
  })

  it('lista 24 h com remédio e quem registrou; estornada fica visível, sem novo Corrigir', async () => {
    const user = userEvent.setup()
    responde([DADA, JA_ESTORNADA])
    renderCom(ENFERMAGEM)
    await user.click(await screen.findByRole('button', { name: 'Corrigir doses' }))
    expect(await dialogo().findByText(/Losartana 50 mg/)).toBeTruthy()
    expect(dialogo().getAllByText(/por Bia Enfermeira/).length).toBe(2)
    expect(dialogo().getByText('Corrigido: Residente errado')).toBeTruthy()
    expect(dialogo().getAllByRole('button', { name: /^Corrigir —/ }).length).toBe(1)
    const params = mockGet.mock.calls.find(c => c[0] === '/administracoes/')![1] as any
    expect(Date.now() - Date.parse(params.params.a_partir_de)).toBeGreaterThanOrEqual(24 * 60 * 60 * 1000 - 5000)
  })

  it('motivo obrigatório; substituto vai no mesmo horário', async () => {
    const user = userEvent.setup()
    responde([DADA])
    renderCom(ENFERMAGEM)
    await user.click(await screen.findByRole('button', { name: 'Corrigir doses' }))
    await user.click(await dialogo().findByRole('button', { name: /^Corrigir —/ }))
    await user.click(dialogo().getByRole('button', { name: 'Recusada' }))
    await user.type(dialogo().getByLabelText(/Motivo do resultado/), 'Recusou')
    await user.click(dialogo().getByRole('button', { name: 'Salvar correção' }))
    expect(dialogo().getByText('Informe o motivo da correção.')).toBeTruthy()
    expect(mockPost).not.toHaveBeenCalled()
    await user.type(dialogo().getByLabelText(/Motivo da correção/), 'Registrado errado')
    await user.click(dialogo().getByRole('button', { name: 'Salvar correção' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/administracoes/a1/estornar', {
      motivo: 'Registrado errado',
      substituto: { resultado: 'recusada', ocorrido_em: HA_10_MIN, justificativa: 'Recusou' },
    }))
  })

  it('anular estorna sem substituto', async () => {
    const user = userEvent.setup()
    responde([DADA])
    renderCom(ENFERMAGEM)
    await user.click(await screen.findByRole('button', { name: 'Corrigir doses' }))
    await user.click(await dialogo().findByRole('button', { name: /^Corrigir —/ }))
    await user.click(dialogo().getByRole('button', { name: 'Anular registro' }))
    await user.type(dialogo().getByLabelText(/Motivo da correção/), 'Dose não existiu')
    await user.click(dialogo().getByRole('button', { name: 'Salvar correção' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/administracoes/a1/estornar', { motivo: 'Dose não existiu' }))
  })
})

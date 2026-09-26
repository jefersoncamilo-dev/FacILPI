import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { MeuPlantao } from '../pages/MeuPlantao'
import { SinaisVitais } from '../pages/SinaisVitais'
import { Intercorrencias } from '../pages/Intercorrencias'
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

const HORA = 60 * 60 * 1000
const ATRASADO = { origem: 'cuidado', registro_id: 'oc-1', residente_id: 'r1', descricao: 'Banho assistido', previsto_em: new Date(Date.now() - HORA).toISOString(), prioridade: 'alta' }
const PROXIMO = { origem: 'medicacao', registro_id: 'dose-1', residente_id: 'r1', descricao: 'Dose de losartana', previsto_em: new Date(Date.now() + HORA).toISOString(), prioridade: null }
const SEM_HORA = { origem: 'intercorrencia', registro_id: 'int-1', residente_id: 'r1', descricao: 'Queda sem lesão', previsto_em: null, prioridade: null }

function responde(plantao: unknown[] = [ATRASADO, PROXIMO, SEM_HORA]) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/plantao/') return Promise.resolve({ data: plantao } as any)
    if (url === '/residentes/') return Promise.resolve({ data: [{ id: 'r1', nome: 'Antônia Ribeiro' }] } as any)
    if (url === '/sinais-vitais/' || url === '/intercorrencias/') return Promise.resolve({ data: [] } as any)
    throw new Error(`URL inesperada: ${url}`)
  })
}

function renderCom(tela: JSX.Element, permissoes: string[]) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes } } as any)
  return render(<AuthProvider><MemoryRouter><PermissoesProvider>{tela}</PermissoesProvider></MemoryRouter></AuthProvider>)
}

const TUDO = ['plantao:ler', 'execucoes:criar', 'administracoes:criar', 'intercorrencias:atualizar']

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  responde()
})

describe('UX-05 — Meu Plantão', () => {
  it('agrupa pela urgência: atrasadas, próximas e sem horário', async () => {
    renderCom(<MeuPlantao />, TUDO)
    const atrasadas = await screen.findByRole('region', { name: 'Atrasadas' })
    expect(within(atrasadas).getByText('Banho assistido')).toBeTruthy()
    expect(within(screen.getByRole('region', { name: 'Próximas' })).getByText('Dose de losartana')).toBeTruthy()
    expect(within(screen.getByRole('region', { name: 'Sem horário' })).getByText('Queda sem lesão')).toBeTruthy()
  })

  it('sem permissão da ação, a pendência continua visível mas sem botão', async () => {
    renderCom(<MeuPlantao />, ['plantao:ler', 'execucoes:criar'])
    await screen.findByText('Queda sem lesão')
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Encerrar' })).toBeNull())
    expect(screen.queryByRole('button', { name: 'Registrar administração' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Registrar execução' })).toBeTruthy()
  })

  it('depois de registrar, mostra o sucesso e recarrega a projeção', async () => {
    const user = userEvent.setup()
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderCom(<MeuPlantao />, TUDO)
    await user.click(await screen.findByRole('button', { name: 'Registrar execução' }))
    responde([PROXIMO, SEM_HORA])
    await user.click(screen.getByRole('button', { name: 'Confirmar' }))
    expect(await screen.findByText('Execução registrada.')).toBeTruthy()
    await waitFor(() => expect(screen.queryByText('Banho assistido')).toBeNull())
  })
})

describe('UX-05 — registro por permissão', () => {
  it('Sinais Vitais: "+ Registrar aferição" só com sinais_vitais:criar', async () => {
    renderCom(<SinaisVitais />, ['sinais_vitais:ler'])
    await waitFor(() => expect(mockPermissoes).toHaveBeenCalled())
    await waitFor(() => expect(screen.queryByText('Carregando sinais vitais…')).toBeNull())
    expect(screen.queryByRole('button', { name: '+ Registrar aferição' })).toBeNull()
  })

  it('Intercorrências: "+ Registrar intercorrência" só com intercorrencias:criar', async () => {
    renderCom(<Intercorrencias />, ['intercorrencias:ler', 'intercorrencias:criar'])
    expect(await screen.findByRole('button', { name: '+ Registrar intercorrência' })).toBeTruthy()
  })
})

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

const em = (min: number) => new Date(Date.now() + min * 60_000).toISOString()
const banho = (id: string, residente: string, min: number) =>
  ({ origem: 'cuidado', registro_id: id, residente_id: residente, descricao: 'Banho assistido', previsto_em: em(min), prioridade: null, local: null })
const FILA = [banho('b1', 'r1', 30), banho('b2', 'r2', 40), banho('b3', 'r3', 50)]
const NOMES = [{ id: 'r1', nome: 'Maria Souza' }, { id: 'r2', nome: 'João Lima' }, { id: 'r3', nome: 'Ana Reis' }]

let fila: unknown[] = []
function responde(itens: unknown[]) {
  fila = itens
  mockGet.mockImplementation((url: string) => {
    if (url === '/plantao/') return Promise.resolve({ data: fila } as any)
    if (url === '/residentes/') return Promise.resolve({ data: NOMES } as any)
    if (url === '/meu-plantao/') return Promise.resolve({ data: { gerado_em: em(0), areas: [] } } as any)
    return Promise.resolve({ data: [] } as any)
  })
}

async function abrirLote(user: ReturnType<typeof userEvent.setup>) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes: ['plantao:ler', 'execucoes:criar'] } } as any)
  render(<AuthProvider><MemoryRouter><PermissoesProvider><MeuPlantao /></PermissoesProvider></MemoryRouter></AuthProvider>)
  await user.click(await screen.findByRole('button', { name: 'Por cuidado' }))
  await user.click(await screen.findByRole('button', { name: 'Selecionar' }))
  await user.click(screen.getByRole('button', { name: 'Marcar todos (3)' }))
  await user.click(screen.getByRole('button', { name: 'Registrar em lote (3)' }))
  return within(await screen.findByRole('dialog', { name: 'Registrar 3 cuidados' }))
}

const postsDeExecucao = () => mockPost.mock.calls.filter(c => c[0] === '/execucoes-cuidado/').map(c => c[1] as any)

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
})

describe('UX-01C — registro em lote, persistência individual', () => {
  it('todos como Realizado: uma execução por ocorrência, sucesso e fim da seleção', async () => {
    const user = userEvent.setup()
    responde(FILA)
    mockPost.mockResolvedValue({ data: {} } as any)
    const dialogo = await abrirLote(user)
    responde([])

    await user.click(dialogo.getByRole('button', { name: 'Registrar 3 cuidados' }))

    expect(await screen.findByText('3 registros salvos.')).toBeTruthy()
    const posts = postsDeExecucao()
    expect(posts.map(p => p.ocorrencia_id)).toEqual(['b1', 'b2', 'b3'])
    expect(posts.every(p => p.resultado === 'executada' && !('justificativa' in p) && p.ocorrido_em)).toBe(true)
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('region', { name: 'Seleção' })).toBeNull()
  })

  it('exceção individual exige motivo e só ela leva justificativa', async () => {
    const user = userEvent.setup()
    responde(FILA)
    mockPost.mockResolvedValue({ data: {} } as any)
    const dialogo = await abrirLote(user)

    await user.click(dialogo.getByRole('button', { name: 'Exceção — João Lima, Banho assistido' }))
    await user.click(within(dialogo.getByRole('group', { name: 'Resultado — João Lima, Banho assistido' })).getByRole('button', { name: 'Não realizado' }))
    await user.click(dialogo.getByRole('button', { name: 'Registrar 3 cuidados (1 exceção)' }))
    expect(dialogo.getByText('Informe o motivo da exceção.')).toBeTruthy()
    expect(postsDeExecucao()).toHaveLength(0)

    await user.type(dialogo.getByLabelText('Motivo — João Lima, Banho assistido'), 'Residente ausente')
    responde([])
    await user.click(dialogo.getByRole('button', { name: 'Registrar 3 cuidados (1 exceção)' }))

    await screen.findByText('3 registros salvos.')
    const porId = Object.fromEntries(postsDeExecucao().map(p => [p.ocorrencia_id, p]))
    expect(porId.b2).toMatchObject({ resultado: 'omitida', justificativa: 'Residente ausente' })
    expect(porId.b1.resultado).toBe('executada')
    expect('justificativa' in porId.b1).toBe(false)
  })

  it('falha parcial: salvos saem, o que falhou fica no diálogo e pode ser reenviado', async () => {
    const user = userEvent.setup()
    responde(FILA)
    mockPost
      .mockResolvedValueOnce({ data: {} } as any)
      .mockRejectedValueOnce({ response: { status: 409, data: { detail: { message: 'Ocorrencia ja possui execucao vigente' } } } })
      .mockResolvedValueOnce({ data: {} } as any)
    const dialogo = await abrirLote(user)
    responde([FILA[1]])

    await user.click(dialogo.getByRole('button', { name: 'Registrar 3 cuidados' }))

    expect(await dialogo.findByText('Ocorrencia ja possui execucao vigente')).toBeTruthy()
    expect(dialogo.getByText('2 salvos. 1 não foram salvos — confira e tente de novo.')).toBeTruthy()
    expect(screen.getByText('2 registros salvos.')).toBeTruthy()
    expect(dialogo.queryByText('Maria Souza')).toBeNull()
    expect(dialogo.getByText('João Lima')).toBeTruthy()

    mockPost.mockResolvedValueOnce({ data: {} } as any)
    responde([])
    await user.click(dialogo.getByRole('button', { name: 'Registrar 1 cuidado' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(postsDeExecucao().map(p => p.ocorrencia_id)).toEqual(['b1', 'b2', 'b3', 'b2'])
  })
})

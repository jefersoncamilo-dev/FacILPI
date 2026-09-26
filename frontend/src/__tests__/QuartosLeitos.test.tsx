import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { QuartosLeitos } from '../pages/QuartosLeitos'
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
const mockPut = vi.mocked(api.put)
const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

const leito = (p: Record<string, unknown>) => ({ unidade: null, capacidade: 1, acessibilidade: null, residente_atual_id: null, situacao: 'livre', data_ocupacao: null, ...p })
const LEITOS = [
  leito({ id: 'l1', quarto: '101', leito: 'A', residente_atual_id: 'r1', data_ocupacao: '2026-09-01T10:00:00Z' }),
  leito({ id: 'l2', quarto: '101', leito: 'B' }),
  leito({ id: 'l3', quarto: '102', leito: 'A', situacao: 'manutencao' }),
  leito({ id: 'l4', quarto: '102', leito: 'B', situacao: 'inativo' }),
]
const RESIDENTES = [{ id: 'r1', nome: 'Antônia Ribeiro' }, { id: 'r2', nome: 'Benedito Carvalho' }]
const AUSENCIAS = [
  { id: 'a1', residente_id: 'r1', quarto_leito_id: 'l1', tipo: 'hospitalizacao', data_inicio: '2026-09-24T10:00:00Z', data_fim: null, motivo: 'Internação', observacoes: null },
]
const TUDO = ['quartos_leitos:ler', 'quartos_leitos:criar', 'quartos_leitos:atualizar', 'quartos_leitos:inativar', 'ausencias:ler', 'ausencias:criar', 'ausencias:atualizar', 'residentes:ler']

function responde({ leitos = LEITOS as unknown, ausencias = AUSENCIAS as unknown }: { leitos?: unknown; ausencias?: unknown } = {}) {
  mockGet.mockImplementation((url: string) => {
    const de = (x: unknown) => (x instanceof Error || (x as any)?.response ? Promise.reject(x) : Promise.resolve({ data: x } as any))
    if (url === '/quartos_leitos/') return de(leitos)
    if (url === '/ausencias/') return de(ausencias)
    if (url === '/residentes/') return de(RESIDENTES)
    if (url === '/ocupacao_historico/') return de([])
    throw new Error(`URL inesperada: ${url}`)
  })
}

function renderTela(permissoes = TUDO) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes } } as any)
  return render(<AuthProvider><MemoryRouter><PermissoesProvider><QuartosLeitos /></PermissoesProvider></MemoryRouter></AuthProvider>)
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  responde()
})

describe('Quartos e leitos — visão', () => {
  it('resumo segue a regra dos leitos: ocupado = com residente; inativo fora dos ativos', async () => {
    renderTela()
    const resumo = within(await screen.findByRole('region', { name: 'Resumo da ocupação' }))
    await waitFor(() => expect(resumo.getByText('1/3')).toBeTruthy())
    expect(resumo.getByText('Livres').nextElementSibling?.textContent).toBe('1')
    expect(resumo.getByText('Indisponíveis').nextElementSibling?.textContent).toBe('1')
    expect(resumo.getByText('Ausentes agora').nextElementSibling?.textContent).toBe('1')
  })

  it('agrupa por quarto e mostra ocupante e ausência sem inventar regra', async () => {
    renderTela()
    const quarto101 = within(await screen.findByRole('region', { name: 'Quarto 101' }))
    const ocupado = quarto101.getByText('Leito A').closest('button')!
    expect(within(ocupado).getByText('Antônia Ribeiro')).toBeTruthy()
    expect(within(ocupado).getByText(/Hospitalização desde/)).toBeTruthy()
  })

  it('403 e falha de consulta não viram "nenhum leito"', async () => {
    responde({ leitos: { response: { status: 403, data: { detail: 'x' } } } })
    const sem = renderTela()
    expect(await screen.findByText('Sem acesso a quartos e leitos')).toBeTruthy()
    sem.unmount()
    responde({ leitos: new Error('rede') })
    renderTela()
    expect(await screen.findByText('Não foi possível carregar os leitos')).toBeTruthy()
    expect(screen.queryByText('Nenhum leito cadastrado')).toBeNull()
  })
})

describe('Quartos e leitos — ações por estado', () => {
  it('leito livre: aloca só residente sem leito', async () => {
    const user = userEvent.setup()
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderTela()
    await user.click((await screen.findByRole('region', { name: 'Quarto 101' })).querySelectorAll('button')[1] as HTMLElement)
    const dialog = within(await screen.findByRole('dialog'))
    const opcoes = within(dialog.getByLabelText('Alocar residente')).getAllByRole('option').map(o => o.textContent)
    expect(opcoes).toContain('Benedito Carvalho')
    expect(opcoes).not.toContain('Antônia Ribeiro')
    await user.selectOptions(dialog.getByLabelText('Alocar residente'), 'r2')
    await user.click(dialog.getByRole('button', { name: /Alocar/ }))
    expect(mockPost).toHaveBeenCalledWith('/quartos_leitos/l2/alocar', { residente_id: 'r2' })
    expect(await screen.findByText(/Benedito Carvalho alocado\(a\)/)).toBeTruthy()
  })

  it('leito ocupado: transfere para leito livre e não oferece mudança de situação nem inativação', async () => {
    const user = userEvent.setup()
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderTela()
    await user.click((await screen.findByRole('region', { name: 'Quarto 101' })).querySelectorAll('button')[0] as HTMLElement)
    const dialog = within(await screen.findByRole('dialog'))
    expect(dialog.queryByLabelText('Situação do leito vazio')).toBeNull()
    expect(dialog.queryByRole('button', { name: 'Inativar leito' })).toBeNull()
    expect(dialog.getByText('O leito continua ocupado pelo residente durante a ausência.')).toBeTruthy()
    const destinos = within(dialog.getByLabelText('Transferir para')).getAllByRole('option').map(o => o.textContent)
    expect(destinos.some(t => t?.includes('Quarto 101 · Leito B'))).toBe(true)
    expect(destinos.some(t => t?.includes('Quarto 102'))).toBe(false)
    await user.selectOptions(dialog.getByLabelText('Transferir para'), 'l2')
    await user.click(dialog.getByRole('button', { name: /Transferir/ }))
    expect(mockPost).toHaveBeenCalledWith('/quartos_leitos/transferencia', { residente_id: 'r1', novo_leito_id: 'l2' })
  })

  it('leito vazio muda de situação pelo PUT; sem permissão de atualizar, nenhuma ação', async () => {
    const user = userEvent.setup()
    mockPut.mockResolvedValueOnce({ data: {} } as any)
    const gestao = renderTela()
    await user.click((await screen.findByRole('region', { name: 'Quarto 102' })).querySelectorAll('button')[0] as HTMLElement)
    await user.selectOptions(within(await screen.findByRole('dialog')).getByLabelText('Situação do leito vazio'), 'livre')
    expect(mockPut).toHaveBeenCalledWith('/quartos_leitos/l3', { situacao: 'livre' })
    gestao.unmount()

    renderTela(['quartos_leitos:ler', 'residentes:ler'])
    await user.click((await screen.findByRole('region', { name: 'Quarto 101' })).querySelectorAll('button')[1] as HTMLElement)
    const dialog = within(await screen.findByRole('dialog'))
    await waitFor(() => expect(dialog.queryByLabelText('Alocar residente')).toBeNull())
    expect(dialog.queryByRole('button', { name: 'Inativar leito' })).toBeNull()
  })

  it('409 do backend é mostrado com a mensagem dele', async () => {
    const user = userEvent.setup()
    mockPost.mockRejectedValueOnce({ response: { status: 409, data: { detail: 'Residente já possui leito ocupado' } } })
    renderTela()
    await user.click((await screen.findByRole('region', { name: 'Quarto 101' })).querySelectorAll('button')[1] as HTMLElement)
    const dialog = within(await screen.findByRole('dialog'))
    await user.selectOptions(dialog.getByLabelText('Alocar residente'), 'r2')
    await user.click(dialog.getByRole('button', { name: /Alocar/ }))
    expect(await screen.findByText('Residente já possui leito ocupado')).toBeTruthy()
  })
})

describe('Quartos e leitos — ausências', () => {
  it('registra retorno de ausência ativa', async () => {
    const user = userEvent.setup()
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderTela()
    await user.click(await screen.findByRole('tab', { name: 'Ausências' }))
    const ativas = within(screen.getByRole('region', { name: 'Ausências ativas' }))
    await user.click(ativas.getByRole('button', { name: /Registrar retorno/ }))
    expect(mockPost).toHaveBeenCalledWith('/ausencias/a1/encerrar', {})
  })

  it('nova ausência só lista residentes sem ausência ativa e vincula o leito atual', async () => {
    const user = userEvent.setup()
    responde({ ausencias: [] })
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    renderTela()
    await user.click(await screen.findByRole('button', { name: /Registrar ausência/ }))
    const dialog = within(await screen.findByRole('dialog'))
    await user.selectOptions(dialog.getByLabelText('Residente'), 'r1')
    await user.type(dialog.getByLabelText('Motivo'), 'Consulta externa')
    await user.selectOptions(dialog.getByLabelText('Tipo'), 'saida_temporaria')
    await user.click(dialog.getByRole('button', { name: 'Registrar ausência' }))
    expect(mockPost).toHaveBeenCalledWith('/ausencias/', {
      residente_id: 'r1', tipo: 'saida_temporaria', motivo: 'Consulta externa', quarto_leito_id: 'l1',
    })
  })
})

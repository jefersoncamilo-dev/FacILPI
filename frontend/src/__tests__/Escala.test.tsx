import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { PermissoesProvider } from '../context/PermissoesContext'
import { Escala } from '../pages/Escala'
import { MeuTurno } from '../components/plantao/MeuTurno'
import { api } from '../services/api'
import { contextApi } from '../services/context'
import type { Area, EscalaAgora, Plantao, PlantaoAtual, Turno } from '../services/escala'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() } }
})

vi.mock('../services/context', () => ({
  contextApi: { permissoesDaSessao: vi.fn() },
  resolveContextLabels: vi.fn(async (ctx: any) => ctx),
  logoutServidor: vi.fn(async () => ({ data: {} })),
}))

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)
const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

const ALA_B: Area = {
  id: 'area-b', nome: 'Ala B', tipo: 'ala', descricao: null, situacao: 'ativa',
  leitos: [{ vinculo_id: 'v1', quarto_leito_id: 'l1', unidade: 'Bloco 1', quarto: '12', leito: 'A', ocupado: true, desde: '2026-09-28T10:00:00Z' }],
}
const DIURNO: Turno = { id: 't1', nome: 'Diurno', hora_inicio: '07:00', hora_fim: '19:00', situacao: 'ativo' }
const RESP = {
  id: 'r1', plantao_id: 'p1', funcionario_id: 'f1', funcionario_nome: 'Ana Sintetica', area_id: 'area-b', area_nome: 'Ala B',
  inicio_em: '2026-09-28T10:00:00Z', fim_em: null, motivo_fim: null,
}
const PLANTAO: Plantao = {
  id: 'p1', funcionario_id: 'f1', funcionario_nome: 'Ana Sintetica', turno_id: 't1', turno_nome: 'Diurno',
  inicio_em: '2026-09-28T10:00:00Z', fim_em: null, situacao: 'em_andamento', responsabilidades: [RESP],
}
const JULIANA: Plantao = { ...PLANTAO, id: 'p2', funcionario_id: 'f2', funcionario_nome: 'Juliana Sintetica', responsabilidades: [] }

function comPermissoes(permissoes: string[]) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', ilpi_id: 'ilpi1', permissoes } } as any)
}

function responder(rotas: Record<string, unknown>) {
  mockGet.mockImplementation((url: string) => {
    if (url in rotas) return Promise.resolve({ data: rotas[url] } as any)
    return Promise.resolve({ data: [] } as any)
  })
}

function renderEscala() {
  return render(<MemoryRouter><PermissoesProvider><Escala /></PermissoesProvider></MemoryRouter>)
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('Escala (#120)', () => {
  it('Agora mostra quem responde por cada área e quem está em plantão sem área', async () => {
    comPermissoes(['escala:ler'])
    const agora: EscalaAgora = {
      gerado_em: '2026-09-28T12:00:00Z',
      areas: [{ area: ALA_B, responsaveis: [RESP], residentes: 1 },
              { area: { ...ALA_B, id: 'area-c', nome: 'Ala C', leitos: [] }, responsaveis: [], residentes: null }],
      plantoes_sem_area: [JULIANA],
    }
    responder({ '/escala/agora': agora })
    renderEscala()
    const alaB = await screen.findByRole('region', { name: 'Área Ala B' })
    expect(within(alaB).getByText('Ana Sintetica')).toBeTruthy()
    expect(within(alaB).getByText(/1 leito · 1 residente/)).toBeTruthy()
    const alaC = screen.getByRole('region', { name: 'Área Ala C' })
    expect(within(alaC).getByText('Ninguém responde por esta área agora.')).toBeTruthy()
    // Sem residentes:ler, a contagem de residentes não aparece.
    expect(within(alaC).queryByText(/residente/)).toBeNull()
    expect(within(screen.getByRole('region', { name: 'Em plantão sem área' })).getByText(/Juliana Sintetica/)).toBeTruthy()
    // Só leitura: sem escala:gerenciar não há atribuição.
    expect(screen.queryByRole('button', { name: 'Atribuir' })).toBeNull()
  })

  it('gestor atribui a área a quem está em plantão, no lugar de outra pessoa', async () => {
    comPermissoes(['escala:ler', 'escala:gerenciar'])
    responder({ '/escala/agora': { gerado_em: '2026-09-28T12:00:00Z', areas: [{ area: ALA_B, responsaveis: [RESP], residentes: 1 }], plantoes_sem_area: [JULIANA] } })
    mockPost.mockResolvedValue({ data: [] } as any)
    renderEscala()
    const alaB = await screen.findByRole('region', { name: 'Área Ala B' })
    await userEvent.selectOptions(within(alaB).getByLabelText('Profissional que passa a responder'), 'p2')
    await userEvent.selectOptions(within(alaB).getByLabelText('Profissional que deixa a área'), 'f1')
    await userEvent.click(within(alaB).getByRole('button', { name: 'Atribuir' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/escala/responsabilidades/transferir', {
      area_id: 'area-b', para_plantao_id: 'p2', de_funcionario_id: 'f1',
    }))
  })

  it('Áreas: gestor cria área; leitura não oferece gestão', async () => {
    comPermissoes(['escala:ler', 'escala:gerenciar'])
    responder({ '/escala/agora': { gerado_em: '', areas: [], plantoes_sem_area: [] }, '/escala/areas': [ALA_B] })
    mockPost.mockResolvedValue({ data: ALA_B } as any)
    renderEscala()
    await userEvent.click(await screen.findByRole('tab', { name: 'Áreas' }))
    const ala = await screen.findByRole('region', { name: 'Área Ala B' })
    expect(within(ala).getByText('Bloco 1 · Quarto 12 · Leito A')).toBeTruthy()
    const form = screen.getByRole('form', { name: 'Nova área' })
    await userEvent.type(within(form).getByPlaceholderText('Ex.: Ala B'), 'Ala C')
    await userEvent.click(within(form).getByRole('button', { name: /Criar área/ }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/escala/areas', { nome: 'Ala C', tipo: 'ala' }))
  })

  it('Turnos: sem escala:gerenciar só lista', async () => {
    comPermissoes(['escala:ler'])
    responder({ '/escala/agora': { gerado_em: '', areas: [], plantoes_sem_area: [] }, '/escala/turnos': [DIURNO] })
    renderEscala()
    await userEvent.click(await screen.findByRole('tab', { name: 'Turnos' }))
    expect(await screen.findByText('Diurno')).toBeTruthy()
    expect(screen.getByText(/07:00–19:00/)).toBeTruthy()
    expect(screen.queryByRole('form', { name: 'Novo turno' })).toBeNull()
  })
})

describe('Meu turno no Meu Plantão (#120)', () => {
  it('sem plantao:registrar e sem plantão, o cartão não aparece', async () => {
    const atual: PlantaoAtual = { pode_registrar: false, funcionario_id: 'f9', plantao: null }
    responder({ '/plantoes/atual': atual })
    const { container } = render(<MeuTurno />)
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/plantoes/atual'))
    expect(container.textContent).toBe('')
  })

  it('inicia o próprio plantão escolhendo área e turno', async () => {
    let atual: PlantaoAtual = { pode_registrar: true, funcionario_id: 'f1', plantao: null }
    mockGet.mockImplementation((url: string) => {
      if (url === '/plantoes/atual') return Promise.resolve({ data: atual } as any)
      if (url === '/escala/areas') return Promise.resolve({ data: [ALA_B] } as any)
      if (url === '/escala/turnos') return Promise.resolve({ data: [DIURNO] } as any)
      return Promise.resolve({ data: [] } as any)
    })
    mockPost.mockImplementation(async () => { atual = { ...atual, plantao: PLANTAO }; return { data: PLANTAO } as any })
    render(<MeuTurno />)
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Ala B' }))
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Turno' }), 't1')
    await userEvent.click(screen.getByRole('button', { name: /Iniciar plantão/ }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/plantoes/iniciar', { area_ids: ['area-b'], turno_id: 't1' }))
    expect(await screen.findByText('Plantão em andamento · Diurno')).toBeTruthy()
    expect(screen.getByText('Responsável por: Ala B')).toBeTruthy()
  })

  it('encerra o próprio plantão', async () => {
    let atual: PlantaoAtual = { pode_registrar: true, funcionario_id: 'f1', plantao: PLANTAO }
    mockGet.mockImplementation((url: string) => Promise.resolve({ data: url === '/plantoes/atual' ? atual : [] } as any))
    mockPost.mockImplementation(async () => { atual = { ...atual, plantao: null }; return { data: { ...PLANTAO, situacao: 'encerrado' } } as any })
    render(<MeuTurno />)
    await userEvent.click(await screen.findByRole('button', { name: /Encerrar plantão/ }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/plantoes/p1/encerrar', {}))
    expect(await screen.findByText('Você não está em plantão')).toBeTruthy()
  })
})

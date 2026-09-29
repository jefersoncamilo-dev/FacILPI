import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { PermissoesProvider } from '../context/PermissoesContext'
import { Escala } from '../pages/Escala'
import { MeuTurno } from '../components/plantao/MeuTurno'
import { api } from '../services/api'
import { contextApi } from '../services/context'
import type { Escala as EscalaPlanejada, EscalaDia, PlantaoAtual } from '../services/escala'

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

function escala(parcial: Partial<EscalaPlanejada>): EscalaPlanejada {
  return {
    id: 'e1', funcionario_id: 'f1', funcionario_nome: 'Ana Sintetica', turno_id: 't1', turno_nome: 'Diurno',
    area_id: 'area-b', area_nome: 'Ala B', inicio_previsto: '2030-01-15T10:00:00Z', fim_previsto: '2030-01-15T22:00:00Z',
    tipo: 'regular', situacao: 'prevista', motivo: null, substitui_escala_id: null, substituta_id: null,
    substituto_nome: null, plantao_id: null, estado: 'prevista', ...parcial,
  }
}

const DIA: EscalaDia = {
  dia: '2030-01-15', fuso: 'America/Sao_Paulo',
  escalas: [
    escala({ id: 'e1', estado: 'presente', plantao_id: 'p1' }),
    escala({ id: 'e2', funcionario_id: 'f2', funcionario_nome: 'Bruno Sintetico', estado: 'nao_iniciada' }),
    escala({ id: 'e3', funcionario_id: 'f3', funcionario_nome: 'Carla Sintetica', situacao: 'ausente', estado: 'substituida', motivo: 'Atestado', substituto_nome: 'Juliana Sintetica' }),
  ],
  coberturas_sem_escala: [{
    id: 'p9', funcionario_id: 'f9', funcionario_nome: 'Davi Sintetico', turno_id: null, turno_nome: null,
    inicio_em: '2030-01-15T11:00:00Z', fim_em: null, situacao: 'em_andamento', escala_id: null, responsabilidades: [],
  }],
}

function comPermissoes(permissoes: string[]) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', ilpi_id: 'ilpi1', permissoes } } as any)
}

function responder() {
  mockGet.mockImplementation((url: string) => {
    if (url === '/escala/previsto') return Promise.resolve({ data: DIA } as any)
    if (url === '/escala/agora') return Promise.resolve({ data: { gerado_em: '', areas: [], plantoes_sem_area: [] } } as any)
    if (url === '/funcionarios/') {
      return Promise.resolve({ data: [
        { id: 'f2', nome: 'Bruno Sintetico', situacao: 'ativo' }, { id: 'f4', nome: 'Juliana Sintetica', situacao: 'ativo' },
      ] } as any)
    }
    return Promise.resolve({ data: [] } as any)
  })
}

async function abrirDia() {
  render(<MemoryRouter><PermissoesProvider><Escala /></PermissoesProvider></MemoryRouter>)
  await userEvent.click(await screen.findByRole('tab', { name: 'Dia' }))
  return screen.findByRole('list', { name: 'Escala do dia' })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('Escala do dia — previsto × efetivo (#122)', () => {
  it('mostra o estado de cada escala e a cobertura sem escala', async () => {
    comPermissoes(['escala:ler'])
    responder()
    const lista = await abrirDia()
    // Sem dia escolhido, a API decide "hoje" no fuso da ILPI e a tela adota o dia devolvido.
    expect(mockGet).toHaveBeenCalledWith('/escala/previsto', { params: {} })
    expect((screen.getByLabelText('Dia') as HTMLInputElement).value).toBe('2030-01-15')
    expect(within(within(lista).getByRole('region', { name: 'Escala de Ana Sintetica' })).getByText('Presente')).toBeTruthy()
    expect(within(within(lista).getByRole('region', { name: 'Escala de Bruno Sintetico' })).getByText('Não iniciada')).toBeTruthy()
    const carla = within(lista).getByRole('region', { name: 'Escala de Carla Sintetica' })
    expect(within(carla).getByText('Substituída')).toBeTruthy()
    expect(within(carla).getByText('Motivo: Atestado')).toBeTruthy()
    expect(within(carla).getByText('Substituído(a) por Juliana Sintetica')).toBeTruthy()
    expect(within(screen.getByRole('region', { name: 'Cobertura sem escala' })).getByText(/Davi Sintetico/)).toBeTruthy()
    // Sem escala:gerenciar não há ações nem formulário.
    expect(screen.queryByRole('button', { name: 'Registrar ausência' })).toBeNull()
    expect(screen.queryByRole('form', { name: 'Nova escala' })).toBeNull()
  })

  it('gestor registra ausência com motivo e substitui', async () => {
    comPermissoes(['escala:ler', 'escala:gerenciar', 'funcionarios:ler'])
    responder()
    mockPost.mockResolvedValue({ data: {} } as any)
    const lista = await abrirDia()
    const bruno = within(lista).getByRole('region', { name: 'Escala de Bruno Sintetico' })
    // Cumprida (Ana, presente) não oferece ações.
    expect(within(within(lista).getByRole('region', { name: 'Escala de Ana Sintetica' })).queryByRole('button')).toBeNull()

    await userEvent.click(within(bruno).getByRole('button', { name: 'Registrar ausência' }))
    await userEvent.type(within(bruno).getByRole('textbox', { name: 'Motivo' }), 'Atestado médico')
    await userEvent.click(within(bruno).getByRole('button', { name: 'Confirmar' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/escala/previsto/e2/ausencia', { motivo: 'Atestado médico' }))

    await userEvent.click(within(bruno).getByRole('button', { name: 'Substituir' }))
    await userEvent.selectOptions(within(bruno).getByRole('combobox', { name: 'Substituto' }), 'f4')
    await userEvent.type(within(bruno).getByRole('textbox', { name: 'Motivo' }), 'Troca de última hora')
    await userEvent.click(within(bruno).getByRole('button', { name: 'Confirmar' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/escala/previsto/e2/substituir', { funcionario_id: 'f4', motivo: 'Troca de última hora' }))
  })
})

describe('Meu turno — iniciar a partir da própria escala (#122)', () => {
  it('oferece a escala pendente e inicia vinculado a ela', async () => {
    let atual: PlantaoAtual = { pode_registrar: true, funcionario_id: 'f1', plantao: null, escalas_pendentes: [escala({})] }
    mockGet.mockImplementation((url: string) => Promise.resolve({ data: url === '/plantoes/atual' ? atual : [] } as any))
    mockPost.mockImplementation(async () => {
      atual = { ...atual, escalas_pendentes: [], plantao: {
        id: 'p1', funcionario_id: 'f1', funcionario_nome: 'Ana Sintetica', turno_id: 't1', turno_nome: 'Diurno',
        inicio_em: '2030-01-15T10:05:00Z', fim_em: null, situacao: 'em_andamento', escala_id: 'e1',
        responsabilidades: [{ id: 'r1', plantao_id: 'p1', funcionario_id: 'f1', funcionario_nome: 'Ana Sintetica', area_id: 'area-b',
          area_nome: 'Ala B', inicio_em: '2030-01-15T10:05:00Z', fim_em: null, motivo_fim: null }],
      } }
      return { data: atual.plantao } as any
    })
    render(<MeuTurno />)
    expect(await screen.findByText(/Sua escala:/)).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: /Iniciar minha escala/ }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/plantoes/iniciar', { area_ids: [], escala_id: 'e1' }))
    expect(await screen.findByText('Responsável por: Ala B')).toBeTruthy()
  })
})

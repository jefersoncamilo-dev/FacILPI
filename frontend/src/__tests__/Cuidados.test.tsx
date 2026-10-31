import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { Cuidados } from '../pages/Cuidados'
import { PaisDetalhe } from '../pages/PaisDetalhe'
import { api } from '../services/api'
import { contextApi } from '../services/context'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }
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

const PLANO = {
  id: 'p1', residente_id: 'r1', versao: 1, objetivos: null, data_inicial: '2026-01-01', data_final: null, situacao: 'vigente',
  revisor_funcionario_id: null, aprovador_funcionario_id: null, revisado_em: null, aprovado_em: null,
  motivo_encerramento: null, encerrado_em: null, anterior_id: null, motivo_versao: null, superseded_by: null, created_at: null,
  necessidades: [{ id: 'n1', descricao: 'Risco de queda', situacao: 'ativa', origem: 'manual' }],
  metas: [{ id: 'm1', descricao: 'Zero quedas', situacao: 'ativa' }],
  intervencoes: [{ id: 'i1', descricao: 'Mudança de decúbito', situacao: 'ativa', perfil_responsavel: 'Enfermagem' }],
}
const PROG = {
  id: 'g1', residente_id: 'r1', plano_id: 'p1', intervencao_id: 'i1', horarios: ['08:00', '14:00'], timezone: 'America/Sao_Paulo',
  vigencia_inicio: '2026-01-01T00:00:00Z', vigencia_fim: null, perfil_responsavel: 'Enfermagem', prioridade: 'alta', situacao: 'ativa',
}
const OC = { id: 'o1', residente_id: 'r1', programacao_id: 'g1', intervencao_id: 'i1', previsto_em: '2026-10-24T17:00:00Z', situacao: 'prevista', pendente: true, motivo_cancelamento: null }

const RT = ['planos_cuidados:ler', 'programacoes:ler', 'programacoes:criar', 'ocorrencias:ler', 'ocorrencias:cancelar', 'residentes:ler']
const ENFERMAGEM = ['planos_cuidados:ler', 'programacoes:ler', 'programacoes:atualizar', 'ocorrencias:ler', 'ocorrencias:cancelar', 'residentes:ler']
const CUIDADOR = ['planos_cuidados:ler', 'programacoes:ler', 'ocorrencias:ler', 'residentes:ler']

function responde() {
  mockGet.mockImplementation((url: string) => {
    const de = (x: unknown) => Promise.resolve({ data: x } as any)
    if (url === '/planos-cuidados/p1') return de(PLANO)
    if (url === '/programacoes-cuidado/') return de([PROG])
    if (url === '/ocorrencias-cuidado/') return de([OC])
    if (url === '/residentes/') return de([{ id: 'r1', nome: 'Antônia Ribeiro' }])
    if (url === '/residentes/r1') return de({ id: 'r1', nome: 'Antônia Ribeiro' })
    if (url === '/funcionarios/') return de([])
    throw new Error(`URL inesperada: ${url}`)
  })
}

function renderEm(rota: string, permissoes: string[]) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes } } as any)
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[rota]}>
        <PermissoesProvider>
          <Routes>
            <Route path="/plano/:id" element={<PaisDetalhe />} />
            <Route path="/cuidados" element={<Cuidados />} />
          </Routes>
        </PermissoesProvider>
      </MemoryRouter>
    </AuthProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  responde()
})

describe('M12 — programar horários no PAIS vigente', () => {
  it('RT programa horários de uma intervenção e o POST segue o contrato do backend', async () => {
    const user = userEvent.setup()
    mockPost.mockResolvedValue({ data: PROG } as any)
    renderEm('/plano/p1', RT)
    await user.click(await screen.findByRole('button', { name: 'Programar horários: Mudança de decúbito' }))
    fireEvent.change(screen.getByLabelText('Horário 1'), { target: { value: '14:00' } })
    await user.click(screen.getByRole('button', { name: /Outro horário/ }))
    fireEvent.change(screen.getByLabelText('Horário 2'), { target: { value: '08:00' } })
    await user.selectOptions(screen.getByLabelText('Prioridade'), 'alta')
    await user.click(screen.getByRole('button', { name: 'Programar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/programacoes-cuidado/', expect.objectContaining({
      plano_id: 'p1', intervencao_id: 'i1', horarios: ['08:00', '14:00'], perfil_responsavel: 'Enfermagem', prioridade: 'alta',
      timezone: expect.any(String), vigencia_inicio: expect.any(String),
    })))
    const corpo = mockPost.mock.calls[0][1] as Record<string, unknown>
    expect(corpo).not.toHaveProperty('ilpi_id')
    expect(corpo).not.toHaveProperty('autor_id')
    expect(await screen.findByText(/aparecem no Meu Plantão/)).toBeTruthy()
  })

  it('sem programacoes:criar (Enfermagem, Cuidador) a ação não aparece', async () => {
    for (const perfil of [ENFERMAGEM, CUIDADOR]) {
      const { unmount } = renderEm('/plano/p1', perfil)
      expect(await screen.findByText('Mudança de decúbito')).toBeTruthy()
      expect(screen.queryByRole('button', { name: /Programar horários/ })).toBeNull()
      unmount()
    }
  })

  it('PAIS não vigente não oferece programação', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === '/planos-cuidados/p1') return Promise.resolve({ data: { ...PLANO, situacao: 'aprovado' } } as any)
      return Promise.resolve({ data: [] } as any)
    })
    renderEm('/plano/p1', RT)
    expect(await screen.findByText('Mudança de decúbito')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Programar horários/ })).toBeNull()
  })
})

describe('M12 — tela /cuidados', () => {
  it('lista por residente e área e Enfermagem cancela ocorrência com motivo', async () => {
    const user = userEvent.setup()
    mockPost.mockResolvedValue({ data: { ...OC, situacao: 'cancelada' } } as any)
    renderEm('/cuidados', ENFERMAGEM)
    expect(await screen.findByRole('region', { name: 'Antônia Ribeiro' })).toBeTruthy()
    expect(await screen.findByText('Mudança de decúbito')).toBeTruthy()
    expect(screen.getByText(/08:00, 14:00 · Enfermagem/)).toBeTruthy()
    expect(screen.getByRole('option', { name: 'Enfermagem' })).toBeTruthy()

    await user.click(screen.getByRole('button', { name: /Cancelar ocorrência de/ }))
    const confirmar = screen.getByRole('button', { name: 'Cancelar ocorrência' })
    expect((confirmar as HTMLButtonElement).disabled).toBe(true)
    await user.type(screen.getByLabelText('Motivo do cancelamento'), '  Residente em consulta externa ')
    await user.click(confirmar)
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/ocorrencias-cuidado/o1/cancelar', { motivo: 'Residente em consulta externa' }))
    expect(await screen.findByText(/Ocorrência cancelada/)).toBeTruthy()
  })

  it('Cuidador só lê: não vê cancelar', async () => {
    renderEm('/cuidados', CUIDADOR)
    expect(await screen.findByText('Mudança de decúbito')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Cancelar/ })).toBeNull()
  })
})

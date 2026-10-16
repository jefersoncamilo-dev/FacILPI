import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { Alertas } from '../pages/Alertas'
import { api } from '../services/api'
import { limparCentralAlertas } from '../hooks/useCentralAlertas'
import { rotuloEstado, type Alerta, type AlertaEstado, type CentralAlertas } from '../services/alertas'

const permissoes = vi.hoisted(() => ({ atuais: new Set<string>() }))
vi.mock('../context/PermissoesContext', async () => {
  const actual = await vi.importActual<typeof import('../context/PermissoesContext')>('../context/PermissoesContext')
  return { ...actual, usePermissoesOuPadrao: () => ({ status: 'ok', pode: (k: string) => permissoes.atuais.has(k) }) }
})

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
})

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)

function alerta(id: string, estado: AlertaEstado | null, titulo: string): Alerta {
  return {
    id, regra: 'intercorrencia_grave_aberta', categoria: 'plantao', gravidade: 'critico', natureza: 'alerta', titulo,
    detalhe: null, residente_id: 'r1', residente_nome: 'Hilda Sintetica', referencia_id: id.split(':')[1],
    unidade: null, quarto: null, leito: null, local: null, desde: null, prazo: null, estado,
  }
}

const estado = (parcial: Partial<AlertaEstado>): AlertaEstado => ({
  id: 'e1', situacao: 'em_atendimento', por_nome: 'Ana Paula', por_mim: false,
  assumido_em: '2026-09-28T10:00:00Z', em_atendimento_em: '2026-09-28T10:01:00Z', ...parcial,
})

function central(alertas: Alerta[]): CentralAlertas {
  return {
    gerado_em: '2026-09-28T10:05:00Z', fuso: 'America/Sao_Paulo', alertas,
    contagem: { critico: alertas.length, atencao: 0, aviso: 0, alerta: alertas.length, pendencia: 0, informativo: 0, atividade: 0, total: alertas.length },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  limparCentralAlertas()
  permissoes.atuais = new Set(['alertas:ler', 'alertas:assumir'])
})

describe('Estado do alerta na Central (#123)', () => {
  it('a equipe vê quem está em atendimento e não recebe botões sobre o alerta de outra pessoa', async () => {
    mockGet.mockResolvedValue({ data: central([
      alerta('intercorrencia_grave_aberta:a', estado({}), 'Intercorrência grave aberta: Queda'),
      alerta('intercorrencia_grave_aberta:b', null, 'Intercorrência grave aberta: Engasgo'),
    ]) } as any)
    render(<MemoryRouter><Alertas /></MemoryRouter>)
    const prioridade = await screen.findByRole('region', { name: 'Prioridade agora (2)' })
    const [queda, engasgo] = within(prioridade).getAllByRole('listitem')
    expect(within(queda).getByText('Em atendimento por Ana Paula')).toBeTruthy()
    expect(within(queda).queryByRole('button')).toBeNull()
    expect(within(engasgo).getByRole('button', { name: 'Assumir: Intercorrência grave aberta: Engasgo' })).toBeTruthy()
    // Não existe "resolver" manual: a resolução vem da fonte.
    expect(screen.queryByRole('button', { name: /Resolver/ })).toBeNull()
  })

  it('assumir chama o backend e recarrega; o próprio vê iniciar atendimento e liberar', async () => {
    let atual: Alerta[] = [alerta('intercorrencia_grave_aberta:b', null, 'Intercorrência grave aberta: Engasgo')]
    mockGet.mockImplementation(async () => ({ data: central(atual) }) as any)
    mockPost.mockImplementation(async () => {
      atual = [alerta('intercorrencia_grave_aberta:b', estado({ situacao: 'assumido', por_nome: 'Bruno', por_mim: true, em_atendimento_em: null }), 'Intercorrência grave aberta: Engasgo')]
      return { data: { alerta_id: 'intercorrencia_grave_aberta:b', estado: atual[0].estado } } as any
    })
    render(<MemoryRouter><Alertas /></MemoryRouter>)
    await userEvent.click(await screen.findByRole('button', { name: /^Assumir/ }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/central-alertas/assumir', { alerta_id: 'intercorrencia_grave_aberta:b' }))
    expect(await screen.findByText('Assumido por você')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Iniciar atendimento: Intercorrência grave aberta: Engasgo' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Liberar: Intercorrência grave aberta: Engasgo' })).toBeTruthy()
  })

  it('sem alertas:assumir não há botões; a coordenação (escala:gerenciar) libera o alerta de outra pessoa', async () => {
    mockGet.mockResolvedValue({ data: central([
      alerta('intercorrencia_grave_aberta:a', estado({}), 'Intercorrência grave aberta: Queda'),
    ]) } as any)
    permissoes.atuais = new Set(['alertas:ler'])
    const { unmount } = render(<MemoryRouter><Alertas /></MemoryRouter>)
    expect(await screen.findByText('Em atendimento por Ana Paula')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Liberar|Assumir/ })).toBeNull()
    unmount()

    permissoes.atuais = new Set(['alertas:ler', 'alertas:assumir', 'escala:gerenciar'])
    mockPost.mockResolvedValue({ data: { alerta_id: 'intercorrencia_grave_aberta:a', estado: null } } as any)
    render(<MemoryRouter><Alertas /></MemoryRouter>)
    await userEvent.click(await screen.findByRole('button', { name: 'Liberar: Intercorrência grave aberta: Queda' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/central-alertas/liberar', { alerta_id: 'intercorrencia_grave_aberta:a' }))
  })

  it('409 mostra quem assumiu antes', async () => {
    mockGet.mockResolvedValue({ data: central([alerta('intercorrencia_grave_aberta:b', null, 'Intercorrência grave aberta: Engasgo')]) } as any)
    mockPost.mockRejectedValue({ response: { status: 409, data: { detail: { code: 'ALERTA_CONFLITO', message: 'Já assumido por Ana Paula' } } } })
    render(<MemoryRouter><Alertas /></MemoryRouter>)
    await userEvent.click(await screen.findByRole('button', { name: /^Assumir/ }))
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText(/Já assumido por Ana Paula/)).toBeTruthy()
  })

  it('rótulo do estado', () => {
    expect(rotuloEstado(null)).toBeNull()
    expect(rotuloEstado(estado({}))).toBe('Em atendimento por Ana Paula')
    expect(rotuloEstado(estado({ situacao: 'assumido', por_mim: true }))).toBe('Assumido por você')
  })
})

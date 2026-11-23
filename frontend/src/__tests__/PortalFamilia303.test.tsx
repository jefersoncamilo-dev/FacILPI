import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PortalFamilia, type ResumoPortal } from '../pages/PortalFamilia'
import { PortalFamiliaConfig } from '../components/portal/PortalFamiliaConfig'
import { api } from '../services/api'

// #303. Dados sintéticos: nomes fictícios, nenhum dado real.
vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), put: vi.fn() } }
})
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ logout: vi.fn() }) }))
const mockGet = vi.mocked(api.get)
const mockPut = vi.mocked(api.put)

const BASE: ResumoPortal = {
  residente_nome: 'Dona Sintética', familiar_nome: 'Filha Sintética', hoje: '2026-11-22', portal_liberado: false, categorias: [],
  medicacao: null, alimentacao: null, atividades: null, peso: null, compromissos_hoje: null, recados_hoje: null,
  agenda: null, mensalidades: null, recados: null,
}

beforeEach(() => { mockGet.mockReset(); mockPut.mockReset() })

describe('Portal Família (#303)', () => {
  it('sem nada liberado, avisa e não mostra nenhum bloco', async () => {
    mockGet.mockResolvedValue({ data: BASE } as any)
    render(<PortalFamilia />)
    expect(await screen.findByText(/ainda não liberou informações/)).toBeInTheDocument()
    expect(screen.queryByText('Recados da equipe')).not.toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('mostra só as categorias que vieram liberadas, em linguagem simples', async () => {
    mockGet.mockResolvedValue({ data: { ...BASE, portal_liberado: true, categorias: ['medicacao', 'recados'],
      medicacao: { feitos: 28, total: 30, percentual: 93 },
      recados: [{ id: 'x', texto: 'Passeou no jardim', autor_nome: 'Enf. Sintética', created_at: '2026-11-22T12:00:00Z' }] } } as any)
    render(<PortalFamilia />)
    expect(await screen.findByRole('progressbar', { name: 'Remédios dados' })).toHaveAttribute('aria-valuenow', '93')
    expect(screen.getByText('28 de 30 remédios previstos.')).toBeInTheDocument()
    expect(screen.getByText('Passeou no jardim')).toBeInTheDocument()
    expect(screen.queryByText('Mensalidades')).not.toBeInTheDocument()
    expect(screen.getByText(/Dúvidas sobre saúde e tratamento/)).toBeInTheDocument()
  })

  it('equipe liga o portal e escolhe categorias; tudo começa desmarcado', async () => {
    mockGet.mockResolvedValue({ data: { ativo: false, categorias: [] } } as any)
    mockPut.mockImplementation(((_u: string, body: unknown) => Promise.resolve({ data: body })) as any)
    render(<PortalFamiliaConfig />)
    const ligar = await screen.findByRole('checkbox', { name: /Portal ligado/ })
    expect(ligar).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: /Remédios/ })).toBeDisabled()
    expect(screen.getAllByRole('checkbox').filter(c => (c as HTMLInputElement).checked)).toHaveLength(0)
    await userEvent.click(ligar)
    await userEvent.click(screen.getByRole('checkbox', { name: /Recados da equipe/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Salvar portal' }))
    expect(mockPut).toHaveBeenCalledWith('/portal/config', { ativo: true, categorias: ['recados'] })
    expect(await screen.findByText('Portal da família atualizado.')).toBeInTheDocument()
  })
})

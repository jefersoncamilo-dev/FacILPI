import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { Relatorios } from '../pages/Relatorios'
import { api } from '../services/api'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn() } }
})
const mockGet = vi.mocked(api.get)

describe('Relatorios', () => {
  beforeEach(() => vi.clearAllMocks())

  it('mostra só as seções que vieram', async () => {
    mockGet.mockResolvedValue({ data: { residentes_por_situacao: [{ chave: 'Ativo', total: 3 }], intercorrencias_por_gravidade: [], administracoes_por_resultado: null } } as any)
    render(<MemoryRouter><Relatorios /></MemoryRouter>)
    expect(await screen.findByText('Residentes hoje, por situação')).toBeTruthy()
    expect(screen.getByText('3')).toBeTruthy()
    expect(screen.queryByText('Administrações de medicação')).toBeNull()
  })

  it('403 mostra sem acesso', async () => {
    mockGet.mockRejectedValue({ response: { status: 403 } })
    render(<MemoryRouter><Relatorios /></MemoryRouter>)
    expect(await screen.findByText('Sem acesso a relatórios')).toBeTruthy()
  })
})

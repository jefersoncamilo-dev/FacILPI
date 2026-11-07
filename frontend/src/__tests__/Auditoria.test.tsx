import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { Auditoria } from '../pages/Auditoria'
import { api } from '../services/api'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn() } }
})
const mockGet = vi.mocked(api.get)

describe('Auditoria', () => {
  beforeEach(() => vi.clearAllMocks())

  it('lista registros com autor', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 'a', acao: 'residente.criado', entidade: 'residentes', registro_id: null, usuario_nome: 'Ana Sintética', valores_anteriores: null, valores_posteriores: null, created_at: '2026-11-06T10:00:00Z' }] } as any)
    render(<MemoryRouter><Auditoria /></MemoryRouter>)
    expect(await screen.findByText('residente.criado')).toBeTruthy()
    expect(screen.getByText(/Ana Sintética/)).toBeTruthy()
  })

  it('403 mostra sem acesso', async () => {
    mockGet.mockRejectedValue({ response: { status: 403 } })
    render(<MemoryRouter><Auditoria /></MemoryRouter>)
    expect(await screen.findByText('Sem acesso à auditoria')).toBeTruthy()
  })
})

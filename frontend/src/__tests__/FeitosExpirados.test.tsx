import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { FeitosExpirados } from '../components/plantao/FeitosExpirados'
import { api } from '../services/api'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
})

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)
const INICIO = '2026-09-28T10:00:00Z'

beforeEach(() => {
  vi.clearAllMocks()
  mockGet.mockImplementation((url: string) => {
    if (url === '/plantoes/atual') return Promise.resolve({ data: { pode_registrar: true, funcionario_id: 'f1', plantao: { inicio_em: INICIO } } } as any)
    if (url === '/execucoes-cuidado/') return Promise.resolve({ data: [
      { id: 'e1', residente_id: 'r1', ocorrencia_id: 'o1', resultado: 'executada', ocorrido_em: '2026-09-28T11:00:00Z', descricao: 'Banho', executor_nome: 'Ana' },
    ] } as any)
    if (url === '/central-alertas/expirados') return Promise.resolve({ data: [
      { id: 's1', alerta_id: 'cuidados_sem_registro:r2', regra: 'cuidados_sem_registro', residente_id: 'r2', por_nome: 'Bia',
        assumido_em: '2026-09-28T10:30:00Z', encerrado_em: '2026-09-28T11:30:00Z' },
    ] } as any)
    return Promise.reject(new Error(`inesperado ${url}`))
  })
})

describe('Feitos/Expirados do turno (G5 #198)', () => {
  it('só carrega ao abrir, lê desde o início do plantão e nunca escreve', async () => {
    render(<FeitosExpirados nomes={{ r1: 'Hilda Sintetica', r2: 'Rita Sintetica' }} />)
    expect(mockGet).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Feitos/Expirados do turno' }))

    expect(await screen.findByText('Banho')).toBeTruthy()
    expect(screen.getByText(/Hilda Sintetica · Realizado/)).toBeTruthy()
    expect(mockGet).toHaveBeenCalledWith('/execucoes-cuidado/', { params: { a_partir_de: INICIO, limit: 200 } })
    expect(mockGet).toHaveBeenCalledWith('/central-alertas/expirados', { params: { a_partir_de: INICIO } })

    fireEvent.click(screen.getByRole('tab', { name: 'Expirados (1)' }))
    expect(screen.getByText(/Rita Sintetica/)).toBeTruthy()
    expect(screen.getByText(/assumido por Bia/)).toBeTruthy()
    expect(mockPost).not.toHaveBeenCalled()
  })
})

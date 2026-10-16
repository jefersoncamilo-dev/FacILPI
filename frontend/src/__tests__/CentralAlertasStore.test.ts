import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { api } from '../services/api'
import { limparCentralAlertas, recarregarCentralAlertas, useCentralAlertas } from '../hooks/useCentralAlertas'
import { CONTEXT_CHANGED_EVENT, TOKEN_KEY } from '../types/context'
import type { CentralAlertas } from '../services/alertas'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
})

const mockGet = vi.mocked(api.get)
const vazio = (gerado: string): CentralAlertas => ({
  gerado_em: gerado,
  contagem: { critico: 0, atencao: 0, aviso: 0, alerta: 0, pendencia: 0, informativo: 0, atividade: 0, total: 0 },
  alertas: [],
})
const chamadas = () => mockGet.mock.calls.filter(c => c[0] === '/central-alertas/').length

/**
 * #119: o retrato compartilhado de /central-alertas/ nunca mostra dados de
 * outra sessão (tablet compartilhado) nem de outra ILPI após troca de contexto.
 */
describe('useCentralAlertas — isolamento e política de atualização', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    limparCentralAlertas()
    mockGet.mockImplementation(async () => ({ data: vazio('2026-09-28T10:00:00Z') }) as any)
  })

  it('troca de sessão no mesmo aparelho descarta o retrato e busca de novo', async () => {
    localStorage.setItem(TOKEN_KEY, 'token-ana')
    const { result, rerender } = renderHook(() => useCentralAlertas())
    await act(() => recarregarCentralAlertas())
    expect(result.current.status).toBe('ok')

    localStorage.setItem(TOKEN_KEY, 'token-bruno')
    rerender()
    expect(result.current.status).toBe('vazio')
    // Mesmo dentro do minuto, a outra sessão não herda o retrato: nova consulta.
    await act(() => recarregarCentralAlertas())
    expect(chamadas()).toBe(2)
    expect(result.current.status).toBe('ok')
  })

  it('troca de contexto (ILPI) limpa o retrato', async () => {
    localStorage.setItem(TOKEN_KEY, 'token-ana')
    const { result } = renderHook(() => useCentralAlertas())
    await act(() => recarregarCentralAlertas())
    expect(result.current.status).toBe('ok')
    act(() => { window.dispatchEvent(new Event(CONTEXT_CHANGED_EVENT)) })
    expect(result.current.status).toBe('vazio')
  })

  it('resposta em voo de antes da troca é descartada', async () => {
    localStorage.setItem(TOKEN_KEY, 'token-ana')
    let responder: (v: any) => void = () => {}
    mockGet.mockImplementationOnce(() => new Promise(r => { responder = r }) as any)
    const { result } = renderHook(() => useCentralAlertas())
    let emVoo!: Promise<void>
    act(() => { emVoo = recarregarCentralAlertas() })
    expect(result.current.status).toBe('carregando')
    act(() => { window.dispatchEvent(new Event(CONTEXT_CHANGED_EVENT)) })
    await act(async () => { responder({ data: vazio('2026-09-28T09:00:00Z') }); await emVoo })
    expect(result.current.status).toBe('vazio')
  })

  it('no máximo uma consulta por minuto ao navegar; a Central força', async () => {
    localStorage.setItem(TOKEN_KEY, 'token-ana')
    await recarregarCentralAlertas()
    await recarregarCentralAlertas()
    expect(chamadas()).toBe(1)
    await recarregarCentralAlertas({ forcar: true })
    await waitFor(() => expect(chamadas()).toBe(2))
  })
})

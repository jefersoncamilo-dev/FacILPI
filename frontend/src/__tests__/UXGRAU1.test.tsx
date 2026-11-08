import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, renderHook, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { PermissoesProvider } from '../context/PermissoesContext'
import { SeloGrau } from '../components/residente/SeloGrau'
import { AvatarResidente } from '../components/residente/AvatarResidente'
import { useGrausAtivos } from '../hooks/useGrausAtivos'
import { compararPorGrau, grauDaApi, ordemDoGrau, type GrauNaTela } from '../lib/grau'
import { api } from '../services/api'
import { contextApi } from '../services/context'

// Dados sintéticos: ids fictícios, nenhum dado real.
vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn() } }
})
vi.mock('../services/context', () => ({ contextApi: { permissoesDaSessao: vi.fn() } }))

const mockGet = vi.mocked(api.get)
const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

beforeEach(() => vi.clearAllMocks())

describe('UX-GRAU — ordem de atenção', () => {
  it('sem grau no topo, depois III, II e I; não consultado por último', () => {
    const lista: GrauNaTela[] = ['Grau I', undefined, 'Grau III', null, 'Grau II']
    expect([...lista].sort(compararPorGrau)).toEqual([null, 'Grau III', 'Grau II', 'Grau I', undefined])
    expect(ordemDoGrau('Grau III')).toBeLessThan(ordemDoGrau('Grau I'))
  })

  it('sem permissão (todos undefined) a ordem original se mantém', () => {
    const itens = [{ n: 'b', g: undefined }, { n: 'a', g: undefined }]
    expect([...itens].sort((x, y) => compararPorGrau(x.g, y.g)).map(i => i.n)).toEqual(['b', 'a'])
  })

  it('normaliza o valor da API sem inventar grau', () => {
    expect(grauDaApi('Grau II')).toBe('Grau II')
    expect(grauDaApi(null)).toBeNull()
    expect(grauDaApi('Grau 4')).toBeNull()
    expect(grauDaApi(undefined)).toBeUndefined()
  })
})

describe('UX-GRAU — selo e círculo da foto', () => {
  it('selo em verde, amarelo e vermelho, sempre com o texto do grau', () => {
    render(<><SeloGrau classificacao="Grau I" /><SeloGrau classificacao="Grau II" /><SeloGrau classificacao="Grau III" /></>)
    expect(screen.getByLabelText('Grau de dependência I').className).toContain('bg-grau-1-fundo')
    const dois = screen.getByLabelText('Grau de dependência II')
    expect(dois.className).toContain('bg-grau-2-fundo')
    expect(dois.className).toContain('text-grau-2-texto')
    expect(dois.textContent).toBe('Grau II')
    expect(screen.getByLabelText('Grau de dependência III').className).toContain('bg-grau-3-fundo')
  })

  it('"Sem grau" só quando pedido e consultado; nada sem consulta', () => {
    const { container, rerender } = render(<SeloGrau classificacao={null} semGrau />)
    expect(container.textContent).toBe('Sem grau')
    rerender(<SeloGrau classificacao={undefined} semGrau />)
    expect(container.textContent).toBe('')
    rerender(<SeloGrau classificacao={null} />)
    expect(container.textContent).toBe('')
  })

  it('círculo na cor do grau; Grau II com contorno escuro; sem grau informado, sem círculo', () => {
    const { container, rerender } = render(<AvatarResidente nome="Ana Sintética" grau="Grau III" />)
    const avatar = () => container.firstElementChild as HTMLElement
    expect(avatar().className).toContain('ring-grau-3')
    rerender(<AvatarResidente nome="Ana Sintética" grau="Grau II" />)
    expect(avatar().className).toContain('ring-grau-2')
    expect(avatar().className).toContain('outline-grau-2-contorno')
    expect(avatar().className).toContain('outline-offset-[6px]')
    rerender(<AvatarResidente nome="Ana Sintética" grau={null} />)
    expect(avatar().className).toContain('ring-border')
    rerender(<AvatarResidente nome="Ana Sintética" />)
    expect(avatar().className).not.toMatch(/ring-/)
    expect(avatar().getAttribute('aria-hidden')).toBe('true')
  })
})

describe('UX-GRAU — grau oficial ativo (useGrausAtivos)', () => {
  const wrapper = ({ children }: { children: ReactNode }) => <PermissoesProvider>{children}</PermissoesProvider>
  const comPermissoes = (permissoes: string[]) =>
    mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', ilpi_id: 'ilpi1', permissoes } } as any)

  it('sem grau_dependencia:ler não consulta e não devolve grau', async () => {
    comPermissoes(['residentes:ler'])
    const { result } = renderHook(() => useGrausAtivos(), { wrapper })
    await waitFor(() => expect(result.current.status).toBe('sem_acesso'))
    expect(result.current.grauDe('r1')).toBeUndefined()
    expect(mockGet).not.toHaveBeenCalled()
  })

  it('pagina a lista, usa só o grau ativo e diferencia "sem grau"', async () => {
    comPermissoes(['grau_dependencia:ler'])
    const cheia = Array.from({ length: 100 }, (_, i) => ({ residente_id: `x${i}`, classificacao: 'Grau I', situacao: 'substituido' }))
    mockGet
      .mockResolvedValueOnce({ data: cheia } as any)
      .mockResolvedValueOnce({ data: [
        { residente_id: 'r1', classificacao: 'Grau III', situacao: 'ativo' },
        { residente_id: 'r2', classificacao: 'Grau I', situacao: 'substituido' },
      ] } as any)
    const { result } = renderHook(() => useGrausAtivos(), { wrapper })
    await waitFor(() => expect(result.current.status).toBe('ok'))
    expect(mockGet.mock.calls.map(c => (c[1] as any).params)).toEqual([{ skip: 0, limit: 100 }, { skip: 100, limit: 100 }])
    expect(result.current.grauDe('r1')).toBe('Grau III')
    expect(result.current.grauDe('r2')).toBeNull()
  })

  it('falha na consulta não vira "sem grau"', async () => {
    comPermissoes(['grau_dependencia:ler'])
    mockGet.mockRejectedValue(new Error('500'))
    const { result } = renderHook(() => useGrausAtivos(), { wrapper })
    await waitFor(() => expect(result.current.status).toBe('erro'))
    expect(result.current.grauDe('r1')).toBeUndefined()
  })
})

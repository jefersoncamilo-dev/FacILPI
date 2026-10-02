import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { MeuPlantao } from '../pages/MeuPlantao'
import { api } from '../services/api'
import { agrupar, chaveDoCuidado, filtrar, tempoDeAtraso, FILTROS_PADRAO } from '../components/plantao/visoes'
import type { PlantaoItem } from '../services/plantao'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
})

const AGORA = Date.parse('2026-10-02T12:00:00Z')
const hora = (h: string) => `2026-10-02T${h}:00Z`

function item(id: string, residente: string, descricao: string, previsto: string | null, origem: PlantaoItem['origem'] = 'cuidado', local: string | null = null): PlantaoItem {
  return { origem, registro_id: id, residente_id: residente, descricao, previsto_em: previsto, prioridade: null, local }
}

const NOMES = { r1: 'Maria Souza', r2: 'João Lima', r3: 'Ana Reis' }
const FILA: PlantaoItem[] = [
  item('a', 'r2', 'Banho', hora('11:30')),                 // atrasado (João)
  item('b', 'r1', 'Banho ', hora('13:00'), 'cuidado', 'Ala B · Quarto 12 · Leito A'),
  item('c', 'r3', 'Hidratação', hora('13:00')),
  item('d', 'r1', 'banho', hora('14:00')),                 // mesma chave de "Banho" (caixa/espaço)
  item('e', 'r3', 'Dose prevista de medicacao', hora('15:00'), 'medicacao'),
  item('f', 'r1', 'Intercorrencia aberta: Queda', null, 'intercorrencia'),
]

describe('UX-01A.2 — visões (puras)', () => {
  it('por horário: Atrasadas, Próximas e sem horário, na ordem da projeção', () => {
    const grupos = agrupar(FILA, 'horario', NOMES, AGORA)
    expect(grupos.map(g => [g.titulo, g.itens.map(i => i.registro_id)])).toEqual([
      ['Atrasadas', ['a']],
      ['Próximas', ['b', 'c', 'd', 'e']],
      ['Intercorrências abertas', ['f']],
    ])
  })

  it('por cuidado: junta descrições iguais ignorando caixa/espaços/acentos', () => {
    expect(chaveDoCuidado(item('x', 'r', 'Hidratação', null))).toBe(chaveDoCuidado(item('y', 'r', ' hidratacao ', null)))
    const grupos = agrupar(FILA, 'cuidado', NOMES, AGORA)
    expect(grupos.map(g => [g.titulo, g.itens.map(i => i.registro_id)])).toEqual([
      ['Banho', ['a', 'b', 'd']],
      ['Hidratação', ['c']],
      ['Medicação', ['e']],
      ['Intercorrências abertas', ['f']],
    ])
  })

  it('por residente: quem tem atraso primeiro, depois horário mais cedo, depois nome', () => {
    const grupos = agrupar(FILA, 'residente', NOMES, AGORA)
    // Ana e Maria empatam às 13:00 → ordem alfabética.
    expect(grupos.map(g => [g.titulo, g.itens.map(i => i.registro_id)])).toEqual([
      ['João Lima', ['a']],
      ['Ana Reis', ['c', 'e']],
      ['Maria Souza', ['b', 'd', 'f']],
    ])
  })

  it('situação: Pendentes = no prazo (inclui sem horário); Atrasados = passou da hora', () => {
    expect(filtrar(FILA, { ...FILTROS_PADRAO, situacao: 'atrasados' }, AGORA).map(i => i.registro_id)).toEqual(['a'])
    expect(filtrar(FILA, { ...FILTROS_PADRAO, situacao: 'pendentes' }, AGORA).map(i => i.registro_id)).toEqual(['b', 'c', 'd', 'e', 'f'])
    expect(filtrar(FILA, { ...FILTROS_PADRAO, origem: 'medicacao', residenteId: 'r3' }, AGORA).map(i => i.registro_id)).toEqual(['e'])
  })

  it('tempo de atraso legível', () => {
    expect(tempoDeAtraso(hora('11:25'), AGORA)).toBe('35 min')
    expect(tempoDeAtraso(hora('09:55'), AGORA)).toBe('2h05')
    expect(tempoDeAtraso(hora('10:00'), AGORA)).toBe('2h')
  })
})

// ---- Tela ----

const mockGet = vi.mocked(api.get)
const futuro = (h: string) => `2099-01-01T${h}:00Z`
const TELA: PlantaoItem[] = [
  item('t1', 'r1', 'Banho', futuro('10:00'), 'cuidado', 'Ala B · Quarto 12 · Leito A'),
  item('t2', 'r2', 'Banho', futuro('10:30')),
  item('t3', 'r1', 'Hidratação', futuro('11:00')),
]

function responde(itens: PlantaoItem[]) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/plantao/') return Promise.resolve({ data: itens } as any)
    if (url === '/residentes/') return Promise.resolve({ data: [{ id: 'r1', nome: 'Maria Souza' }, { id: 'r2', nome: 'João Lima' }] } as any)
    throw new Error(`URL inesperada: ${url}`)
  })
}

const renderTela = () => render(<MemoryRouter><MeuPlantao /></MemoryRouter>)

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
})

describe('UX-01A.2 — tela', () => {
  it('sem ?desde=, a fila começa 24 h atrás para mostrar o que está atrasado', async () => {
    responde(TELA)
    renderTela()
    await screen.findByRole('region', { name: 'Próximas' })
    const { a_partir_de } = (mockGet.mock.calls.find(c => c[0] === '/plantao/')![1] as any).params
    expect(Math.abs(Date.now() - Date.parse(a_partir_de) - 24 * 3600 * 1000)).toBeLessThan(60_000)
  })

  it('card mostra horário, cuidado, residente e quarto/leito', async () => {
    responde(TELA)
    renderTela()
    const proximas = await screen.findByRole('region', { name: 'Próximas' })
    // Linha 2: residente · quarto/leito; linha 3: horário (secundário). Avatar com iniciais sem foto.
    expect(within(proximas).getByText(/^Maria Souza · +Ala B · Quarto 12 · Leito A$/)).toBeTruthy()
    expect(within(proximas).getAllByText('Banho')).toHaveLength(2)
    expect(within(proximas).getAllByText(/Maria Souza/)).toHaveLength(2)
    expect(within(proximas).getAllByText('MS')).toHaveLength(2)
    expect(within(proximas).getAllByText(/^\d{2}:\d{2}/).length).toBeGreaterThanOrEqual(3)
  })

  it('"Por cuidado" agrupa com contagem e lembra a escolha na sessão', async () => {
    const user = userEvent.setup()
    responde(TELA)
    const { unmount } = renderTela()
    await screen.findByRole('region', { name: 'Próximas' })

    await user.click(screen.getByRole('button', { name: 'Por cuidado' }))
    const banho = screen.getByRole('region', { name: 'Banho' })
    expect(within(banho).getByText('2 pendentes')).toBeTruthy()
    expect(within(banho).getByText('João Lima')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Por cuidado' }).getAttribute('aria-pressed')).toBe('true')

    unmount()
    renderTela()
    expect(await screen.findByRole('region', { name: 'Hidratação' })).toBeTruthy()
  })

  it('"Por residente" agrupa pelo nome', async () => {
    const user = userEvent.setup()
    responde(TELA)
    renderTela()
    await screen.findByRole('region', { name: 'Próximas' })
    await user.click(screen.getByRole('button', { name: 'Por residente' }))
    const maria = screen.getByRole('region', { name: 'Maria Souza' })
    expect(within(maria).getByText('2 pendentes')).toBeTruthy()
    expect(within(maria).getByText('Hidratação')).toBeTruthy()
  })

  it('Filtros (Sheet): residente reduz a fila e o botão mostra quantos estão ativos', async () => {
    const user = userEvent.setup()
    responde(TELA)
    renderTela()
    await screen.findByRole('region', { name: 'Próximas' })

    await user.click(screen.getByRole('button', { name: 'Filtros' }))
    const dialogo = within(await screen.findByRole('dialog', { name: 'Filtros do plantão' }))
    await user.selectOptions(dialogo.getByLabelText('Residente'), 'r2')
    await user.click(dialogo.getByRole('button', { name: 'Ver resultados' }))

    expect(screen.getByRole('button', { name: 'Filtros (1)' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Todos 1' })).toBeTruthy()
    expect(screen.queryByText('Hidratação')).toBeNull()
  })
})

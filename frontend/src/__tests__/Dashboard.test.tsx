import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { Dashboard } from '../pages/Dashboard'
import { api } from '../services/api'
import { contextApi } from '../services/context'
import type { DashboardResumo } from '../services/dashboard'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
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
const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

const GESTAO = [
  'residentes:ler', 'residentes:criar', 'plantao:ler', 'intercorrencias:ler', 'quartos_leitos:ler',
  'ausencias:ler', 'admissoes:ler', 'planos_cuidados:ler', 'funcionarios:ler',
]
const CUIDADO = ['plantao:ler', 'residentes:ler', 'intercorrencias:ler', 'sinais_vitais:criar', 'intercorrencias:criar']

const PENDENCIAS = [
  { origem: 'cuidado', registro_id: 'oc-1', residente_id: 'res-1', descricao: 'Banho assistido', previsto_em: '2026-09-15T12:00:00Z', prioridade: 'alta' },
  { origem: 'medicacao', registro_id: 'dose-1', residente_id: 'res-2', descricao: 'Dose prevista de medicacao', previsto_em: '2026-09-15T13:00:00Z', prioridade: null },
]
const RESIDENTES = [{ id: 'res-1', nome: 'Maria Silva', situacao: 'Em admissao', grau_dependencia: 'II' }]

function resumo(parcial: Partial<DashboardResumo> = {}): DashboardResumo {
  return {
    gerado_em: '2026-09-15T12:00:00Z',
    residentes_total: 1,
    ocupacao: null,
    ausencias_ativas: null,
    intercorrencias_abertas: 0,
    admissoes_em_andamento: null,
    planos: null,
    equipe: null,
    ...parcial,
  }
}

type Fonte = unknown[] | DashboardResumo | Error
function responde({ resumo: r = resumo(), plantao = PENDENCIAS, residentes = RESIDENTES }: { resumo?: Fonte; plantao?: Fonte; residentes?: Fonte } = {}) {
  const de = (fonte: Fonte) => (fonte instanceof Error ? Promise.reject(fonte) : Promise.resolve({ data: fonte } as any))
  mockGet.mockImplementation((url: string) => {
    if (url === '/dashboard/resumo') return de(r)
    if (url === '/plantao/') return de(plantao)
    if (url === '/residentes/') return de(residentes)
    throw new Error(`URL inesperada no Dashboard: ${url}`)
  })
}

function renderDashboard(permissoes: string[] = GESTAO) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', ilpi_id: 'i1', permissoes } } as any)
  return render(
    <AuthProvider>
      <MemoryRouter>
        <PermissoesProvider>
          <Dashboard />
        </PermissoesProvider>
      </MemoryRouter>
    </AuthProvider>,
  )
}

function urlsChamadas() {
  return mockGet.mock.calls.map(c => String(c[0]))
}

async function cartao(titulo: string) {
  return (await screen.findByText(titulo)).closest('div.rounded-card') as HTMLElement
}

function titulosDosIndicadores() {
  return within(screen.getByRole('region', { name: 'Indicadores' }))
    .getAllByText(/./, { selector: 'p.text-sm.font-medium' })
    .map(e => e.textContent)
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('Dashboard — fontes oficiais, nunca endpoints fail-closed', () => {
  it('1. não chama /tarefas/ nem /alertas/', async () => {
    responde()
    renderDashboard()
    await waitFor(() => expect(urlsChamadas()).toContain('/plantao/'))
    expect(urlsChamadas()).toContain('/dashboard/resumo')
    expect(urlsChamadas().some(u => u.includes('tarefas'))).toBe(false)
    expect(urlsChamadas().some(u => u.includes('alertas'))).toBe(false)
  })

  it('2. pendências vêm da projeção /plantao/, com o nome do residente', async () => {
    responde()
    renderDashboard()
    await waitFor(async () => expect((await cartao('Pendências do turno')).textContent).toContain('2'))
    expect(await screen.findByText('Banho assistido')).toBeTruthy()
    expect(await screen.findByText('Maria Silva', { selector: 'p' })).toBeTruthy()
  })
})

describe('Dashboard — indisponibilidade nunca vira zero', () => {
  it('3. falha da projeção mostra traço e explica, não 0', async () => {
    responde({ plantao: new Error('rede') })
    renderDashboard()
    const card = await cartao('Pendências do turno')
    await waitFor(() => expect(card.textContent).toContain('—'))
    expect(card.textContent).toContain('Indisponível no momento')
    expect(card.textContent).not.toMatch(/\b0\b/)
    expect(await screen.findByText('Não foi possível carregar as pendências')).toBeTruthy()
    expect(screen.getByText('Isso não significa que não há pendências.')).toBeTruthy()
    expect(screen.queryByText('Nenhuma pendência no período')).toBeNull()
  })

  it('4. projeção vazia legítima mostra zero e estado vazio próprio', async () => {
    responde({ plantao: [] })
    renderDashboard()
    expect(await screen.findByText('Nenhuma pendência no período')).toBeTruthy()
    const card = await cartao('Pendências do turno')
    expect(card.textContent).toMatch(/Pendências do turno\s*0/)
  })

  it('5. resumo indisponível vira traço nos indicadores que a sessão lê — nunca 0', async () => {
    responde({ resumo: new Error('rede') })
    renderDashboard()
    for (const titulo of ['Residentes cadastrados', 'Intercorrências abertas', 'Ocupação de leitos']) {
      const card = await cartao(titulo)
      await waitFor(() => expect(card.textContent).toContain('—'))
      expect(card.textContent).toContain('Indisponível no momento')
      expect(card.textContent).not.toMatch(/\b0\b/)
    }
    expect(await screen.findByText('Não foi possível carregar os processos')).toBeTruthy()
  })

  it('6. falha nos residentes não vira "nenhum residente"', async () => {
    responde({ residentes: new Error('rede') })
    renderDashboard()
    expect(await screen.findByText('Não foi possível carregar os residentes')).toBeTruthy()
    expect(screen.getByText('Isso não significa que não há residentes cadastrados.')).toBeTruthy()
    expect(screen.queryByText('Nenhum residente cadastrado')).toBeNull()
  })
})

describe('Dashboard — só afirma o que tem fonte (PH-02 / #71)', () => {
  it('7. conformidade e alertas não têm fonte oficial: nada é afirmado', async () => {
    for (const r of [resumo(), new Error('rede')]) {
      responde({ resumo: r })
      const { unmount } = renderDashboard()
      await screen.findByText('Residentes cadastrados')
      expect(screen.queryByText(/Conformidade/)).toBeNull()
      expect(screen.queryByText(/Alertas/)).toBeNull()
      expect(document.body.textContent).not.toMatch(/Em dia|Licenças verificadas|✅/)
      unmount()
    }
  })

  it('8. ocupação só aparece com a fonte oficial de leitos — nunca derivada de residentes', async () => {
    responde({ resumo: resumo({ residentes_total: 50, ocupacao: null }) })
    const semLeitos = renderDashboard()
    await waitFor(async () => expect((await cartao('Residentes cadastrados')).textContent).toContain('50'))
    expect(screen.queryByText(/Ocupação/)).toBeNull()
    expect(document.body.textContent).not.toMatch(/\d+\s*%/)
    semLeitos.unmount()

    responde({ resumo: resumo({ ocupacao: { leitos_ativos: 5, ocupados: 2, livres: 1, indisponiveis: 2 } }) })
    renderDashboard()
    const card = await cartao('Ocupação de leitos')
    await waitFor(() => expect(card.textContent).toContain('2/5'))
    expect(card.textContent).toContain('40% ocupados · 1 livre')
  })

  it('9. total é "cadastrados", nunca "ativos", e vem da contagem oficial sem teto', async () => {
    const cem = Array.from({ length: 100 }, (_, i) => ({ id: `r-${i}`, nome: `Residente ${i}`, situacao: 'Em admissao' }))
    responde({ resumo: resumo({ residentes_total: 137 }), residentes: cem })
    renderDashboard()
    const card = await cartao('Residentes cadastrados')
    await waitFor(() => expect(card.textContent).toContain('137'))
    expect(card.textContent).not.toContain('100+')
    expect(screen.queryByText('Residentes ativos')).toBeNull()
  })

  it('10. nenhum selo "Ativo" é inventado — a situação exibida é a real', async () => {
    responde()
    renderDashboard()
    expect(await screen.findByText(/^Em admissao •/)).toBeTruthy()
    expect(screen.queryByText('Ativo')).toBeNull()
  })
})

describe('Dashboard — experiência por perfil (UX-02 / #85)', () => {
  it('11. gestão vê o espelho da instituição primeiro e os processos em andamento', async () => {
    responde({
      resumo: resumo({
        ocupacao: { leitos_ativos: 4, ocupados: 3, livres: 1, indisponiveis: 0 },
        ausencias_ativas: { total: 1, hospitalizacoes: 1 },
        admissoes_em_andamento: 2,
        planos: { vigentes: 5, em_revisao: 1, em_elaboracao: 2, aprovados_aguardando_vigencia: 0 },
        equipe: { ativos: 12, afastados: 1 },
      }),
    })
    renderDashboard(GESTAO)
    await screen.findByText('Ocupação de leitos')
    await waitFor(() => expect(titulosDosIndicadores()[0]).toBe('Residentes cadastrados'))
    const processos = within(await screen.findByRole('region', { name: 'Processos em andamento' }))
    expect(processos.getByText('Em andamento').nextElementSibling?.textContent).toBe('2')
    expect(processos.getByText('Vigentes').nextElementSibling?.textContent).toBe('5')
    expect(processos.getByText('Afastados').nextElementSibling?.textContent).toBe('1')
    expect(screen.getByText('1 em hospitalização')).toBeTruthy()
  })

  it('12. operação vê primeiro o que fazer, sem processos de gestão', async () => {
    responde({ resumo: resumo({ residentes_total: 1, intercorrencias_abertas: 1 }) })
    renderDashboard(CUIDADO)
    await screen.findByText('Banho assistido')
    await waitFor(() => expect(titulosDosIndicadores()[0]).toBe('Pendências do turno'))
    expect(screen.queryByRole('region', { name: 'Processos em andamento' })).toBeNull()
    const acoes = within(screen.getByRole('region', { name: 'Ações rápidas' }))
    expect(acoes.getByRole('link', { name: /Registrar sinal vital/ })).toBeTruthy()
    expect(acoes.getByRole('link', { name: /Registrar intercorrência/ })).toBeTruthy()
    expect(acoes.queryByRole('link', { name: /Cadastrar residente/ })).toBeNull()
  })

  it('13. "Cadastrar residente" só aparece para quem pode criar', async () => {
    responde({ residentes: [] })
    const cuidador = renderDashboard(CUIDADO)
    expect(await screen.findByText('Nenhum residente cadastrado')).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Cadastrar residente' })).toBeNull()
    cuidador.unmount()

    responde({ residentes: [] })
    renderDashboard(GESTAO)
    expect(await screen.findByText('Nenhum residente cadastrado')).toBeTruthy()
    expect(screen.getAllByRole('link', { name: /Cadastrar residente/ }).length).toBeGreaterThan(0)
  })

  it('14. módulo sem permissão não é consultado', async () => {
    responde()
    renderDashboard(['intercorrencias:ler'])
    await screen.findByText('Intercorrências abertas')
    expect(urlsChamadas()).not.toContain('/plantao/')
    expect(urlsChamadas()).not.toContain('/residentes/')
  })
})

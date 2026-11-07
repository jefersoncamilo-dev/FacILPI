import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { Dashboard, noTurno } from '../pages/Dashboard'
import { api } from '../services/api'
import { contextApi } from '../services/context'
import { limparCentralAlertas } from '../hooks/useCentralAlertas'
import { DURACAO_ENTRADA } from '../hooks/useAnimarUmaVez'
import type { Alerta } from '../services/alertas'

/** UX-DASH-1: Início do gestor — indicadores, atenção, pendências por tipo, turno e movimento. */

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

const GESTOR = [
  'residentes:ler', 'plantao:ler', 'admissoes:ler', 'funcionarios:ler', 'quartos_leitos:ler',
  'alertas:ler', 'documentos:ler', 'estoque:ler', 'escala:ler',
]

function alerta(parcial: Partial<Alerta>): Alerta {
  return {
    id: parcial.regra ?? 'a', regra: 'documento_vencendo', categoria: 'admissao_documentos', gravidade: 'atencao', natureza: 'pendencia',
    titulo: 'Documento vencendo', detalhe: null, residente_id: 'res-1', residente_nome: 'Maria Silva', referencia_id: null,
    unidade: null, quarto: null, leito: null, local: null, desde: null, prazo: null, estado: null,
    ...parcial,
  }
}

const ALERTAS = [
  alerta({ id: 'd1', regra: 'doses_sem_registro', categoria: 'plantao', gravidade: 'critico', natureza: 'alerta', titulo: '2 doses de medicação sem registro' }),
  alerta({ id: 'v1', regra: 'documento_vencendo' }),
  alerta({ id: 'v2', regra: 'documento_vencendo', residente_nome: 'João Lima' }),
]

// 09:00 e 21:00 em São Paulo.
const PENDENCIAS = [
  { origem: 'cuidado', registro_id: 'c-1', residente_id: 'res-1', descricao: 'Banho assistido', previsto_em: '2026-09-15T12:00:00Z', prioridade: null },
  { origem: 'cuidado', registro_id: 'c-2', residente_id: 'res-1', descricao: 'Troca de curativo', previsto_em: '2026-09-16T00:00:00Z', prioridade: null },
]
const TURNOS = [
  { id: 't-m', nome: 'Manhã', hora_inicio: '07:00:00', hora_fim: '13:00:00', situacao: 'ativo' },
  { id: 't-t', nome: 'Tarde', hora_inicio: '13:00:00', hora_fim: '19:00:00', situacao: 'ativo' },
  { id: 't-n', nome: 'Noite', hora_inicio: '19:00:00', hora_fim: '07:00:00', situacao: 'ativo' },
]

type Fonte = unknown | Error
function responde(fontes: { alertas?: Fonte; estoque?: Fonte; admissoes?: number | null } = {}) {
  const de = (f: Fonte) => (f instanceof Error ? Promise.reject(f) : Promise.resolve({ data: f } as any))
  const central = fontes.alertas ?? ALERTAS
  mockGet.mockImplementation((url: string) => {
    if (url === '/dashboard/resumo') {
      return de({
        gerado_em: '2026-09-15T12:00:00Z', residentes_total: 3, ocupacao: null, ausencias_ativas: null, intercorrencias_abertas: null,
        admissoes_em_andamento: fontes.admissoes === undefined ? 2 : fontes.admissoes, planos: null, equipe: null,
      })
    }
    if (url === '/plantao/') return de(PENDENCIAS)
    if (url === '/residentes/') return de([{ id: 'res-1', nome: 'Maria Silva', situacao: null, grau_dependencia: null }])
    if (url === '/central-alertas/') {
      return de(central instanceof Error ? central : {
        gerado_em: '2026-09-15T12:00:00Z', fuso: 'America/Sao_Paulo',
        contagem: {
          total: (central as Alerta[]).length, critico: (central as Alerta[]).filter(a => a.gravidade === 'critico').length,
          atencao: 0, aviso: 0, alerta: 0, pendencia: 0, informativo: 0, atividade: 0,
        },
        alertas: central,
      })
    }
    if (url === '/estoque/itens') {
      return de(fontes.estoque ?? [{ id: 'i1', abaixo_do_minimo: true }, { id: 'i2', abaixo_do_minimo: false }, { id: 'i3', abaixo_do_minimo: true }])
    }
    if (url === '/escala/turnos') return de(TURNOS)
    throw new Error(`URL inesperada no Dashboard: ${url}`)
  })
}

function renderDashboard(permissoes: string[] = GESTOR) {
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

const urls = () => mockGet.mock.calls.map(c => String(c[0]))
const cartao = async (titulo: string) => (await screen.findByText(titulo)).closest('div.rounded-card') as HTMLElement
const titulos = () => within(screen.getByRole('region', { name: 'Indicadores' }))
  .getAllByText(/./, { selector: 'p.text-sm.font-medium' }).map(e => e.textContent)

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  limparCentralAlertas()
})

describe('UX-DASH-1 — indicadores do gestor', () => {
  it('admissões, documentos vencendo e estoque abaixo do mínimo, com estado em texto e borda do tom', async () => {
    responde()
    renderDashboard()
    await waitFor(() => expect(titulos()).toEqual(['Admissões abertas', 'Documentos vencendo', 'Estoque abaixo do mínimo', 'Residentes cadastrados']))
    const docs = await cartao('Documentos vencendo')
    await waitFor(() => expect(docs.textContent).toMatch(/Documentos vencendo\s*2Vencem em breve/))
    expect(docs.className).toContain('border-t-alerta')
    const estoque = await cartao('Estoque abaixo do mínimo')
    await waitFor(() => expect(estoque.textContent).toContain('Repor itens'))
    expect(estoque.textContent).toMatch(/mínimo\s*2/)
    expect((await cartao('Admissões abertas')).textContent).toContain('Em andamento')
  })

  it('estado positivo: zero com texto, não só cor', async () => {
    responde({ alertas: [], estoque: [{ id: 'i1', abaixo_do_minimo: false }], admissoes: 0 })
    renderDashboard()
    await waitFor(async () => expect((await cartao('Estoque abaixo do mínimo')).textContent).toContain('Estoque em dia'))
    expect((await cartao('Documentos vencendo')).textContent).toContain('Nenhum vencendo')
    expect((await cartao('Admissões abertas')).textContent).toContain('Nenhuma em aberto')
    expect(await screen.findByText('Nada pedindo ação agora.')).toBeTruthy()
  })

  it('falha do estoque vira traço, nunca zero; sem estoque:ler não consulta', async () => {
    responde({ estoque: new Error('rede') })
    const um = renderDashboard()
    const card = await cartao('Estoque abaixo do mínimo')
    await waitFor(() => expect(card.textContent).toContain('—'))
    expect(card.textContent).toContain('Indisponível no momento')
    um.unmount()

    vi.clearAllMocks()
    limparCentralAlertas()
    responde()
    renderDashboard(GESTOR.filter(p => p !== 'estoque:ler'))
    await screen.findByText('Admissões abertas')
    await screen.findByText('Documentos vencendo')
    expect(screen.queryByText('Estoque abaixo do mínimo')).toBeNull()
    expect(urls()).not.toContain('/estoque/itens')
  })
})

describe('UX-DASH-1 — atenção agora, pendências por tipo e frase do dia', () => {
  it('tabela com gravidade em ícone + texto e barras por categoria com valores', async () => {
    responde()
    renderDashboard([...GESTOR, 'administracoes:ler'])
    const tabela = await screen.findByRole('table')
    expect(within(tabela).getByText('Crítico')).toBeTruthy()
    expect(within(tabela).getByRole('link', { name: /2 doses de medicação sem registro/ })).toBeTruthy()
    const grafico = await screen.findByRole('img', { name: /^Pendências por tipo: / })
    expect(grafico.getAttribute('aria-label')).toContain('Admissão e documentos 2')
    expect(grafico.getAttribute('aria-label')).toContain('Plantão 1')
    expect(await screen.findByText(/Pede ação hoje: 1 residente com dose sem registro · 2 documentos vencendo ou vencidos · 1 alerta crítico\./)).toBeTruthy()
  })

  it('sem administracoes:ler a frase não fala de doses', async () => {
    responde({ alertas: ALERTAS.filter(a => a.regra !== 'doses_sem_registro') })
    renderDashboard()
    await screen.findByText(/Pede ação hoje/)
    expect(screen.queryByText(/dose/)).toBeNull()
  })

  it('só alertas de outros tipos: a frase não diz "nada pedindo ação"', async () => {
    responde({ alertas: [alerta({ id: 'g1', regra: 'grau_ausente', categoria: 'avaliacao_grau_pais', titulo: 'Sem grau de dependência confirmado' })] })
    renderDashboard()
    expect(await screen.findByText('Para acompanhar hoje: 1 alerta na central.')).toBeTruthy()
    expect(screen.queryByText('Nada pedindo ação agora.')).toBeNull()
  })

  it('central em erro: falha explícita, sem frase de "nada pendente"', async () => {
    responde({ alertas: new Error('rede') })
    renderDashboard()
    expect((await screen.findAllByText(/Isso não significa que não há pendências\./)).length).toBeGreaterThan(0)
    expect(screen.queryByText('Nada pedindo ação agora.')).toBeNull()
    expect(screen.queryByText('Nada pendente agora.')).toBeNull()
  })

  it('central vazia: estado positivo nos dois blocos', async () => {
    responde({ alertas: [] })
    renderDashboard()
    await waitFor(() => expect(screen.getAllByText('Nada pendente agora.')).toHaveLength(2))
  })
})

describe('UX-DASH-1 — filtro de turno', () => {
  it('filtra só as pendências do plantão, sem nova consulta e sem mexer nos indicadores', async () => {
    responde()
    renderDashboard()
    const grupo = await screen.findByRole('group', { name: 'Turno' })
    expect(screen.getByText(/Indicadores, alertas e ocupação valem para a casa toda/)).toBeTruthy()
    await screen.findByText('Banho assistido')
    const antes = urls().length
    const indicadores = () => screen.getByRole('region', { name: 'Indicadores' }).textContent

    const inicial = indicadores()
    await userEvent.click(within(grupo).getByRole('button', { name: 'Manhã' }))
    expect(within(grupo).getByRole('button', { name: 'Manhã' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByText('Banho assistido')).toBeTruthy()
    expect(screen.queryByText('Troca de curativo')).toBeNull()

    await userEvent.click(within(grupo).getByRole('button', { name: 'Noite' }))
    expect(screen.getByText('Troca de curativo')).toBeTruthy()
    expect(screen.queryByText('Banho assistido')).toBeNull()

    await userEvent.click(within(grupo).getByRole('button', { name: 'Tarde' }))
    expect(screen.getByText('Nada pendente neste turno.')).toBeTruthy()

    expect(indicadores()).toBe(inicial)
    expect(urls().length).toBe(antes)
  })

  it('sem leitura de turnos o filtro não aparece', async () => {
    responde()
    renderDashboard(GESTOR.filter(p => p !== 'escala:ler'))
    await screen.findByText('Banho assistido')
    expect(screen.queryByRole('group', { name: 'Turno' })).toBeNull()
    expect(urls()).not.toContain('/escala/turnos')
  })

  it('turno que vira a noite e item sem horário', () => {
    const noite = { hora_inicio: '19:00', hora_fim: '07:00' }
    expect(noTurno({ previsto_em: '2026-09-16T01:30:00Z' }, noite)).toBe(true) // 22:30
    expect(noTurno({ previsto_em: '2026-09-16T09:59:00Z' }, noite)).toBe(true) // 06:59
    expect(noTurno({ previsto_em: '2026-09-16T10:00:00Z' }, noite)).toBe(false) // 07:00
    expect(noTurno({ previsto_em: null }, noite)).toBe(true)
  })
})

describe('UX-DASH-1 — movimento só na primeira abertura', () => {
  it('cartões entram animados uma vez; trocar o turno não repete', async () => {
    responde()
    renderDashboard()
    const card = await cartao('Admissões abertas')
    await waitFor(() => expect(card.className).toContain('animar-entrada'))
    await waitFor(() => expect(card.className).not.toContain('animar-entrada'), { timeout: DURACAO_ENTRADA + 1500 })
    const grupo = await screen.findByRole('group', { name: 'Turno' })
    await userEvent.click(within(grupo).getByRole('button', { name: 'Manhã' }))
    expect((await cartao('Admissões abertas')).className).not.toContain('animar-entrada')
    expect(document.querySelector('.animar-crescer-x, .animar-crescer-y, .animar-entrada')).toBeNull()
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { Layout } from '../components/Layout'
import { Alertas } from '../pages/Alertas'
import { Dashboard } from '../pages/Dashboard'
import { api } from '../services/api'
import { contextApi } from '../services/context'
import { quandoDoAlerta, type Alerta, type CentralAlertas } from '../services/alertas'
import { limparCentralAlertas } from '../hooks/useCentralAlertas'
import { TOKEN_KEY, USER_KEY, CONTEXT_KEY } from '../types/context'

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
  logoutServidor: vi.fn(async () => ({ data: {} })),
}))

const mockGet = vi.mocked(api.get)
const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

type Base = Pick<Alerta, 'regra' | 'categoria' | 'gravidade' | 'natureza' | 'titulo'>
function alerta(parcial: Partial<Alerta> & Base): Alerta {
  return {
    id: `${parcial.regra}:${parcial.referencia_id ?? 'x'}`,
    detalhe: null, residente_id: 'res-1', residente_nome: 'Benedito Carvalho', referencia_id: 'ref-1',
    unidade: null, quarto: null, leito: null, local: null, desde: null, prazo: null,
    ...parcial,
  }
}

// Já na ordem do backend (#117): gravidade, alerta antes de pendência, mais atrasado primeiro.
const ALERTAS: Alerta[] = [
  alerta({
    regra: 'doses_sem_registro', categoria: 'plantao', gravidade: 'critico', natureza: 'alerta', titulo: '2 doses de medicação sem registro',
    referencia_id: 'res-1', unidade: 'Ala B', quarto: '12', leito: 'A', local: 'Ala B · Quarto 12 · Leito A',
    desde: '2026-09-26T14:42:00Z', prazo: '2026-09-26T14:42:00Z',
  }),
  alerta({ regra: 'admissao_parada', categoria: 'admissao_documentos', gravidade: 'atencao', natureza: 'pendencia', titulo: 'Admissão parada em Avaliações', referencia_id: 'adm-9', detalhe: 'Sem avanço há 9 dias.' }),
  alerta({ regra: 'documento_aguardando_validacao', categoria: 'admissao_documentos', gravidade: 'atencao', natureza: 'pendencia', titulo: 'Documento obrigatório aguardando validação: RG', referencia_id: 'doc-1' }),
  alerta({ regra: 'acesso_nao_utilizado', categoria: 'ocupacao_equipe', gravidade: 'aviso', natureza: 'pendencia', titulo: 'Acesso ainda não utilizado: Tiago Ramos', residente_id: null, residente_nome: null, referencia_id: 'func-1' }),
]

function central(alertas: Alerta[] = ALERTAS): CentralAlertas {
  const contagem = { critico: 0, atencao: 0, aviso: 0, alerta: 0, pendencia: 0, informativo: 0, atividade: 0, total: alertas.length }
  alertas.forEach(a => { contagem[a.gravidade] += 1; contagem[a.natureza] += 1 })
  return { gerado_em: '2026-09-26T15:00:00Z', contagem, alertas }
}

type Fonte = CentralAlertas | Error | { response: { status: number } }
let fonteAtual: Fonte = central()
function responde(fonte: Fonte = central()) {
  fonteAtual = fonte
  mockGet.mockImplementation((url: string) => {
    if (url === '/central-alertas/') {
      const f = fonteAtual
      if (f instanceof Error || 'response' in f) return Promise.reject(f)
      return Promise.resolve({ data: f } as any)
    }
    if (url === '/dashboard/resumo') {
      return Promise.resolve({ data: {
        gerado_em: '2026-09-26T15:00:00Z', residentes_total: 12, ocupacao: null, ausencias_ativas: null,
        intercorrencias_abertas: null, admissoes_em_andamento: null, planos: null, equipe: null,
      } } as any)
    }
    return Promise.resolve({ data: [] } as any)
  })
}

function renderPagina() {
  return render(<MemoryRouter><Alertas /></MemoryRouter>)
}

function seedSessao() {
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  const exp = Math.floor(Date.now() / 1000) + 3600
  localStorage.setItem(TOKEN_KEY, `${b64({ alg: 'HS256' })}.${b64({ sub: 'u1', scope: 'ilpi', ilpi_id: 'ilpi1', perfil_id: 'p1', exp })}.sig`)
  localStorage.setItem(USER_KEY, JSON.stringify({ id: 'u1', nome: 'Gestora', email: 'gestora@example.com' }))
  localStorage.setItem(CONTEXT_KEY, JSON.stringify({ scope: 'ilpi', ilpi_id: 'ilpi1' }))
}

function comPermissoes(permissoes: string[]) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', ilpi_id: 'ilpi1', permissoes } } as any)
}

const chamouAlertas = () => mockGet.mock.calls.filter(c => c[0] === '/central-alertas/').length

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  limparCentralAlertas()
})

describe('Alertas e Pendências (#107, #117) — página', () => {
  it('prioridade agora com os críticos e cada cartão leva à ação na origem', async () => {
    responde()
    renderPagina()
    expect(await screen.findByRole('heading', { name: 'Alertas e Pendências' })).toBeTruthy()
    expect(screen.getByText('Situações que precisam da sua atenção, ação ou acompanhamento.')).toBeTruthy()

    const prioridade = await screen.findByRole('region', { name: 'Prioridade agora (1)' })
    expect(within(prioridade).getByText('2 doses de medicação sem registro')).toBeTruthy()
    // O Meu Plantão abre a partir do horário mais antigo sem registro, para o atraso aparecer na lista.
    expect(within(prioridade).getByRole('link', { name: 'Registrar doses em Meu Plantão' }).getAttribute('href'))
      .toBe('/plantao?desde=2026-09-26T14%3A42%3A00Z')

    const demais = screen.getByRole('region', { name: 'Demais (3)' })
    expect(within(demais).getByRole('link', { name: 'Continuar admissão em Admissões' }).getAttribute('href')).toBe('/admissoes/adm-9')
    expect(within(demais).getByText(/Sem avanço há 9 dias/)).toBeTruthy()
    expect(within(demais).getByRole('link', { name: 'Validar documento em Documentos' }).getAttribute('href')).toBe('/documentos')
    expect(within(demais).getByRole('link', { name: 'Ver equipe em Equipe' }).getAttribute('href')).toBe('/equipe')
    // A tela respeita a ordem do backend.
    const titulos = within(demais).getAllByRole('listitem').map(li => li.querySelector('p')?.textContent)
    expect(titulos).toEqual([
      'Atenção: Admissão parada em Avaliações',
      'Atenção: Documento obrigatório aguardando validação: RG',
      'Aviso: Acesso ainda não utilizado: Tiago Ramos',
    ])

    const resumo = screen.getByRole('list', { name: 'Resumo' })
    expect(resumo.textContent).toContain('Críticos: 1')
    expect(resumo.textContent).toContain('Atenção: 2')
    expect(resumo.textContent).toContain('Pendências: 3')
  })

  it('o cartão responde com quem, onde e quando', async () => {
    responde()
    renderPagina()
    const prioridade = await screen.findByRole('region', { name: 'Prioridade agora (1)' })
    expect(within(prioridade).getByText('Benedito Carvalho')).toBeTruthy()
    expect(within(prioridade).getByText('Ala B · Quarto 12 · Leito A')).toBeTruthy()
    expect(within(prioridade).getByText(/^Alerta · atrasado há /)).toBeTruthy()
  })

  it('abas: Críticos e Atenção por gravidade; Pendências por natureza', async () => {
    const itens = [
      ...ALERTAS,
      alerta({ regra: 'pais_ausente', categoria: 'avaliacao_grau_pais', gravidade: 'critico', natureza: 'pendencia', titulo: 'Sem PAIS vigente', referencia_id: 'res-2' }),
      alerta({ regra: 'intercorrencia_aberta_prolongada', categoria: 'plantao', gravidade: 'atencao', natureza: 'alerta', titulo: 'Intercorrência aberta há mais de 24 horas: Febre', referencia_id: 'int-1' }),
    ]
    responde(central(itens))
    renderPagina()
    await screen.findByText('2 doses de medicação sem registro')

    await userEvent.click(screen.getByRole('tab', { name: /Críticos \(2\)/ }))
    expect(screen.getByText('Sem PAIS vigente')).toBeTruthy()
    expect(screen.queryByText('Admissão parada em Avaliações')).toBeNull()

    await userEvent.click(screen.getByRole('tab', { name: /Atenção \(3\)/ }))
    expect(screen.getByText('Intercorrência aberta há mais de 24 horas: Febre')).toBeTruthy()
    expect(screen.queryByText('2 doses de medicação sem registro')).toBeNull()

    // Pendência é natureza: entra o crítico "Sem PAIS vigente"; sai a intercorrência (alerta de atenção).
    await userEvent.click(screen.getByRole('tab', { name: /Pendências \(4\)/ }))
    expect(screen.getByText('Sem PAIS vigente')).toBeTruthy()
    expect(screen.getByText('Acesso ainda não utilizado: Tiago Ramos')).toBeTruthy()
    expect(screen.queryByText('Intercorrência aberta há mais de 24 horas: Febre')).toBeNull()
    expect(screen.queryByText('2 doses de medicação sem registro')).toBeNull()
  })

  it('sem alertas mostra o estado vazio honesto', async () => {
    responde(central([]))
    renderPagina()
    expect(await screen.findByText('Nada pedindo atenção agora')).toBeTruthy()
  })

  it('falha na consulta não vira "sem pendências"', async () => {
    responde(new Error('rede'))
    renderPagina()
    expect(await screen.findByText('Não foi possível carregar os alertas')).toBeTruthy()
    expect(screen.getByText(/Isso não significa que não há pendências/)).toBeTruthy()
    expect(screen.queryByText('Nada pedindo atenção agora')).toBeNull()
  })

  it('403 explica o acesso sem dizer que é só do administrador', async () => {
    responde({ response: { status: 403 } })
    renderPagina()
    expect(await screen.findByText('Sem acesso aos alertas')).toBeTruthy()
    expect(screen.getByText(/Seu perfil não inclui a Central de Alertas/)).toBeTruthy()
  })
})

describe('quandoDoAlerta (#117)', () => {
  const agora = new Date('2026-09-26T15:00:00Z') // 12:00 em São Paulo
  it('origem sem prazo: há …', () => {
    expect(quandoDoAlerta({ natureza: 'alerta', desde: '2026-09-26T14:57:00Z', prazo: null }, agora)).toBe('há 3 min')
    expect(quandoDoAlerta({ natureza: 'alerta', desde: '2026-09-26T13:00:00Z', prazo: null }, agora)).toBe('há 2 h')
    expect(quandoDoAlerta({ natureza: 'pendencia', desde: '2026-09-25T14:00:00Z', prazo: null }, agora)).toBe('há 1 dia')
    expect(quandoDoAlerta({ natureza: 'pendencia', desde: null, prazo: null }, agora)).toBeNull()
  })
  it('prazo futuro em dias de calendário da ILPI (validade D vence às 00:00 de D+1)', () => {
    expect(quandoDoAlerta({ natureza: 'pendencia', desde: null, prazo: '2026-09-27T03:00:00Z' }, agora)).toBe('vence hoje')
    expect(quandoDoAlerta({ natureza: 'pendencia', desde: null, prazo: '2026-09-28T03:00:00Z' }, agora)).toBe('vence amanhã')
    expect(quandoDoAlerta({ natureza: 'pendencia', desde: null, prazo: '2026-09-30T03:00:00Z' }, agora)).toBe('vence em 3 dias')
  })
  it('usa o fuso da ILPI informado pelo backend (não o de São Paulo)', () => {
    // Manaus (UTC-4): validade 26/09 vence às 00:00 de 27/09 em Manaus = 04:00Z.
    const prazo = '2026-09-27T04:00:00Z'
    expect(quandoDoAlerta({ natureza: 'pendencia', desde: null, prazo }, agora, 'America/Manaus')).toBe('vence hoje')
    // Com o fuso de São Paulo o último instante válido cairia em 27/09 (o defeito evitado).
    expect(quandoDoAlerta({ natureza: 'pendencia', desde: null, prazo }, agora)).toBe('vence amanhã')
  })
  it('prazo passado: atrasado (alerta) ou venceu (pendência)', () => {
    const doze = '2026-09-26T14:42:00Z'
    expect(quandoDoAlerta({ natureza: 'alerta', desde: doze, prazo: doze }, agora)).toBe('atrasado há 18 min')
    expect(quandoDoAlerta({ natureza: 'pendencia', desde: '2026-09-24T03:00:00Z', prazo: '2026-09-24T03:00:00Z' }, agora)).toBe('venceu há 2 dias')
  })
})

describe('Sino, navegação inferior e Início (#107, #117)', () => {
  function renderShell(filho = <div>conteúdo</div>, rota = '/') {
    seedSessao()
    return render(
      <AuthProvider>
        <MemoryRouter initialEntries={[rota]}>
          <Layout>{filho}</Layout>
        </MemoryRouter>
      </AuthProvider>,
    )
  }

  it('o sino é triagem rápida: totais, até 5 itens na ordem do backend e o caminho para a Central', async () => {
    const muitos = [
      ...ALERTAS,
      ...[1, 2, 3].map(i => alerta({ regra: 'documento_vencendo', categoria: 'admissao_documentos', gravidade: 'aviso', natureza: 'pendencia', titulo: `Documento vence em breve: ${i}`, referencia_id: `doc-v${i}` })),
    ]
    comPermissoes(['alertas:ler', 'residentes:ler'])
    responde(central(muitos))
    renderShell()
    const sinos = await screen.findAllByRole('button', { name: 'Alertas: 3 pedem atenção' })
    // Um cabeçalho por tamanho de tela, uma consulta só.
    expect(chamouAlertas()).toBe(1)

    await userEvent.click(sinos[0])
    const menu = await screen.findByRole('menu')
    expect(within(menu).getByLabelText('Totais').textContent).toBe('Críticos: 1 · Atenção: 2 · Pendências: 6')
    const itens = within(menu).getAllByRole('menuitem')
    const titulos = itens.slice(0, -1).map(i => i.querySelector('span > span')?.textContent)
    expect(titulos).toEqual([
      '2 doses de medicação sem registro',
      'Admissão parada em Avaliações',
      'Documento obrigatório aguardando validação: RG',
      'Acesso ainda não utilizado: Tiago Ramos',
      'Documento vence em breve: 1',
    ])
    expect(itens[0].getAttribute('href')).toBe('/plantao?desde=2026-09-26T14%3A42%3A00Z')
    const central_ = itens[itens.length - 1]
    expect(central_.textContent).toContain('Ver Central de Alertas')
    expect(central_.getAttribute('href')).toBe('/alertas')
    expect(chamouAlertas()).toBe(1)
  })

  it('sem alertas:ler não há sino, item de menu, navegação inferior nem consulta', async () => {
    comPermissoes(['residentes:ler'])
    responde()
    renderShell()
    await within(screen.getByRole('navigation', { name: 'Navegação principal' })).findByRole('link', { name: /Residentes/ })
    expect(screen.queryByRole('button', { name: /^Alertas/ })).toBeNull()
    expect(screen.queryByRole('link', { name: /^Alertas/ })).toBeNull()
    expect(chamouAlertas()).toBe(0)
  })

  it('mobile: Alertas na navegação inferior com o mesmo número do sino', async () => {
    comPermissoes(['alertas:ler', 'residentes:ler'])
    responde()
    renderShell()
    const rapida = screen.getByRole('navigation', { name: 'Navegação rápida' })
    const link = await within(rapida).findByRole('link', { name: 'Alertas: 3 pedem atenção' })
    expect(link.getAttribute('href')).toBe('/alertas')
    expect(chamouAlertas()).toBe(1)
  })

  it('sino e Central concordam: atualizar a Central atualiza o sino', async () => {
    comPermissoes(['alertas:ler', 'residentes:ler'])
    responde()
    renderShell(<Alertas />, '/alertas')
    await screen.findByRole('region', { name: 'Prioridade agora (1)' })
    expect((await screen.findAllByRole('button', { name: 'Alertas: 3 pedem atenção' })).length).toBeGreaterThan(0)

    // A fonte resolveu a dose e a admissão: o próximo retrato é o mesmo para os dois.
    responde(central(ALERTAS.slice(2)))
    await userEvent.click(screen.getByRole('button', { name: /Atualizar/ }))
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Alertas: 1 pede atenção' }).length).toBeGreaterThan(0))
    expect(screen.queryByRole('region', { name: /Prioridade agora/ })).toBeNull()
    expect(screen.getByRole('list', { name: 'Resumo' }).textContent).toContain('Atenção: 1')
  })

  function renderInicio(permissoes: string[]) {
    comPermissoes(permissoes)
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

  it('o Início mostra "Precisa de atenção" com os primeiros alertas', async () => {
    responde()
    renderInicio(['alertas:ler', 'residentes:ler', 'funcionarios:ler'])
    const painel = await screen.findByRole('region', { name: 'Precisa de atenção' })
    await waitFor(() => expect(within(painel).getByText('2 doses de medicação sem registro')).toBeTruthy())
    expect(within(painel).getByText('Crítico: 1 · Atenção: 2 · Aviso: 1')).toBeTruthy()
    expect(within(painel).getByRole('link', { name: 'Ver todos os alertas' }).getAttribute('href')).toBe('/alertas')
  })

  it('o Início sem alertas:ler não consulta nem mostra o painel', async () => {
    responde()
    renderInicio(['residentes:ler', 'funcionarios:ler'])
    await screen.findByText('Residentes cadastrados')
    expect(screen.queryByRole('region', { name: 'Precisa de atenção' })).toBeNull()
    expect(chamouAlertas()).toBe(0)
  })
})

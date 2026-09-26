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
import { haQuantoTempo, type Alerta, type CentralAlertas } from '../services/alertas'
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

function alerta(parcial: Partial<Alerta> & Pick<Alerta, 'regra' | 'categoria' | 'gravidade' | 'titulo'>): Alerta {
  return {
    id: `${parcial.regra}:${parcial.referencia_id ?? 'x'}`,
    detalhe: null, residente_id: 'res-1', residente_nome: 'Benedito Carvalho', referencia_id: 'ref-1', desde: null,
    ...parcial,
  }
}

const ALERTAS: Alerta[] = [
  alerta({ regra: 'doses_sem_registro', categoria: 'plantao', gravidade: 'critico', titulo: '2 doses de medicação sem registro', referencia_id: 'res-1' }),
  alerta({ regra: 'admissao_parada', categoria: 'admissao_documentos', gravidade: 'atencao', titulo: 'Admissão parada em Avaliações', referencia_id: 'adm-9', detalhe: 'Sem avanço há 9 dias.' }),
  alerta({ regra: 'documento_aguardando_validacao', categoria: 'admissao_documentos', gravidade: 'atencao', titulo: 'Documento obrigatório aguardando validação: RG', referencia_id: 'doc-1' }),
  alerta({ regra: 'acesso_nao_utilizado', categoria: 'ocupacao_equipe', gravidade: 'aviso', titulo: 'Acesso ainda não utilizado: Tiago Ramos', residente_id: null, residente_nome: null, referencia_id: 'func-1' }),
]

function central(alertas: Alerta[] = ALERTAS): CentralAlertas {
  const contagem = { critico: 0, atencao: 0, aviso: 0 }
  alertas.forEach(a => { contagem[a.gravidade] += 1 })
  return { gerado_em: '2026-09-26T15:00:00Z', contagem, alertas }
}

type Fonte = CentralAlertas | Error | { response: { status: number } }
function responde(fonte: Fonte = central()) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/central-alertas/') {
      if (fonte instanceof Error || 'response' in fonte) return Promise.reject(fonte)
      return Promise.resolve({ data: fonte } as any)
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
})

describe('Central de alertas (#107) — página', () => {
  it('agrupa por gravidade e cada alerta leva à tela onde é resolvido', async () => {
    responde()
    renderPagina()
    const criticos = await screen.findByRole('region', { name: 'Crítico (1)' })
    expect(within(criticos).getByText('2 doses de medicação sem registro')).toBeTruthy()
    expect(within(criticos).getByRole('link', { name: /Resolver em Meu Plantão/ }).getAttribute('href')).toBe('/plantao')

    const atencao = screen.getByRole('region', { name: 'Atenção (2)' })
    expect(within(atencao).getByRole('link', { name: /Resolver em Admissões/ }).getAttribute('href')).toBe('/admissoes/adm-9')
    expect(within(atencao).getByText(/Sem avanço há 9 dias/)).toBeTruthy()
    expect(within(atencao).getByRole('link', { name: /Resolver em Documentos/ }).getAttribute('href')).toBe('/documentos')

    const avisos = screen.getByRole('region', { name: 'Aviso (1)' })
    expect(within(avisos).getByRole('link', { name: /Resolver em Equipe/ }).getAttribute('href')).toBe('/equipe')

    const resumo = screen.getByRole('list', { name: 'Resumo por gravidade' })
    expect(resumo.textContent).toContain('Crítico: 1')
    expect(resumo.textContent).toContain('Atenção: 2')
    expect(resumo.textContent).toContain('Aviso: 1')
  })

  it('filtra por categoria', async () => {
    responde()
    renderPagina()
    await screen.findByText('2 doses de medicação sem registro')
    await userEvent.click(screen.getByRole('tab', { name: /Admissão e documentos \(2\)/ }))
    expect(screen.queryByText('2 doses de medicação sem registro')).toBeNull()
    expect(screen.getByText('Admissão parada em Avaliações')).toBeTruthy()
    await userEvent.click(screen.getByRole('tab', { name: /Ocupação e equipe/ }))
    expect(screen.getByText('Acesso ainda não utilizado: Tiago Ramos')).toBeTruthy()
    expect(screen.queryByText('Admissão parada em Avaliações')).toBeNull()
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

  it('403 explica o acesso', async () => {
    responde({ response: { status: 403 } })
    renderPagina()
    expect(await screen.findByText('Sem acesso aos alertas')).toBeTruthy()
  })

  it('tempo desde o início do problema em linguagem simples', () => {
    const agora = new Date('2026-09-26T15:00:00Z')
    expect(haQuantoTempo('2026-09-26T14:30:00Z', agora)).toBe('há poucos minutos')
    expect(haQuantoTempo('2026-09-26T13:00:00Z', agora)).toBe('há 2 horas')
    expect(haQuantoTempo('2026-09-25T14:00:00Z', agora)).toBe('há 1 dia')
    expect(haQuantoTempo(null, agora)).toBeNull()
  })
})

describe('Central de alertas (#107) — sino e Início', () => {
  function renderShell() {
    seedSessao()
    return render(
      <AuthProvider>
        <MemoryRouter initialEntries={['/']}>
          <Layout><div>conteúdo</div></Layout>
        </MemoryRouter>
      </AuthProvider>,
    )
  }

  it('o sino mostra quantos pedem atenção (crítico + atenção) e leva a /alertas', async () => {
    comPermissoes(['alertas:ler', 'residentes:ler'])
    responde()
    renderShell()
    const sinos = await screen.findAllByRole('link', { name: 'Alertas: 3 pedem atenção' })
    expect(sinos.length).toBeGreaterThan(0)
    expect(sinos[0].getAttribute('href')).toBe('/alertas')
    // Um cabeçalho por tamanho de tela, uma consulta só.
    expect(chamouAlertas()).toBe(1)
    expect(within(screen.getByRole('navigation', { name: 'Navegação principal' })).getByRole('link', { name: /Alertas/ })).toBeTruthy()
  })

  it('sem alertas:ler não há sino, item de menu nem consulta', async () => {
    comPermissoes(['residentes:ler'])
    responde()
    renderShell()
    await within(screen.getByRole('navigation', { name: 'Navegação principal' })).findByRole('link', { name: /Residentes/ })
    expect(screen.queryByRole('link', { name: /^Alertas/ })).toBeNull()
    expect(chamouAlertas()).toBe(0)
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

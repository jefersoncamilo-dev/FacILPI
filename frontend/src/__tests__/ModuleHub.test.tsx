import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { Layout } from '../components/Layout'
import { ModuleHub } from '../pages/ModuleHub'
import { api } from '../services/api'
import { contextApi } from '../services/context'
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

const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

function jwt(payload: object): string {
  const b64 = (o: object) =>
    btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${b64({ alg: 'HS256' })}.${b64(payload)}.sig`
}

function seedSessao() {
  const exp = Math.floor(Date.now() / 1000) + 3600
  localStorage.setItem(TOKEN_KEY, jwt({ sub: 'u1', exp }))
  localStorage.setItem(USER_KEY, JSON.stringify({ id: 'u1', nome: 'gestora', email: 'gestora@ilpi.com' }))
  localStorage.setItem(CONTEXT_KEY, JSON.stringify({ scope: 'ilpi', ilpi_id: 'ilpi1' }))
}

function comPermissoes(permissoes: string[]) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', ilpi_id: 'ilpi1', permissoes } } as any)
}

function renderEm(rota: string) {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[rota]}>
        <Layout>
          <Routes>
            <Route path="/" element={<p>tela início</p>} />
            <Route path="/modulos/:modulo" element={<ModuleHub />} />
            <Route path="/residentes" element={<p>tela residentes</p>} />
            <Route path="/residentes/:id" element={<p>tela prontuário</p>} />
            <Route path="/sinais" element={<p>tela sinais</p>} />
          </Routes>
        </Layout>
      </MemoryRouter>
    </AuthProvider>,
  )
}

const principal = () => within(screen.getByRole('main'))
const menu = () => within(screen.getByRole('navigation', { name: 'Navegação principal' }))

/** Destinos dos cards do hub, na ordem exibida. */
async function cardsDoHub(titulo: string) {
  await principal().findByRole('heading', { level: 1, name: titulo })
  const lista = await principal().findByRole('list')
  return within(lista).getAllByRole('link').map(l => l.getAttribute('href'))
}

const TODAS = [
  'residentes:ler', 'admissoes:ler', 'documentos:ler', 'quartos_leitos:ler',
  'sinais_vitais:ler', 'intercorrencias:ler', 'plantao:ler', 'avaliacoes:ler', 'planos_cuidados:ler',
]

const CONTAGEM_VAZIA = { critico: 0, atencao: 0, aviso: 0, alerta: 0, pendencia: 0, informativo: 0, atividade: 0, total: 0 }

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
  // A central de alertas é um store de módulo: sempre no formato real (vazia).
  vi.mocked(api.get).mockImplementation(async (url: string) =>
    url === '/central-alertas/'
      ? ({ data: { gerado_em: '2026-10-01T12:00:00Z', alertas: [], contagem: CONTAGEM_VAZIA } } as any)
      : ({ data: [] } as any),
  )
  seedSessao()
})

describe('UX-00C — hub do módulo', () => {
  it('acesso parcial: lista só as telas permitidas, cada card inteiro é o link', async () => {
    comPermissoes(['residentes:ler', 'documentos:ler'])
    renderEm('/modulos/residentes')

    expect(await cardsDoHub('Residentes')).toEqual(['/residentes', '/documentos'])
    expect(principal().queryByRole('button', { name: /Abrir/ })).toBeNull()
    expect(principal().getByRole('link', { name: /Documentos/ }).textContent).toContain('Documentos dos residentes e validação.')
  })

  it('item futuro nunca aparece, nem com permissões indisponíveis', async () => {
    mockPermissoes.mockRejectedValue({ response: { status: 404, data: { detail: 'Not Found' } } })
    renderEm('/modulos/residentes')
    expect(await cardsDoHub('Residentes')).toEqual(['/residentes', '/admissoes', '/documentos', '/quartos'])
    expect(principal().queryByText('Estoque do Residente')).toBeNull()
  })

  it('Multidisciplinar mostra só Avaliações e Plano, sem as áreas futuras', async () => {
    comPermissoes(TODAS)
    renderEm('/modulos/multidisciplinar')
    expect(await cardsDoHub('Multidisciplinar')).toEqual(['/avaliacoes', '/plano'])
    for (const area of ['Fisioterapia', 'Nutrição', 'Psicologia', 'Serviço Social', 'Enfermagem']) {
      expect(screen.queryByText(area)).toBeNull()
    }
  })

  it('módulo válido sem item permitido mostra "Sem acesso a este módulo"', async () => {
    comPermissoes(['residentes:ler'])
    renderEm('/modulos/equipe')
    expect(await principal().findByText('Sem acesso a este módulo')).toBeTruthy()
    expect(principal().getByRole('link', { name: 'Voltar ao início' }).getAttribute('href')).toBe('/')
    expect(principal().queryByRole('list')).toBeNull()
    expect(menu().queryByRole('button', { name: 'Submenu de Equipe' })).toBeNull()
  })

  it.each(['/modulos/nao-existe', '/modulos/farmacia', '/modulos/gestao', '/modulos/plantao'])(
    'slug inválido, futuro ou sem hub (%s) volta ao Início',
    async rota => {
      comPermissoes(TODAS)
      renderEm(rota)
      expect(await principal().findByText('tela início')).toBeTruthy()
    },
  )
})

describe('UX-00C — sidebar híbrida', () => {
  it('clique no nome do módulo abre o hub e expande o grupo', async () => {
    const user = userEvent.setup()
    comPermissoes(TODAS)
    renderEm('/')

    await user.click(await menu().findByRole('link', { name: 'Assistencial' }))
    expect(await cardsDoHub('Assistencial')).toEqual(['/sinais', '/intercorrencias', '/passagem'])
    expect(menu().getByRole('button', { name: 'Submenu de Assistencial' }).getAttribute('aria-expanded')).toBe('true')
    expect(menu().getByRole('link', { name: 'Assistencial' }).getAttribute('aria-current')).toBe('page')
  })

  it('chevron só expande/recolhe, sem navegar', async () => {
    const user = userEvent.setup()
    comPermissoes(TODAS)
    renderEm('/')

    const chevron = await menu().findByRole('button', { name: 'Submenu de Residentes' })
    await user.click(chevron)
    expect(chevron.getAttribute('aria-expanded')).toBe('true')
    expect(principal().getByText('tela início')).toBeTruthy()
    await user.click(chevron)
    expect(chevron.getAttribute('aria-expanded')).toBe('false')
    expect(principal().getByText('tela início')).toBeTruthy()
  })

  it('deep links antigos continuam funcionando e destacam o item', async () => {
    comPermissoes(TODAS)
    renderEm('/residentes/abc')

    expect(await principal().findByText('tela prontuário')).toBeTruthy()
    expect((await menu().findByRole('button', { name: 'Submenu de Residentes' })).getAttribute('aria-expanded')).toBe('true')
    const item = menu().getAllByRole('link', { name: 'Residentes' }).find(l => l.getAttribute('href') === '/residentes')
    expect(item?.getAttribute('aria-current')).toBe('page')
  })

  it('deep link de item relocado (/sinais) abre o grupo Assistencial', async () => {
    comPermissoes(TODAS)
    renderEm('/sinais')
    expect(await principal().findByText('tela sinais')).toBeTruthy()
    expect((await menu().findByRole('button', { name: 'Submenu de Assistencial' })).getAttribute('aria-expanded')).toBe('true')
  })
})

describe('UX-00D — navegação inferior e sessão restrita', () => {
  const rapida = () => within(screen.getByRole('navigation', { name: 'Navegação rápida' }))

  it('ordem Início · Alertas · Plantão · Residentes · Mais', async () => {
    comPermissoes(['alertas:ler', 'plantao:ler', 'residentes:ler'])
    renderEm('/')
    await rapida().findByRole('link', { name: /^Alertas/ })
    const destinos = [...screen.getByRole('navigation', { name: 'Navegação rápida' }).querySelectorAll('a, button')]
    expect(destinos.map(d => d.textContent?.replace(/\d+|:.*$/g, '').trim())).toEqual(['Início', 'Alertas', 'Plantão', 'Residentes', 'Mais'])
    expect(rapida().queryByRole('button', { name: 'Menu' })).toBeNull()
  })

  it('"Mais" abre o Sheet só com os módulos permitidos e fecha ao navegar', async () => {
    const user = userEvent.setup()
    comPermissoes(['sinais_vitais:ler'])
    renderEm('/')

    const mais = await rapida().findByRole('button', { name: 'Mais' })
    expect(mais.getAttribute('aria-expanded')).toBe('false')
    await user.click(mais)
    const sheet = within(await screen.findByRole('dialog', { name: 'Menu de navegação' }))
    expect(mais.getAttribute('aria-expanded')).toBe('true')
    expect(sheet.getAllByRole('link').map(l => l.getAttribute('href')).filter(h => h?.startsWith('/modulos/'))).toEqual(['/modulos/assistencial'])

    await user.click(sheet.getByRole('link', { name: 'Assistencial' }))
    expect(await cardsDoHub('Assistencial')).toEqual(['/sinais'])
    expect(screen.queryByRole('dialog', { name: 'Menu de navegação' })).toBeNull()
  })

  it('só sinais_vitais:ler: Assistencial com Sinais Vitais e nada mais', async () => {
    comPermissoes(['sinais_vitais:ler'])
    renderEm('/modulos/assistencial')

    expect(await cardsDoHub('Assistencial')).toEqual(['/sinais'])
    const hrefs = menu().getAllByRole('link', { hidden: true }).map(l => l.getAttribute('href'))
    expect(hrefs).toEqual(['/', '/modulos/assistencial', '/sinais'])
    expect(menu().getAllByRole('button', { name: /^Submenu de/ }).map(b => b.getAttribute('aria-label'))).toEqual(['Submenu de Assistencial'])
    expect(rapida().queryByRole('link', { name: /Plantão|Residentes|Alertas/ })).toBeNull()
  })

  it('só sinais_vitais:ler: hub de outro módulo mostra "Sem acesso"', async () => {
    comPermissoes(['sinais_vitais:ler'])
    renderEm('/modulos/residentes')
    expect(await principal().findByText('Sem acesso a este módulo')).toBeTruthy()
  })
})

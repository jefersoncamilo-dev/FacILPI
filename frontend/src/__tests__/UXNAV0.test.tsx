import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { SinaisVitais } from '../pages/SinaisVitais'
import { AbasModulo } from '../components/modulo/AbasModulo'
import { BotaoVoltar } from '../components/modulo/BotaoVoltar'
import { LinkResidente } from '../components/modulo/LinkResidente'
import { PaginaModulo } from '../components/modulo/PaginaModulo'
import { api } from '../services/api'

// Dados sintéticos: nomes fictícios, nenhum dado real.
vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }
})
const mockGet = vi.mocked(api.get)

const RESIDENTES = [
  { id: 'res-1', nome: 'Ana Sintética' },
  { id: 'res-2', nome: 'Beto Exemplo' },
]
const HOJE = new Date().toISOString()
const REGISTROS = [
  { id: 'sv-hoje', residente_id: 'res-1', temperatura: 36.5, profissional: 'Enf. Teste', data: HOJE },
  { id: 'sv-antigo', residente_id: 'res-2', saturacao: 96, profissional: 'Enf. Teste', data: '2026-01-10T12:00:00Z' },
]

function respondeCom() {
  mockGet.mockImplementation((url: string) => {
    if (url === '/sinais-vitais/') return Promise.resolve({ data: REGISTROS } as any)
    if (url === '/residentes/') return Promise.resolve({ data: RESIDENTES } as any)
    throw new Error(`URL inesperada: ${url}`)
  })
}

/** Mostra a URL atual para o teste conferir o que ficou guardado. */
function Url() {
  const { pathname, search } = useLocation()
  return <output data-testid="url">{pathname + search}</output>
}

function renderSinais(rota = '/sinais') {
  return render(
    <MemoryRouter initialEntries={[rota]}>
      <Routes>
        <Route path="/sinais" element={<><SinaisVitais /><Url /></>} />
        <Route path="/modulos/cuidado" element={<p>hub cuidado</p>} />
        <Route path="/residentes/:id" element={<p>ficha</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

const url = () => screen.getByTestId('url').textContent

beforeEach(() => {
  vi.clearAllMocks()
  respondeCom()
})

describe('UX-NAV-0 — AbasModulo', () => {
  function Abas({ onTrocar = vi.fn(), ativa = 'a' as 'a' | 'b' | 'c' }) {
    return (
      <AbasModulo
        abas={[{ id: 'a', rotulo: 'Alfa' }, { id: 'b', rotulo: 'Beta' }, { id: 'c', rotulo: 'Gama' }]}
        ativa={ativa}
        onTrocar={onTrocar}
        rotulo="Exemplo"
        prefixo="ex"
      />
    )
  }

  it('só a aba ativa entra no Tab e liga com o painel', () => {
    render(<Abas />)
    const abas = screen.getAllByRole('tab')
    expect(abas.map(a => a.getAttribute('tabindex'))).toEqual(['0', '-1', '-1'])
    expect(abas[0].getAttribute('aria-selected')).toBe('true')
    expect(abas[0].getAttribute('aria-controls')).toBe('ex-painel-a')
    expect(abas.every(a => a.className.includes('min-h-[44px]'))).toBe(true)
  })

  it('setas, Home e End trocam a aba e circulam nas pontas', async () => {
    const user = userEvent.setup()
    const onTrocar = vi.fn()
    render(<Abas onTrocar={onTrocar} />)
    screen.getAllByRole('tab')[0].focus()
    await user.keyboard('{ArrowRight}')
    expect(onTrocar).toHaveBeenLastCalledWith('b')
    expect(document.activeElement?.textContent).toBe('Beta')
    await user.keyboard('{End}')
    expect(onTrocar).toHaveBeenLastCalledWith('c')
    await user.keyboard('{ArrowRight}')
    expect(onTrocar).toHaveBeenLastCalledWith('a')
    await user.keyboard('{ArrowLeft}')
    expect(onTrocar).toHaveBeenLastCalledWith('c')
    await user.keyboard('{Home}')
    expect(onTrocar).toHaveBeenLastCalledWith('a')
  })
})

describe('UX-NAV-0 — LinkResidente, BotaoVoltar e PaginaModulo', () => {
  it('LinkResidente leva à ficha; sem nome mostra o identificador', () => {
    render(
      <MemoryRouter>
        <LinkResidente id="r9" nome="Ana Sintética" detalhe="hoje" />
        <LinkResidente id="r8" />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: /Ana Sintética/ }).getAttribute('href')).toBe('/residentes/r9')
    expect(screen.getByRole('link', { name: /r8/ }).getAttribute('href')).toBe('/residentes/r8')
  })

  it('Voltar sem histórico vai para o destino padrão', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/sinais']}>
        <Routes>
          <Route path="/sinais" element={<BotaoVoltar fallback="/modulos/cuidado" />} />
          <Route path="/modulos/cuidado" element={<p>hub cuidado</p>} />
        </Routes>
      </MemoryRouter>,
    )
    await user.click(screen.getByRole('button', { name: 'Voltar' }))
    expect(screen.getByText('hub cuidado')).toBeTruthy()
  })

  it('PaginaModulo: um título, ação opcional e "Ver também" como navegação', () => {
    render(
      <MemoryRouter>
        <PaginaModulo titulo="Tela" subtitulo="Apoio" verTambem={[{ to: '/x', rotulo: 'Outra tela' }]}>
          <p>conteúdo</p>
        </PaginaModulo>
      </MemoryRouter>,
    )
    expect(screen.getAllByRole('heading', { level: 1 }).map(h => h.textContent)).toEqual(['Tela'])
    const ver = within(screen.getByRole('navigation', { name: 'Ver também' }))
    expect(ver.getByRole('link', { name: 'Outra tela' }).getAttribute('href')).toBe('/x')
    expect(screen.queryByRole('button', { name: 'Voltar' })).toBeNull()
  })
})

describe('UX-NAV-0 — piloto Sinais vitais', () => {
  it('filtro de residente vem da URL e vira chip removível', async () => {
    const user = userEvent.setup()
    renderSinais('/sinais?residente=res-2')
    await waitFor(() =>
      expect(mockGet.mock.calls.some(c => c[0] === '/sinais-vitais/' && (c[1] as any)?.params?.residente_id === 'res-2')).toBe(true),
    )
    expect((screen.getByLabelText('Residente') as HTMLSelectElement).value).toBe('res-2')
    const chip = await screen.findByRole('button', { name: 'Remover filtro Residente: Beto Exemplo' })
    await user.click(chip)
    expect(url()).toBe('/sinais')
    expect(screen.queryByRole('button', { name: /Remover filtro/ })).toBeNull()
  })

  it('escolher residente grava na URL e "Limpar filtros" tira tudo, preservando a aba', async () => {
    const user = userEvent.setup()
    renderSinais('/sinais?aba=hoje')
    await screen.findAllByRole('article')
    await user.selectOptions(screen.getByLabelText('Residente'), 'res-1')
    expect(url()).toBe('/sinais?aba=hoje&residente=res-1')
    await user.click(screen.getByRole('button', { name: 'Limpar filtros' }))
    expect(url()).toBe('/sinais?aba=hoje')
  })

  it('aba Hoje mostra só as aferições do dia; Todos mostra tudo', async () => {
    const user = userEvent.setup()
    renderSinais()
    expect(await screen.findAllByRole('article')).toHaveLength(2)
    await user.click(screen.getByRole('tab', { name: 'Hoje' }))
    expect(url()).toBe('/sinais?aba=hoje')
    const artigos = screen.getAllByRole('article')
    expect(artigos).toHaveLength(1)
    expect(within(artigos[0]).getByRole('link', { name: /Ana Sintética/ }).getAttribute('href')).toBe('/residentes/res-1')
    await user.click(screen.getByRole('tab', { name: 'Todos' }))
    expect(url()).toBe('/sinais')
  })

  it('aba inválida na URL cai em Todos', async () => {
    renderSinais('/sinais?aba=nao-existe')
    expect(await screen.findAllByRole('article')).toHaveLength(2)
    expect(screen.getByRole('tab', { name: 'Todos' }).getAttribute('aria-selected')).toBe('true')
    await waitFor(() => expect(url()).toBe('/sinais'))
  })

  it('"Ver também" oferece a ficha do residente filtrado', async () => {
    renderSinais('/sinais?residente=res-1')
    const ver = within(await screen.findByRole('navigation', { name: 'Ver também' }))
    expect(ver.getByRole('link', { name: 'Abrir prontuário' }).getAttribute('href')).toBe('/residentes/res-1')
  })
})

describe('UX-NAV-0 — chip do residente sem a lista', () => {
  it('enquanto a lista carrega, o chip não mostra o identificador', async () => {
    mockGet.mockImplementation((u: string) => {
      if (u === '/sinais-vitais/') return Promise.resolve({ data: [] } as any)
      return new Promise(() => {}) as any
    })
    renderSinais('/sinais?residente=res-2')
    expect(await screen.findByRole('button', { name: 'Remover filtro Residente: carregando…' })).toBeTruthy()
  })

  it('residente fora da lista vira "não encontrado"', async () => {
    renderSinais('/sinais?residente=outro')
    expect(await screen.findByRole('button', { name: 'Remover filtro Residente: não encontrado' })).toBeTruthy()
  })
})

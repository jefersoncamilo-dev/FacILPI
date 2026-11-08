import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router'
import { PermissoesProvider } from '../context/PermissoesContext'
import { ResidenteProntuario, abasPermitidas } from '../pages/ResidenteProntuario'
import { hora as horaDoItem, situacaoDoItem } from '../components/prontuario/PainelHoje'
import { ResidenteCabecalho } from '../components/prontuario/ResidenteCabecalho'
import { api } from '../services/api'
import { contextApi } from '../services/context'
import { limparCentralAlertas } from '../hooks/useCentralAlertas'

// Dados sintéticos: nomes fictícios, nenhum dado real.
vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() } }
})
vi.mock('../services/context', () => ({ contextApi: { permissoesDaSessao: vi.fn() } }))

const mockGet = vi.mocked(api.get)
const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

const AGORA = Date.now()
const hora = (deltaMin: number) => new Date(AGORA + deltaMin * 60_000).toISOString()

const SINAIS = [
  { id: 's2', residente_id: 'r1', pressao_sistolica: 130, pressao_diastolica: 85, temperatura: 36.9, data: '2026-11-02T12:00:00Z', profissional: 'Enf. Teste' },
  { id: 's1', residente_id: 'r1', pressao_sistolica: 120, pressao_diastolica: 80, temperatura: 36.4, data: '2026-11-01T12:00:00Z', profissional: 'Enf. Teste' },
]
const PLANTAO = [
  { origem: 'cuidado', registro_id: 'c1', residente_id: 'r1', descricao: 'Higiene sintética', previsto_em: hora(-60) },
  { origem: 'medicacao', registro_id: 'm1', residente_id: 'r1', descricao: 'Dose sintética 10 mg', previsto_em: hora(30) },
  { origem: 'intercorrencia', registro_id: 'i1', residente_id: 'r1', descricao: 'Queda sintética', previsto_em: null },
]

function fontes(url: string) {
  if (url === '/residentes/r1') return { id: 'r1', nome: 'Ana Sintética', situacao: 'Ativo' }
  if (url === '/residentes/r1/prontuario') return { items: [], next_cursor: null, has_more: false }
  if (url === '/plantao/') return PLANTAO
  if (url === '/sinais-vitais/') return SINAIS
  return []
}

function Url() {
  const { pathname, search } = useLocation()
  return <output data-testid="url">{pathname + search}</output>
}

function renderFicha(permissoes: string[], rota = '/residentes/r1') {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', ilpi_id: 'ilpi1', permissoes } } as any)
  mockGet.mockImplementation(((url: string) => Promise.resolve({ data: fontes(url) })) as any)
  return render(
    <PermissoesProvider>
      <MemoryRouter initialEntries={[rota]}>
        <Routes>
          <Route path="/residentes/:id" element={<><ResidenteProntuario /><Url /></>} />
        </Routes>
      </MemoryRouter>
    </PermissoesProvider>,
  )
}

const url = () => screen.getByTestId('url').textContent
const nomesDasAbas = () => screen.getAllByRole('tab').map(t => t.textContent)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  limparCentralAlertas()
})

describe('UX-NAV-3 — abas da ficha', () => {
  it('7 abas na ordem da rotina quando tudo é permitido', () => {
    expect(abasPermitidas(() => true).map(a => a.rotulo)).toEqual([
      'Hoje', 'Resumo', 'Medicação', 'Saúde', 'Cuidados e PAIS', 'Linha do tempo', 'Documentos',
    ])
  })

  it('cada aba só aparece com uma das chaves que a alimentam', () => {
    const so = (...c: string[]) => (k?: string) => !k || c.includes(k)
    expect(abasPermitidas(so('residentes:ler')).map(a => a.id)).toEqual(['resumo', 'linha-do-tempo'])
    expect(abasPermitidas(so('prescricoes:ler')).map(a => a.id)).toContain('medicacao')
    expect(abasPermitidas(so('documentos:ler')).map(a => a.id)).toContain('documentos')
    expect(abasPermitidas(so('sinais_vitais:ler')).map(a => a.id)).toEqual(['hoje', 'resumo', 'saude', 'linha-do-tempo'])
  })

  it('abre na primeira aba permitida (Hoje)', async () => {
    renderFicha(['residentes:ler', 'plantao:ler'])
    await waitFor(() => expect(nomesDasAbas()).toEqual(['Hoje', 'Resumo', 'Linha do tempo']))
    expect(screen.getByRole('tab', { name: 'Hoje' }).getAttribute('aria-selected')).toBe('true')
  })

  it('aba sem permissão cai na primeira permitida, com aviso dispensável e URL corrigida', async () => {
    const user = userEvent.setup()
    renderFicha(['residentes:ler', 'plantao:ler'], '/residentes/r1?aba=medicacao')
    const aviso = await screen.findByText('Medicação não está liberada para você. Mostrando a aba Hoje.')
    expect(screen.getByRole('tab', { name: 'Hoje' }).getAttribute('aria-selected')).toBe('true')
    await waitFor(() => expect(url()).toBe('/residentes/r1'))
    expect(aviso.closest('[role="status"]')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Fechar aviso' }))
    expect(screen.queryByText(/não está liberada/)).toBeNull()
  })

  it('aba que não existe tem aviso próprio, sem citar permissão', async () => {
    renderFicha(['residentes:ler'], '/residentes/r1?aba=medicaco')
    expect(await screen.findByText('Não encontramos essa parte da ficha. Mostrando a aba Resumo.')).toBeTruthy()
  })

  it('aba permitida pela URL abre direto, sem aviso', async () => {
    renderFicha(['residentes:ler', 'documentos:ler'], '/residentes/r1?aba=documentos')
    const link = await screen.findByRole('link', { name: /Documentos do residente/ })
    expect(link.getAttribute('href')).toBe('/documentos?residente=r1')
    expect(screen.queryByRole('status', { name: /liberada/ })).toBeNull()
    expect(url()).toBe('/residentes/r1?aba=documentos')
  })
})

describe('UX-NAV-3 — painel do dia (aba Hoje)', () => {
  it('sem administracoes:ler, dose não aparece; estado sempre com texto', async () => {
    renderFicha(['residentes:ler', 'plantao:ler'])
    const lista = within(await screen.findByRole('region', { name: 'O que está previsto' }))
    expect(await lista.findByText('Higiene sintética')).toBeTruthy()
    expect(lista.queryByText('Dose sintética 10 mg')).toBeNull()
    expect(lista.getByText('Atrasado')).toBeTruthy()
    expect(lista.getByText('Em aberto')).toBeTruthy()
    expect(mockGet).toHaveBeenCalledWith('/plantao/', { params: { residente_id: 'r1' } })
  })

  it('com administracoes:ler, a dose entra na lista', async () => {
    renderFicha(['residentes:ler', 'plantao:ler', 'administracoes:ler'])
    expect(await screen.findByText('Dose sintética 10 mg')).toBeTruthy()
    expect(screen.getByText('Cuidados e doses pendentes')).toBeTruthy()
  })

  it('situação do item: atrasado, previsto, sem horário e intercorrência em aberto', () => {
    const base = { registro_id: 'x', residente_id: 'r1', descricao: 'x' }
    expect(situacaoDoItem({ ...base, origem: 'cuidado', previsto_em: hora(-1) }, AGORA).texto).toBe('Atrasado')
    expect(situacaoDoItem({ ...base, origem: 'cuidado', previsto_em: hora(10) }, AGORA).texto).toBe('Previsto')
    expect(situacaoDoItem({ ...base, origem: 'cuidado', previsto_em: null }, AGORA).texto).toBe('Sem horário')
    expect(situacaoDoItem({ ...base, origem: 'intercorrencia', previsto_em: null }, AGORA).texto).toBe('Em aberto')
  })
})

describe('UX-NAV-3 — aba Saúde', () => {
  it('mostra o histórico de saúde e nenhum gráfico (a evolução fica para a aba Monitoramento)', async () => {
    renderFicha(['residentes:ler', 'sinais_vitais:ler'], '/residentes/r1?aba=saude')
    expect(await screen.findByRole('region', { name: 'Avaliações, sinais e intercorrências' })).toBeTruthy()
    expect(screen.queryByRole('img')).toBeNull()
  })
})

describe('UX-NAV-3 — achados da validação', () => {
  it('escolher aba enquanto as permissões carregam não se perde', async () => {
    let liberar: (v: unknown) => void = () => {}
    mockPermissoes.mockReturnValue(new Promise(r => { liberar = r }) as any)
    mockGet.mockImplementation(((u: string) => Promise.resolve({ data: fontes(u) })) as any)
    render(
      <PermissoesProvider>
        <MemoryRouter initialEntries={['/residentes/r1']}>
          <Routes><Route path="/residentes/:id" element={<><ResidenteProntuario /><Url /></>} /></Routes>
        </MemoryRouter>
      </PermissoesProvider>,
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('tab', { name: 'Resumo' }))
    expect(url()).toBe('/residentes/r1?aba=resumo')
    liberar({ data: { scope: 'ilpi', ilpi_id: 'ilpi1', permissoes: ['residentes:ler', 'plantao:ler'] } })
    await waitFor(() => expect(nomesDasAbas()).toContain('Hoje'))
    expect(screen.getByRole('tab', { name: 'Resumo' }).getAttribute('aria-selected')).toBe('true')
  })

  it('item de outro dia mostra a data junto da hora', () => {
    const agora = new Date('2026-11-07T15:00:00')
    expect(horaDoItem('2026-11-07T08:00:00', agora)).toBe('08:00')
    expect(horaDoItem('2026-11-06T23:30:00', agora)).toBe('06/11 23:30')
  })
})

describe('UX-NAV-3 — cabeçalho do residente', () => {
  const RES = { id: 'r1', nome: 'Ana Sintética', situacao: 'Ativo', data_nascimento: '1940-05-10', alergias: 'Dipirona' }

  it('grau de dependência em destaque, com texto e validade', () => {
    render(<ResidenteCabecalho residente={RES} contexto={{ leito: 'Quarto 1 · Leito A', ausencia: null, grau: { classificacao: 'Grau II', validade: '2026-12-31' } }} />)
    const grau = screen.getByText('Grau de dependência: Grau II').parentElement!
    expect(grau.textContent).toContain('válido até 31/12/2026')
    expect(grau.className).toContain('bg-alerta-soft')
    expect(screen.getByText('Quarto 1 · Leito A')).toBeTruthy()
    expect(screen.getByText(/Dipirona/)).toBeTruthy()
  })

  it('sem grau confirmado diz "Não definido"; sem permissão, o bloco nem aparece', () => {
    const { rerender } = render(<ResidenteCabecalho residente={RES} contexto={{ leito: undefined, ausencia: undefined, grau: null }} />)
    expect(screen.getByText('Grau de dependência: Não definido')).toBeTruthy()
    rerender(<ResidenteCabecalho residente={RES} contexto={{ leito: undefined, ausencia: undefined, grau: undefined }} />)
    expect(screen.queryByText(/Grau de dependência/)).toBeNull()
  })

  it('foto grande e ações dentro do cabeçalho', () => {
    render(<ResidenteCabecalho residente={RES} acoes={<button type="button">+ Registrar</button>} />)
    const regiao = screen.getByRole('region', { name: 'Identificação do residente' })
    expect(regiao.querySelector('[aria-hidden="true"]')!.className).toMatch(/size-24.*sm:size-28/)
    expect(within(regiao).getByRole('button', { name: '+ Registrar' })).toBeTruthy()
  })
})


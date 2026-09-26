import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { Avaliacoes } from '../pages/Avaliacoes'
import { api } from '../services/api'
import { contextApi } from '../services/context'
import { hojeLocal, situacaoValidade } from '../services/avaliacoes'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn() } }
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
const mockPost = vi.mocked(api.post)
const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

const avaliacao = (p: Record<string, unknown>) => ({
  residente_id: 'r1', tipo: 'Funcional', instrumento: null, respostas: null, pontuacao: null, classificacao: null,
  data: '2026-09-20T13:00:00Z', validade: null, observacoes: null, profissional: 'Enf. Carla Souza', created_at: null, ...p,
})
const AVALIACOES = [
  avaliacao({ id: 'a1', tipo: 'Funcional', instrumento: 'Katz', pontuacao: 4, classificacao: 'Grau II', validade: '2999-12-31',
    respostas: JSON.stringify({ banho: 'dependente', alimentacao: 'independente' }) }),
  avaliacao({ id: 'a2', residente_id: 'r2', tipo: 'Risco de queda', validade: '2000-01-01', observacoes: 'Usa andador' }),
]
const RESIDENTES = [{ id: 'r1', nome: 'Antônia Ribeiro' }, { id: 'r2', nome: 'Benedito Carvalho' }]
const TUDO = ['avaliacoes:ler', 'avaliacoes:criar', 'grau_dependencia:ler', 'grau_dependencia:criar', 'residentes:ler']

function responde({ avaliacoes = AVALIACOES as unknown, graus = [] as unknown } = {}) {
  mockGet.mockImplementation((url: string) => {
    const de = (x: unknown) => (x instanceof Error || (x as any)?.response ? Promise.reject(x) : Promise.resolve({ data: x } as any))
    if (url === '/avaliacoes/') return de(avaliacoes)
    if (url === '/residentes/') return de(RESIDENTES)
    if (url === '/graus-dependencia/') return de(graus)
    throw new Error(`URL inesperada: ${url}`)
  })
}

function renderEm(rota = '/avaliacoes', permissoes = TUDO) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes } } as any)
  return render(<AuthProvider><MemoryRouter initialEntries={[rota]}><PermissoesProvider><Avaliacoes /></PermissoesProvider></MemoryRouter></AuthProvider>)
}

const cartao = async (texto: string) => (await screen.findByText(texto)).closest('button') as HTMLElement

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  responde()
})

describe('Avaliações — lista', () => {
  it('mostra o que foi registrado, sem calcular, e a validade pela data', async () => {
    renderEm()
    const katz = within(await cartao('Funcional · Katz'))
    expect(await katz.findByText('Antônia Ribeiro')).toBeTruthy()
    expect(katz.getByText(/Enf\. Carla Souza · pontuação 4 · classificação: Grau II/)).toBeTruthy()
    expect(katz.getByText(/Válida até/)).toBeTruthy()
    expect(within(await cartao('Risco de queda')).getByText(/Vencida em/)).toBeTruthy()
  })

  it('validade usa a data local e não afirma nada sem data', () => {
    expect(hojeLocal(new Date(2026, 8, 25, 23, 30))).toBe('2026-09-25')
    expect(situacaoValidade('2026-09-25', '2026-09-25')).toBe('vigente')
    expect(situacaoValidade('2026-09-24', '2026-09-25')).toBe('vencida')
    expect(situacaoValidade(null)).toBeNull()
  })

  it('?residente= e busca restringem a lista', async () => {
    const user = userEvent.setup()
    renderEm('/avaliacoes?residente=r2')
    expect(await screen.findByText('Risco de queda')).toBeTruthy()
    expect(screen.queryByText('Funcional · Katz')).toBeNull()
    await user.selectOptions(screen.getByLabelText('Residente'), '')
    expect(await screen.findByText('Funcional · Katz')).toBeTruthy()
    await user.type(screen.getByLabelText('Buscar'), 'katz')
    expect(screen.queryByText('Risco de queda')).toBeNull()
  })

  it('403 e falha não viram "nenhuma avaliação"', async () => {
    responde({ avaliacoes: { response: { status: 403, data: { detail: 'x' } } } })
    const sem = renderEm()
    expect(await screen.findByText('Sem acesso às avaliações')).toBeTruthy()
    sem.unmount()
    responde({ avaliacoes: new Error('rede') })
    renderEm()
    expect(await screen.findByText('Não foi possível carregar as avaliações')).toBeTruthy()
    expect(screen.queryByText('Nenhuma avaliação registrada')).toBeNull()
  })
})

describe('Avaliações — registro', () => {
  it('registra com texto aparado, pontuação com vírgula e sem data (o backend usa agora)', async () => {
    const user = userEvent.setup()
    mockPost.mockResolvedValueOnce({ data: avaliacao({ id: 'a3', residente_id: 'r2' }) } as any)
    renderEm()
    await user.click(await screen.findByRole('button', { name: /Nova avaliação/ }))
    const dialog = within(await screen.findByRole('dialog'))
    await dialog.findByRole('option', { name: 'Benedito Carvalho' })
    await user.selectOptions(dialog.getByLabelText('Residente'), 'r2')
    await user.type(dialog.getByLabelText('Tipo'), '  Cognitiva ')
    await user.type(dialog.getByLabelText('Pontuação (opcional)'), '18,5')
    await user.type(dialog.getByLabelText('Classificação (opcional)'), 'Leve')
    await user.click(dialog.getByRole('button', { name: 'Registrar avaliação' }))
    expect(mockPost).toHaveBeenCalledWith('/avaliacoes/', { residente_id: 'r2', tipo: 'Cognitiva', pontuacao: 18.5, classificacao: 'Leve' })
    expect(await screen.findByText('Avaliação registrada para Benedito Carvalho.')).toBeTruthy()
  })

  it('pontuação não numérica não é enviada; sem permissão de criar, não há botão', async () => {
    const user = userEvent.setup()
    const tela = renderEm()
    await user.click(await screen.findByRole('button', { name: /Nova avaliação/ }))
    const dialog = within(await screen.findByRole('dialog'))
    await dialog.findByRole('option', { name: 'Antônia Ribeiro' })
    await user.selectOptions(dialog.getByLabelText('Residente'), 'r1')
    await user.type(dialog.getByLabelText('Tipo'), 'Funcional')
    await user.type(dialog.getByLabelText('Pontuação (opcional)'), 'abc')
    await user.click(dialog.getByRole('button', { name: 'Registrar avaliação' }))
    expect(await dialog.findByText('Pontuação deve ser um número.')).toBeTruthy()
    expect(mockPost).not.toHaveBeenCalled()
    tela.unmount()

    renderEm('/avaliacoes', ['avaliacoes:ler', 'residentes:ler'])
    expect(await screen.findByText('Funcional · Katz')).toBeTruthy()
    await waitFor(() => expect(screen.queryByRole('button', { name: /Nova avaliação/ })).toBeNull())
  })

  it('vindo da pendência da admissão, abre com residente, tipo e instrumento exatos', async () => {
    renderEm('/avaliacoes?residente=r1&novo=1&tipo=Nutricional&instrumento=MAN')
    const dialog = within(await screen.findByRole('dialog'))
    expect((dialog.getByLabelText('Tipo') as HTMLInputElement).value).toBe('Nutricional')
    expect((dialog.getByLabelText('Instrumento (opcional)') as HTMLInputElement).value).toBe('MAN')
    await waitFor(() => expect((dialog.getByLabelText('Residente') as HTMLSelectElement).value).toBe('r1'))
  })
})

describe('Avaliações — detalhe e grau de dependência', () => {
  it('mostra respostas e confirma o grau só por decisão explícita, com a sugestão pré-selecionada', async () => {
    const user = userEvent.setup()
    mockPost.mockResolvedValueOnce({ data: { id: 'g1', classificacao: 'Grau II' } } as any)
    renderEm()
    await user.click(await cartao('Funcional · Katz'))
    const dialog = within(await screen.findByRole('dialog'))
    expect(within(dialog.getByRole('region', { name: 'Respostas' })).getByText('dependente')).toBeTruthy()
    const grau = within(dialog.getByRole('region', { name: 'Grau de dependência' }))
    expect(await grau.findByText('Não definido')).toBeTruthy()
    expect(mockPost).not.toHaveBeenCalled()

    await user.click(grau.getByRole('button', { name: 'Confirmar grau a partir desta avaliação' }))
    expect((grau.getByLabelText('Grau confirmado') as HTMLSelectElement).value).toBe('Grau II')
    const confirmar = grau.getByRole('button', { name: 'Confirmar grau' })
    expect(confirmar).toHaveProperty('disabled', true)
    await user.type(grau.getByLabelText('Justificativa'), 'Katz 4, dependente para banho')
    await user.click(confirmar)
    expect(mockPost).toHaveBeenCalledWith('/graus-dependencia/', {
      residente_id: 'r1', avaliacao_id: 'a1', classificacao: 'Grau II', justificativa: 'Katz 4, dependente para banho', origem: 'avaliacao',
    })
    expect(await grau.findByText(/Grau de dependência confirmado: Grau II\./)).toBeTruthy()
  })

  it('com grau ativo, avisa a substituição; classificação fora dos graus oficiais não pré-seleciona', async () => {
    const user = userEvent.setup()
    responde({ graus: [{ id: 'g0', residente_id: 'r2', classificacao: 'Grau I', situacao: 'ativo', avaliacao_id: null, confirmado_em: '2026-08-01T10:00:00Z' }] })
    renderEm()
    await user.click(await cartao('Risco de queda'))
    const grau = within(within(await screen.findByRole('dialog')).getByRole('region', { name: 'Grau de dependência' }))
    expect(await grau.findByText(/Grau I · desde/)).toBeTruthy()
    await user.click(grau.getByRole('button', { name: 'Confirmar grau a partir desta avaliação' }))
    expect(grau.getByText(/o grau atual \(Grau I\) passa a “substituído”/)).toBeTruthy()
    expect((grau.getByLabelText('Grau confirmado') as HTMLSelectElement).value).toBe('')
  })

  it('sem permissão de confirmar, só leitura; sem permissão de ler grau, a seção não aparece', async () => {
    const user = userEvent.setup()
    const leitura = renderEm('/avaliacoes', ['avaliacoes:ler', 'grau_dependencia:ler', 'residentes:ler'])
    await user.click(await cartao('Funcional · Katz'))
    const grau = within(within(await screen.findByRole('dialog')).getByRole('region', { name: 'Grau de dependência' }))
    expect(await grau.findByText('Não definido')).toBeTruthy()
    expect(grau.queryByRole('button', { name: /Confirmar grau/ })).toBeNull()
    leitura.unmount()
    mockGet.mockClear()

    renderEm('/avaliacoes', ['avaliacoes:ler', 'residentes:ler'])
    await user.click(await cartao('Funcional · Katz'))
    const dialog = within(await screen.findByRole('dialog'))
    await waitFor(() => expect(dialog.queryByRole('region', { name: 'Grau de dependência' })).toBeNull())
    expect(mockGet).not.toHaveBeenCalledWith('/graus-dependencia/', expect.anything())
  })
})

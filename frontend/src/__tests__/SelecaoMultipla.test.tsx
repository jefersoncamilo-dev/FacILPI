import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { MeuPlantao } from '../pages/MeuPlantao'
import { api } from '../services/api'
import { contextApi } from '../services/context'

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

const em = (min: number) => new Date(Date.now() + min * 60_000).toISOString()
const cuidado = (id: string, residente: string, descricao: string, min: number) =>
  ({ origem: 'cuidado', registro_id: id, residente_id: residente, descricao, previsto_em: em(min), prioridade: null, local: null })
const BANHO_1 = cuidado('b1', 'r1', 'Banho assistido', 30)
const BANHO_2 = cuidado('b2', 'r2', 'Banho assistido', 40)
const HIDRATACAO = cuidado('h1', 'r1', 'Hidratação', 50)
const DOSE = { origem: 'medicacao', registro_id: 'd1', residente_id: 'r1', descricao: 'Dose prevista de medicacao', previsto_em: em(35), prioridade: null, local: null }

let fila: unknown[] = []
function responde(itens: unknown[]) {
  fila = itens
  mockGet.mockImplementation((url: string) => {
    if (url === '/plantao/') return Promise.resolve({ data: fila } as any)
    if (url === '/residentes/') return Promise.resolve({ data: [{ id: 'r1', nome: 'Maria Souza' }, { id: 'r2', nome: 'João Lima' }] } as any)
    if (url === '/meu-plantao/') return Promise.resolve({ data: { gerado_em: em(0), areas: [] } } as any)
    return Promise.resolve({ data: [] } as any)
  })
}

function renderCom(permissoes: string[]) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes } } as any)
  return render(<AuthProvider><MemoryRouter><PermissoesProvider><MeuPlantao /></PermissoesProvider></MemoryRouter></AuthProvider>)
}

const TUDO = ['plantao:ler', 'execucoes:criar', 'administracoes:criar', 'intercorrencias:atualizar']
const barra = () => within(screen.getByRole('region', { name: 'Seleção' }))

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
})

describe('UX-01B — seleção múltipla', () => {
  it('só cuidados viram marcáveis; medicação não, e Registrar some no modo seleção', async () => {
    const user = userEvent.setup()
    responde([BANHO_1, DOSE, BANHO_2])
    renderCom(TUDO)

    await user.click(await screen.findByRole('button', { name: 'Selecionar' }))
    expect(screen.getAllByRole('checkbox')).toHaveLength(2)
    expect(screen.queryByRole('button', { name: 'Registrar' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Registrar administração' })).toBeNull()
    expect(barra().getByText('Nenhum cuidado marcado')).toBeTruthy()
  })

  it('sem execucoes:criar não há seleção', async () => {
    responde([BANHO_1, BANHO_2])
    renderCom(['plantao:ler'])
    await screen.findAllByText('Banho assistido')
    await waitFor(() => expect(mockPermissoes).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: 'Selecionar' })).toBeNull()
  })

  it('marca um a um e conta; Limpar e Cancelar zeram', async () => {
    const user = userEvent.setup()
    responde([BANHO_1, BANHO_2, HIDRATACAO])
    renderCom(TUDO)

    await user.click(await screen.findByRole('button', { name: 'Selecionar' }))
    const [primeiro, segundo] = screen.getAllByRole('checkbox')
    await user.click(primeiro)
    await user.click(segundo)
    expect(primeiro.getAttribute('aria-checked')).toBe('true')
    expect(barra().getByText('2 marcados')).toBeTruthy()

    await user.click(barra().getByRole('button', { name: 'Limpar' }))
    expect(barra().getByText('Nenhum cuidado marcado')).toBeTruthy()

    await user.click(screen.getAllByRole('checkbox')[0])
    await user.click(screen.getByRole('button', { name: 'Cancelar seleção' }))
    expect(screen.queryByRole('region', { name: 'Seleção' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Selecionar' }))
    expect(screen.getAllByRole('checkbox').every(c => c.getAttribute('aria-checked') === 'false')).toBe(true)
  })

  it('Por cuidado: "Marcar até 1 h" marca só o grupo e alterna para "Desmarcar todos"', async () => {
    const user = userEvent.setup()
    responde([BANHO_1, BANHO_2, HIDRATACAO])
    renderCom(TUDO)

    await user.click(await screen.findByRole('button', { name: /^Organizar/ }))
    await user.click(await screen.findByRole('menuitemradio', { name: 'Por cuidado' }))
    await user.click(screen.getByRole('button', { name: 'Selecionar' }))
    const banho = within(screen.getByRole('region', { name: 'Banho assistido' }))
    await user.click(banho.getByRole('button', { name: 'Marcar até 1 h (2)' }))

    expect(barra().getByText('2 marcados')).toBeTruthy()
    expect(within(screen.getByRole('region', { name: 'Hidratação' })).getByRole('checkbox').getAttribute('aria-checked')).toBe('false')
    expect(banho.getByRole('button', { name: 'Desmarcar todos' })).toBeTruthy()
  })

  it('o nome acessível da caixa diz cuidado, residente e horário', async () => {
    const user = userEvent.setup()
    responde([BANHO_1])
    renderCom(TUDO)
    await user.click(await screen.findByRole('button', { name: 'Selecionar' }))
    expect(screen.getByRole('checkbox', { name: /^Banho assistido — Maria Souza, \d{2}\/\d{2} \d{2}:\d{2}$/ })).toBeTruthy()
  })
})

describe('Grau de dependência no card (UX-01E, decisão C)', () => {
  it('o grau ativo vem da fila: aparece para quem lê o plantão, sem consultar o histórico', async () => {
    responde([{ ...BANHO_1, grau: 'Grau III' }, { ...BANHO_2, grau: null }])
    renderCom(['plantao:ler'])  // sem grau_dependencia:ler
    const selo = await screen.findByLabelText('Grau de dependência III')
    expect(selo.textContent).toBe('Grau III')
    expect(screen.getAllByLabelText(/Grau de dependência/)).toHaveLength(1)
    expect(mockGet.mock.calls.some(c => c[0] === '/graus-dependencia/')).toBe(false)
  })

  // UX-GRAU: I verde, II amarelo, III vermelho (tokens --grau-*), sempre com o texto.
  it('cores por grau: I verde, II amarelo, III vermelho — sempre com o texto', async () => {
    responde([{ ...BANHO_1, grau: 'Grau I' }, { ...BANHO_2, grau: 'Grau II' }, { ...HIDRATACAO, residente_id: 'r2', grau: 'Grau III' }])
    renderCom(['plantao:ler'])
    const selo = async (g: string) => (await screen.findAllByLabelText(`Grau de dependência ${g}`))[0]
    expect((await selo('I')).className).toMatch(/(^|\s)bg-grau-1-fundo\s.*\btext-grau-1-texto(\s|$)/)
    expect((await selo('II')).className).toMatch(/(^|\s)bg-grau-2-fundo\s.*\btext-grau-2-texto(\s|$)/)
    expect((await selo('III')).className).toMatch(/(^|\s)bg-grau-3-fundo\s.*\btext-grau-3-texto(\s|$)/)
    expect((await selo('II')).textContent).toBe('Grau II')
  })

  // UX-GRAU G3a: círculo do grau na foto, "Sem grau" visível e quem não tem grau sobe na faixa.
  it('círculo na foto, "Sem grau" no card e ordem sem grau → III → II → I na faixa', async () => {
    responde([
      { ...BANHO_1, grau: 'Grau I' },
      { ...HIDRATACAO, residente_id: 'r3', grau: 'Grau III' },
      { ...BANHO_2, grau: null },
    ])
    renderCom(['plantao:ler', 'execucoes:criar'])
    const regiao = await screen.findByRole('region', { name: 'Agora (próxima 1 h)' })
    await within(regiao).findByText('Sem grau')
    const ordem = [...regiao.querySelectorAll('[data-acao-plantao]')].map(b => b.getAttribute('data-acao-plantao'))
    expect(ordem).toEqual(['cuidado:b2', 'cuidado:h1', 'cuidado:b1'])
    expect(document.querySelector('[data-grau="Grau III"]')?.className).toMatch(/(^|\s)ring-grau-3(\s|$)/)
  })
})

describe('UX-GRAU G3b — barra única e cartão novo', () => {
  it('botão curto "Registrar" com o nome acessível completo; atraso em texto no cartão', async () => {
    const atrasada = { ...DOSE, registro_id: 'd0', previsto_em: em(-35) }
    responde([atrasada, BANHO_1])
    renderCom(TUDO)
    const dose = await screen.findByRole('button', { name: 'Registrar administração' })
    expect(dose.textContent).toBe('Registrar')
    expect(screen.getByRole('button', { name: 'Registrar' }).textContent).toBe('Registrar')
    expect(within(screen.getByRole('region', { name: 'Atrasadas' })).getByText(/atrasado 3\d min/)).toBeTruthy()
  })

  it('"Mais ações" abre Feitos/Expirados do turno; sem a permissão, o item não aparece', async () => {
    const user = userEvent.setup()
    responde([BANHO_1])
    const { unmount } = renderCom([...TUDO, 'execucoes:ler'])
    await screen.findByRole('button', { name: 'Registrar' })
    expect(screen.queryByRole('region', { name: 'Feitos e expirados do turno' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Mais ações' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Feitos e expirados do turno' }))
    expect(await screen.findByRole('region', { name: 'Feitos e expirados do turno' })).toBeTruthy()
    unmount()

    renderCom(TUDO)  // sem execucoes:ler, correção ou passagem: nada a oferecer
    await screen.findByRole('button', { name: 'Registrar' })
    expect(screen.queryByRole('button', { name: 'Mais ações' })).toBeNull()
  })

  it('Organizar: o menu mostra a visão escolhida marcada', async () => {
    const user = userEvent.setup()
    responde([BANHO_1, HIDRATACAO])
    renderCom(TUDO)
    await user.click(await screen.findByRole('button', { name: 'Organizar por horário' }))
    expect((await screen.findByRole('menuitemradio', { name: 'Por horário' })).getAttribute('aria-checked')).toBe('true')
    await user.click(screen.getByRole('menuitemradio', { name: 'Por residente' }))
    expect(await screen.findByRole('region', { name: 'Maria Souza' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Organizar por residente' })).toBeTruthy()
  })
})

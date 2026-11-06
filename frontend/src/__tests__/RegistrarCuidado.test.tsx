import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { MeuPlantao } from '../pages/MeuPlantao'
import { validarOutroHorario } from '../components/plantao/RegistrarCuidado'
import { api } from '../services/api'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
})

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)

const cuidado = (id: string, descricao: string, hora: string) => ({
  origem: 'cuidado', registro_id: id, residente_id: 'res-1', descricao, previsto_em: `2099-01-01T${hora}:00Z`, prioridade: 'media',
})
const BANHO = cuidado('oc-1', 'Banho assistido', '10:00')
const HIDRATACAO = cuidado('oc-2', 'Hidratação', '11:00')

function responde(itens: unknown[]) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/plantao/') return Promise.resolve({ data: itens } as any)
    if (url === '/residentes/') return Promise.resolve({ data: [{ id: 'res-1', nome: 'Maria Silva' }] } as any)
    throw new Error(`URL inesperada: ${url}`)
  })
}

async function abrirRegistro(user: ReturnType<typeof userEvent.setup>, indice = 0) {
  await user.click((await screen.findAllByRole('button', { name: 'Registrar' }))[indice])
  return within(await screen.findByRole('dialog', { name: 'Registrar cuidado' }))
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('UX-01A.1 — Registrar rápido', () => {
  it('abre sem foco em campo de texto e com observação recolhida', async () => {
    const user = userEvent.setup()
    responde([BANHO])
    render(<MemoryRouter><MeuPlantao /></MemoryRouter>)
    const dialogo = await abrirRegistro(user)

    expect(dialogo.getByText('Banho assistido')).toBeTruthy()
    expect(dialogo.getByText(/Maria Silva/)).toBeTruthy()
    expect(['INPUT', 'TEXTAREA']).not.toContain(document.activeElement?.tagName)
    expect(dialogo.queryByLabelText(/Observação/)).toBeNull()
    expect(dialogo.queryByLabelText(/Motivo/)).toBeNull()
  })

  it('Não realizado: sugestão preenche o motivo e vai como justificativa', async () => {
    const user = userEvent.setup()
    responde([BANHO])
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    render(<MemoryRouter><MeuPlantao /></MemoryRouter>)
    const dialogo = await abrirRegistro(user)

    await user.click(dialogo.getByRole('button', { name: 'Não realizado' }))
    await user.click(dialogo.getByRole('button', { name: 'Residente dormindo' }))
    await user.click(dialogo.getByRole('button', { name: 'Adicionar observação' }))
    await user.type(dialogo.getByLabelText(/Observação/), 'Tentar às 14h')
    await user.click(dialogo.getByRole('button', { name: 'Salvar como não realizado' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect(mockPost.mock.calls[0][1]).toMatchObject({
      ocorrencia_id: 'oc-1', resultado: 'omitida', justificativa: 'Residente dormindo', observacao: 'Tentar às 14h',
    })
  })

  it('falha mantém o diálogo aberto com o que foi informado', async () => {
    const user = userEvent.setup()
    responde([BANHO])
    mockPost.mockRejectedValueOnce(new Error('rede'))
    render(<MemoryRouter><MeuPlantao /></MemoryRouter>)
    const dialogo = await abrirRegistro(user)

    await user.click(dialogo.getByRole('button', { name: 'Recusado' }))
    await user.type(dialogo.getByLabelText(/Motivo/), 'Preferiu à tarde')
    await user.click(dialogo.getByRole('button', { name: 'Salvar como recusado' }))

    expect(await dialogo.findByText('Não foi possível salvar. Tentar novamente.')).toBeTruthy()
    expect((dialogo.getByLabelText(/Motivo/) as HTMLInputElement).value).toBe('Preferiu à tarde')
  })

  it('depois de salvar: item sai da fila sem "Carregando", sucesso visível e foco no próximo', async () => {
    const user = userEvent.setup()
    responde([BANHO, HIDRATACAO])
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    render(<MemoryRouter><MeuPlantao /></MemoryRouter>)
    const dialogo = await abrirRegistro(user)
    responde([HIDRATACAO])

    await user.click(dialogo.getByRole('button', { name: 'Realizado' }))

    expect(await screen.findByText('Registro salvo.')).toBeTruthy()
    expect(screen.queryByText('Carregando plantão…')).toBeNull()
    await waitFor(() => expect(screen.queryByText('Banho assistido')).toBeNull())
    expect(screen.queryByRole('dialog')).toBeNull()
    await waitFor(() => expect(document.activeElement?.getAttribute('data-acao-plantao')).toBe('cuidado:oc-2'))
  })
})

describe('G7 — registrar em outro horário', () => {
  const AGORA = Date.parse('2026-10-29T12:00:00Z')

  it('aceita até 24 h para trás; recusa futuro, mais de 24 h e vazio', () => {
    expect(validarOutroHorario('2026-10-29T08:30:00Z', AGORA)).toEqual({ iso: '2026-10-29T08:30:00.000Z' })
    expect(validarOutroHorario('2026-10-28T12:00:00Z', AGORA)).toEqual({ iso: '2026-10-28T12:00:00.000Z' })
    expect(validarOutroHorario('2026-10-29T12:01:00Z', AGORA)).toEqual({ erro: 'O horário não pode ser no futuro.' })
    expect(validarOutroHorario('2026-10-28T11:59:00Z', AGORA)).toEqual({ erro: 'Só é possível registrar até 24 horas para trás.' })
    expect(validarOutroHorario('', AGORA)).toEqual({ erro: 'Informe o horário do cuidado.' })
  })

  it('sem escolher horário, o registro vai no instante atual', async () => {
    const user = userEvent.setup()
    responde([BANHO])
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    render(<MemoryRouter><MeuPlantao /></MemoryRouter>)
    const dialogo = await abrirRegistro(user)
    expect(dialogo.queryByLabelText(/Horário do cuidado/)).toBeNull()
    const antes = Date.now()
    await user.click(dialogo.getByRole('button', { name: 'Realizado' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect(Date.parse((mockPost.mock.calls[0][1] as any).ocorrido_em)).toBeGreaterThanOrEqual(antes - 1000)
  })

  it('horário escolhido vai como ocorrido_em; fora da janela não envia', async () => {
    const user = userEvent.setup()
    responde([BANHO])
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    render(<MemoryRouter><MeuPlantao /></MemoryRouter>)
    const dialogo = await abrirRegistro(user)
    await user.click(dialogo.getByRole('button', { name: 'Registrar em outro horário' }))
    const campo = dialogo.getByLabelText(/Horário do cuidado/) as HTMLInputElement
    const local = (ms: number) => {
      const d = new Date(ms); const p = (n: number) => String(n).padStart(2, '0')
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
    }

    fireEvent.change(campo, { target: { value: local(Date.now() + 2 * 60 * 60 * 1000) } })
    await user.click(dialogo.getByRole('button', { name: 'Realizado' }))
    expect(await dialogo.findByText('O horário não pode ser no futuro.')).toBeTruthy()
    expect(mockPost).not.toHaveBeenCalled()

    const duasHorasAtras = local(Date.now() - 2 * 60 * 60 * 1000)
    fireEvent.change(campo, { target: { value: duasHorasAtras } })
    await user.click(dialogo.getByRole('button', { name: 'Realizado' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect((mockPost.mock.calls[0][1] as any).ocorrido_em).toBe(new Date(duasHorasAtras).toISOString())
  })
})

describe('G4 — percentual de refeição (D6)', () => {
  const ALMOCO = cuidado('oc-3', 'Almoço assistido', '12:00')

  it('em refeição, cinco botões opcionais; o escolhido vai junto com "Realizado"', async () => {
    const user = userEvent.setup()
    responde([ALMOCO])
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    render(<MemoryRouter><MeuPlantao /></MemoryRouter>)
    const dialogo = await abrirRegistro(user)
    const grupo = within(dialogo.getByRole('group', { name: /Quanto comeu/ }))
    expect(grupo.getAllByRole('button').map(b => b.textContent)).toEqual(['0%', '25%', '50%', '75%', '100%'])
    await user.click(grupo.getByRole('button', { name: '75%' }))
    expect(grupo.getByRole('button', { name: '75%' }).getAttribute('aria-pressed')).toBe('true')
    await user.click(dialogo.getByRole('button', { name: 'Realizado' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect((mockPost.mock.calls[0][1] as any).percentual_consumido).toBe(75)
  })

  it('não é obrigatório: sem escolha, nada de percentual no envio', async () => {
    const user = userEvent.setup()
    responde([ALMOCO])
    mockPost.mockResolvedValueOnce({ data: {} } as any)
    render(<MemoryRouter><MeuPlantao /></MemoryRouter>)
    const dialogo = await abrirRegistro(user)
    await user.click(dialogo.getByRole('button', { name: 'Realizado' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect('percentual_consumido' in (mockPost.mock.calls[0][1] as any)).toBe(false)
  })

  it('fora de refeição, fica recolhido atrás de "Informar quanto comeu"', async () => {
    const user = userEvent.setup()
    responde([BANHO])
    render(<MemoryRouter><MeuPlantao /></MemoryRouter>)
    const dialogo = await abrirRegistro(user)
    expect(dialogo.queryByRole('group', { name: /Quanto comeu/ })).toBeNull()
    await user.click(dialogo.getByRole('button', { name: /Informar quanto comeu/ }))
    expect(dialogo.getByRole('group', { name: /Quanto comeu/ })).toBeTruthy()
  })
})

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, within, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { MeuPlantao } from '../pages/MeuPlantao'
import { api } from '../services/api'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
})

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)
const BANHO = { origem: 'cuidado', registro_id: 'oc-1', residente_id: 'r1', descricao: 'Banho assistido', previsto_em: '2099-01-01T10:00:00Z', prioridade: null, local: null }

// Motor de fala falso: guarda a última instância para o teste "falar".
let instancia: any = null
function instalarMotor({ local, disponibilidade = 'available' }: { local: boolean; disponibilidade?: string }) {
  class Motor {
    lang = ''
    continuous = false
    interimResults = true
    onresult: any = null
    onend: any = null
    onerror: any = null
    start = vi.fn()
    stop = vi.fn(() => this.onend?.())
    constructor() {
      if (local) (this as any).processLocally = false
      instancia = this
    }
    static available = local ? vi.fn(async () => disponibilidade) : undefined
    static install = vi.fn(async () => true)
  }
  ;(window as any).SpeechRecognition = Motor
  return Motor
}

function falar(texto: string) {
  act(() => {
    instancia.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: texto }], { isFinal: true })] })
    instancia.onend()
  })
}

async function abrirObservacao(user: ReturnType<typeof userEvent.setup>) {
  mockGet.mockImplementation((url: string) =>
    Promise.resolve({ data: url === '/plantao/' ? [BANHO] : [{ id: 'r1', nome: 'Maria Souza' }] } as any))
  render(<MemoryRouter><MeuPlantao /></MemoryRouter>)
  await user.click(await screen.findByRole('button', { name: 'Registrar' }))
  const dialogo = within(await screen.findByRole('dialog', { name: 'Registrar cuidado' }))
  await user.click(dialogo.getByRole('button', { name: 'Adicionar observação' }))
  return dialogo
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
  instancia = null
})

afterEach(() => {
  delete (window as any).SpeechRecognition
})

describe('UX-01D — ditado só no aparelho', () => {
  it('sem reconhecimento local (só nuvem) o botão Ditar não aparece', async () => {
    const user = userEvent.setup()
    instalarMotor({ local: false })
    const dialogo = await abrirObservacao(user)
    await waitFor(() => expect(dialogo.getByLabelText(/Observação/)).toBeTruthy())
    expect(dialogo.queryByRole('button', { name: /Ditar/ })).toBeNull()
  })

  it('local indisponível para pt-BR: sem botão', async () => {
    const user = userEvent.setup()
    instalarMotor({ local: true, disponibilidade: 'unavailable' })
    const dialogo = await abrirObservacao(user)
    await waitFor(() => expect(dialogo.getByLabelText(/Observação/)).toBeTruthy())
    expect(dialogo.queryByRole('button', { name: /Ditar/ })).toBeNull()
  })

  it('dita localmente, põe o texto para revisão e só salva texto ao confirmar', async () => {
    const user = userEvent.setup()
    const Motor = instalarMotor({ local: true })
    mockPost.mockResolvedValue({ data: {} } as any)
    const dialogo = await abrirObservacao(user)

    await user.click(await dialogo.findByRole('button', { name: 'Ditar — observação' }))
    expect(Motor.available).toHaveBeenCalledWith({ langs: ['pt-BR'], processLocally: true })
    expect(instancia.processLocally).toBe(true)
    expect(instancia.lang).toBe('pt-BR')
    expect(dialogo.getByRole('button', { name: 'Parar ditado — observação' })).toBeTruthy()

    falar('aceitou bem o banho')
    const campo = dialogo.getByLabelText(/Observação/) as HTMLTextAreaElement
    expect(campo.value).toBe('aceitou bem o banho')
    expect(dialogo.getByText('Texto ditado. Revise antes de salvar.')).toBeTruthy()
    expect(mockPost).not.toHaveBeenCalled()

    await user.type(campo, ', sem queixas')
    await user.click(dialogo.getByRole('button', { name: 'Realizado' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    const payload = mockPost.mock.calls[0][1] as Record<string, unknown>
    expect(payload.observacao).toBe('aceitou bem o banho, sem queixas')
    expect(Object.values(payload).some(v => v instanceof Blob)).toBe(false)
  })

  it('pacote baixável: instala para uso local antes de ouvir', async () => {
    const user = userEvent.setup()
    const Motor = instalarMotor({ local: true, disponibilidade: 'downloadable' })
    const dialogo = await abrirObservacao(user)
    await user.click(await dialogo.findByRole('button', { name: 'Ditar — observação' }))
    await waitFor(() => expect(instancia).not.toBeNull())
    expect(Motor.install).toHaveBeenCalledWith({ langs: ['pt-BR'], processLocally: true })
    expect(instancia.processLocally).toBe(true)
  })
})

describe('UX-01D — fim do ditado sem fala', () => {
  it('parar sem nada reconhecido limpa o "Ouvindo…" e avisa', async () => {
    const user = userEvent.setup()
    instalarMotor({ local: true })
    const dialogo = await abrirObservacao(user)
    await user.click(await dialogo.findByRole('button', { name: 'Ditar — observação' }))
    expect(dialogo.getByText(/Ouvindo/)).toBeTruthy()

    act(() => { instancia.onend() })
    expect(dialogo.queryByText(/Ouvindo/)).toBeNull()
    expect(dialogo.getByText('Nada foi reconhecido. Tente de novo ou digite.')).toBeTruthy()
    expect(dialogo.getByRole('button', { name: 'Ditar — observação' })).toBeTruthy()
    expect((dialogo.getByLabelText(/Observação/) as HTMLTextAreaElement).value).toBe('')
  })

  it('erro do microfone mantém a mensagem do erro, não a de "nada reconhecido"', async () => {
    const user = userEvent.setup()
    instalarMotor({ local: true })
    const dialogo = await abrirObservacao(user)
    await user.click(await dialogo.findByRole('button', { name: 'Ditar — observação' }))
    act(() => { instancia.onerror({ error: 'not-allowed' }); instancia.onend() })
    expect(dialogo.getByText('Permita o microfone para ditar.')).toBeTruthy()
    expect(dialogo.queryByText(/Nada foi reconhecido/)).toBeNull()
  })
})

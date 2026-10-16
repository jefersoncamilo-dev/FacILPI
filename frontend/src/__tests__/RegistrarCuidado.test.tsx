import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
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

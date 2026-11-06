import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PermissoesProvider } from '../context/PermissoesContext'
import { FamiliaresResidente } from '../components/prontuario/FamiliaresResidente'
import { api } from '../services/api'
import { contextApi } from '../services/context'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() } }
})
vi.mock('../services/context', () => ({
  contextApi: { permissoesDaSessao: vi.fn() },
}))

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)
const mockPut = vi.mocked(api.put)
const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

const FAMILIAR = {
  id: 'f1', residente_id: 'r1', nome: 'Ana Souza', parentesco: 'Filha', tipo_responsabilidade: 'Responsável legal',
  telefone: '11999990000', email: 'ana@example.com', cpf: '123.456.789-00', endereco: 'Rua A, 1', autorizacao_acesso: false,
}

function renderSecao(permissoes: string[]) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', ilpi_id: 'ilpi1', permissoes } } as any)
  mockGet.mockResolvedValue({ data: [FAMILIAR] } as any)
  return render(<PermissoesProvider><FamiliaresResidente residenteId="r1" /></PermissoesProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('M13 — Familiares e responsáveis', () => {
  it('lista os familiares do residente, filtrada no backend, sem CPF nem endereço na lista', async () => {
    renderSecao(['familiares:ler'])
    const secao = await screen.findByRole('region', { name: 'Familiares e responsáveis' })
    expect(await within(secao).findByText('Ana Souza')).toBeTruthy()
    expect(within(secao).getByText('Responsável legal')).toBeTruthy()
    expect(within(secao).getByRole('link', { name: '11999990000' }).getAttribute('href')).toBe('tel:11999990000')
    expect(within(secao).queryByText(/123\.456/)).toBeNull()
    expect(within(secao).queryByText(/Rua A/)).toBeNull()
    expect(mockGet).toHaveBeenCalledWith('/familiares/', { params: { residente_id: 'r1' } })
    // Só leitura: sem ações de escrita.
    expect(within(secao).queryByRole('button', { name: '+ Cadastrar' })).toBeNull()
    expect(within(secao).queryByRole('button', { name: 'Editar Ana Souza' })).toBeNull()
  })

  it('sem familiares:ler a seção não aparece nem consulta', async () => {
    renderSecao(['familiares:criar', 'familiares:atualizar'])
    await waitFor(() => expect(mockPermissoes).toHaveBeenCalled())
    await new Promise(r => setTimeout(r, 0))
    expect(screen.queryByRole('region', { name: 'Familiares e responsáveis' })).toBeNull()
    expect(mockGet).not.toHaveBeenCalled()
  })

  it('cadastra sem enviar ilpi_id, com residente_id da tela', async () => {
    const user = userEvent.setup()
    mockPost.mockResolvedValue({ data: {} } as any)
    renderSecao(['familiares:ler', 'familiares:criar'])
    await user.click(await screen.findByRole('button', { name: '+ Cadastrar' }))
    expect(screen.queryByRole('button', { name: 'Editar Ana Souza' })).toBeNull()
    await user.type(screen.getByLabelText('Nome'), 'João Lima')
    await user.type(screen.getByLabelText('Telefone'), '1133334444')
    await user.click(screen.getByRole('button', { name: 'Salvar' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalled())
    const [url, corpo] = mockPost.mock.calls[0] as [string, Record<string, unknown>]
    expect(url).toBe('/familiares/')
    expect(corpo).toMatchObject({ residente_id: 'r1', nome: 'João Lima', telefone: '1133334444', email: null })
    expect(corpo).not.toHaveProperty('ilpi_id')
    expect(await screen.findByText('Familiar cadastrado.')).toBeTruthy()
  })

  it('edita sem reenviar residente_id nem ilpi_id', async () => {
    const user = userEvent.setup()
    mockPut.mockResolvedValue({ data: {} } as any)
    renderSecao(['familiares:ler', 'familiares:atualizar'])
    await user.click(await screen.findByRole('button', { name: 'Editar Ana Souza' }))
    expect(screen.queryByRole('button', { name: '+ Cadastrar' })).toBeNull()
    const telefone = screen.getByLabelText('Telefone')
    await user.clear(telefone)
    await user.type(telefone, '11888887777')
    await user.click(screen.getByRole('button', { name: 'Salvar' }))
    await waitFor(() => expect(mockPut).toHaveBeenCalled())
    const [url, corpo] = mockPut.mock.calls[0] as [string, Record<string, unknown>]
    expect(url).toBe('/familiares/f1')
    expect(corpo).toMatchObject({ nome: 'Ana Souza', telefone: '11888887777' })
    expect(corpo).not.toHaveProperty('residente_id')
    expect(corpo).not.toHaveProperty('ilpi_id')
  })
})

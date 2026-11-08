import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { Residentes } from '../pages/Residentes'
import { api } from '../services/api'
import { contextApi } from '../services/context'

// Dados sintéticos: nomes fictícios, nenhum dado real.
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
const mockPost = vi.mocked(api.post)
const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

function renderCadastro(permissoes: string[]) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes } } as any)
  mockGet.mockImplementation((() => Promise.resolve({ data: [] })) as any)
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={['/residentes?novo=1']}>
        <PermissoesProvider>
          <Routes><Route path="/residentes" element={<Residentes />} /></Routes>
        </PermissoesProvider>
      </MemoryRouter>
    </AuthProvider>,
  )
}

async function preencherBasico(user: ReturnType<typeof userEvent.setup>) {
  const dialogo = await screen.findByRole('dialog', { name: 'Novo residente' })
  await user.type(within(dialogo).getByLabelText('Nome completo'), 'Ana Sintética')
  await user.type(within(dialogo).getByLabelText('Nascimento'), '1940-05-10')
  return dialogo
}

const BASE = ['residentes:ler', 'residentes:criar']

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('UX-NAV-3b — grau de dependência no cadastro', () => {
  it('aparece logo depois do nome, só com grau_dependencia:criar', async () => {
    renderCadastro([...BASE, 'grau_dependencia:criar'])
    const dialogo = await screen.findByRole('dialog', { name: 'Novo residente' })
    const grupo = within(dialogo).getByRole('group', { name: 'Grau de dependência' })
    expect(within(grupo).getAllByRole('radio').map(r => r.closest('label')!.textContent)).toEqual(['Grau I', 'Grau II', 'Grau III', 'Definir depois'])
    // Ordem no formulário: nome, depois grau, depois nascimento.
    const campos = [...dialogo.querySelectorAll('#res-nome, fieldset, #res-nascimento')]
    expect(campos.map(c => c.tagName)).toEqual(['INPUT', 'FIELDSET', 'INPUT'])
    expect(within(grupo).getByRole('radio', { name: 'Definir depois' })).toHaveProperty('checked', true)
  })

  it('sem grau_dependencia:criar, o campo não aparece', async () => {
    renderCadastro(BASE)
    const dialogo = await screen.findByRole('dialog', { name: 'Novo residente' })
    await waitFor(() => expect(mockPermissoes).toHaveBeenCalled())
    expect(within(dialogo).queryByRole('group', { name: 'Grau de dependência' })).toBeNull()
  })

  it('grau escolhido vira grau oficial (origem manual) depois do residente, sem ilpi nem autor no payload', async () => {
    const user = userEvent.setup()
    mockPost.mockImplementation(((url: string) =>
      Promise.resolve({ data: url === '/residentes/' ? { id: 'novo-1', nome: 'Ana Sintética' } : { id: 'g1' } })) as any)
    renderCadastro([...BASE, 'grau_dependencia:criar'])
    const dialogo = await preencherBasico(user)
    await user.click(within(dialogo).getByRole('radio', { name: 'Grau III' }))
    await user.type(within(dialogo).getByLabelText('Motivo do grau'), 'Acamada, ajuda total')
    await user.click(within(dialogo).getByRole('button', { name: 'Salvar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(2))
    expect(mockPost.mock.calls[0][0]).toBe('/residentes/')
    expect(mockPost.mock.calls[0][1]).not.toHaveProperty('grau_dependencia')
    expect(mockPost.mock.calls[1]).toEqual(['/graus-dependencia/', {
      residente_id: 'novo-1', classificacao: 'Grau III', origem: 'manual', justificativa: 'Acamada, ajuda total',
    }])
  })

  it('"Definir depois" não registra grau', async () => {
    const user = userEvent.setup()
    mockPost.mockResolvedValue({ data: { id: 'novo-1', nome: 'Ana Sintética' } } as any)
    renderCadastro([...BASE, 'grau_dependencia:criar'])
    const dialogo = await preencherBasico(user)
    await user.click(within(dialogo).getByRole('button', { name: 'Salvar' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect(mockPost.mock.calls[0][0]).toBe('/residentes/')
  })

  it('grau sem motivo não envia nada e explica', async () => {
    const user = userEvent.setup()
    renderCadastro([...BASE, 'grau_dependencia:criar'])
    const dialogo = await preencherBasico(user)
    await user.click(within(dialogo).getByRole('radio', { name: 'Grau II' }))
    const motivo = within(dialogo).getByLabelText('Motivo do grau')
    motivo.removeAttribute('required')
    await user.click(within(dialogo).getByRole('button', { name: 'Salvar' }))
    expect(await within(dialogo).findByText('Informe o motivo do grau de dependência escolhido.')).toBeTruthy()
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('falha ao gravar o grau não desfaz o residente e avisa onde concluir', async () => {
    const user = userEvent.setup()
    mockPost.mockImplementation(((url: string) => url === '/residentes/'
      ? Promise.resolve({ data: { id: 'novo-1', nome: 'Ana Sintética' } })
      : Promise.reject({ response: { status: 403, data: { detail: 'Sem permissão' } } })) as any)
    renderCadastro([...BASE, 'grau_dependencia:criar'])
    const dialogo = await preencherBasico(user)
    await user.click(within(dialogo).getByRole('radio', { name: 'Grau I' }))
    await user.type(within(dialogo).getByLabelText('Motivo do grau'), 'Independente')
    await user.click(within(dialogo).getByRole('button', { name: 'Salvar' }))
    expect(await screen.findByText(/Ana Sintética foi cadastrado, mas o grau de dependência não foi registrado/)).toBeTruthy()
    expect(screen.getByText(/Registre o grau na ficha do residente/)).toBeTruthy()
  })
})

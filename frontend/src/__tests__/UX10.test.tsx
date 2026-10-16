import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { PerfilFormModal } from '../components/equipe/PerfilFormModal'
import { FuncionarioCard } from '../components/equipe/FuncionarioCard'
import { Equipe } from '../pages/Equipe'
import { api } from '../services/api'
import { contextApi } from '../services/context'
import type { Perfil, Permissao } from '../types/equipe'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() } }
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

const perm = (modulo: string, acao: string): Permissao => ({ id: `${modulo}-${acao}`, modulo, acao, chave: `${modulo}:${acao}`, descricao: null })
const CATALOGO = [perm('funcionarios', 'ler'), perm('funcionarios', 'criar'), perm('usuarios', 'ler')]
const PERFIL: Perfil = { id: 'p1', ilpi_id: 'i1', nome: 'Recepção', chave: 'recepcao', descricao: null, escopo: 'ilpi', situacao: 'ativo' }
const atual = (itens: [string, string, boolean][]) => ({
  perfil_id: 'p1',
  permissoes: itens.map(([modulo, acao, editavel]) => ({ modulo, acao, chave: `${modulo}:${acao}`, descricao: null, editavel })),
  editavel: itens.every(([, , e]) => e),
})

function respondePerfil(resposta: unknown) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/perfis/p1/permissoes') return resposta instanceof Error ? Promise.reject(resposta) : Promise.resolve({ data: resposta } as any)
    throw new Error(`URL inesperada: ${url}`)
  })
}

function renderModal(props: Partial<React.ComponentProps<typeof PerfilFormModal>> = {}) {
  const onSubmitPermissoes = vi.fn(async () => {})
  render(
    <PerfilFormModal open perfil={PERFIL} permissoes={CATALOGO} allPerfis={[PERFIL]} onClose={vi.fn()}
      onSubmitPerfil={vi.fn()} onSubmitPermissoes={onSubmitPermissoes} {...props} />,
  )
  return { onSubmitPermissoes }
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('UX-10 — permissões de perfil partem do que o perfil tem', () => {
  it('marca só as permissões reais e salva exatamente a mudança feita', async () => {
    const user = userEvent.setup()
    respondePerfil(atual([['funcionarios', 'ler', true]]))
    const { onSubmitPermissoes } = renderModal()
    await screen.findAllByRole('checkbox')
    await waitFor(() => expect((screen.getAllByRole('checkbox') as HTMLInputElement[]).map(c => c.checked)).toEqual([true, false, false]))
    const salvar = screen.getByRole('button', { name: 'Salvar permissões' })
    expect(salvar).toHaveProperty('disabled', true)

    await user.click(screen.getAllByRole('checkbox')[2])
    expect(screen.getByText('+1 concedida(s)')).toBeTruthy()
    await user.click(salvar)
    expect(onSubmitPermissoes).toHaveBeenCalledWith('p1', ['funcionarios:ler', 'usuarios:ler'])
  })

  it('perfil com permissão fora do catálogo local fica só para leitura', async () => {
    respondePerfil(atual([['funcionarios', 'ler', true], ['residentes', 'ler', false]]))
    renderModal()
    expect(await screen.findByText('Edição indisponível nesta tela')).toBeTruthy()
    expect(screen.getByText(/Residentes\)\. Salvar por esta tela as removeria/)).toBeTruthy()
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Salvar permissões' })).toBeNull()
    expect(screen.getByText('Fechar', { selector: 'button' })).toBeTruthy()
  })

  it('sem a leitura das permissões atuais, não há edição', async () => {
    respondePerfil(new Error('rede'))
    renderModal()
    expect(await screen.findByText('Não foi possível carregar as permissões atuais')).toBeTruthy()
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Salvar permissões' })).toBeNull()
  })

  it('sem permissão para atribuir, mostra o que o perfil pode fazer sem editar', async () => {
    respondePerfil(atual([['funcionarios', 'ler', true], ['funcionarios', 'criar', true]]))
    renderModal({ somenteLeitura: true })
    const lista = await screen.findByText('Funcionários')
    expect(within(lista.closest('div')!).getByText('Cadastrar')).toBeTruthy()
    expect(screen.queryByRole('checkbox')).toBeNull()
  })

  it('perfil novo começa sem nenhuma permissão marcada', async () => {
    const user = userEvent.setup()
    const onSubmitPerfil = vi.fn(async () => ({ ...PERFIL, id: 'novo' }))
    renderModal({ perfil: null, onSubmitPerfil })
    await user.type(screen.getByPlaceholderText('Ex: Enfermeiro Chefe'), 'Recepção')
    await user.type(screen.getByPlaceholderText('Ex: enfermeiro_chefe'), 'recepcao')
    await user.click(screen.getByRole('button', { name: 'Criar perfil' }))
    const caixas = await screen.findAllByRole('checkbox') as HTMLInputElement[]
    expect(caixas.every(c => !c.checked)).toBe(true)
    expect(mockGet).not.toHaveBeenCalled()
  })
})

describe('UX-10 — ações só para quem o backend aceitaria', () => {
  const funcionario = {
    id: 'f1', ilpi_id: 'i1', usuario_id: null, nome: 'Maria Silva', cpf: null, telefone: null, email: null,
    cargo: null, profissao: null, conselho_profissional: null, numero_conselho: null, uf_conselho: null, situacao: 'ativo',
  } as any
  const acoes = { onEdit: vi.fn(), onConcederAcesso: vi.fn(), onVincular: vi.fn(), onRevogarAcesso: vi.fn(), onInativar: vi.fn() }

  function comPermissoes(ui: React.ReactElement, permissoes: string[]) {
    mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes } } as any)
    return render(<AuthProvider><MemoryRouter><PermissoesProvider>{ui}</PermissoesProvider></MemoryRouter></AuthProvider>)
  }

  it('cartão: só leitura não tem menu; com permissão, só as ações permitidas', async () => {
    const user = userEvent.setup()
    const leitura = comPermissoes(<FuncionarioCard funcionario={funcionario} {...acoes} />, ['funcionarios:ler'])
    expect(await screen.findByText('Maria Silva')).toBeTruthy()
    await waitFor(() => expect(mockPermissoes).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: 'Ações' })).toBeNull()
    leitura.unmount()

    comPermissoes(<FuncionarioCard funcionario={funcionario} {...acoes} />, ['funcionarios:ler', 'funcionarios:atualizar', 'funcionarios:vincular_usuario'])
    await user.click(await screen.findByRole('button', { name: 'Ações' }))
    expect(screen.getByRole('button', { name: /Editar/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Vincular usuário existente/ })).toBeTruthy()
    // Conceder acesso cria usuário: sem usuarios:criar, não aparece.
    expect(screen.queryByRole('button', { name: /Conceder acesso/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Inativar funcionário/ })).toBeNull()
  })

  it('Equipe: sem permissão, sem abas de usuários/perfis nem cadastro; perfis sem atribuir abre só para ver', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === '/funcionarios/') return Promise.resolve({ data: [] } as any)
      if (url === '/perfis/') return Promise.resolve({ data: [PERFIL] } as any)
      if (url === '/permissoes/') return Promise.resolve({ data: CATALOGO } as any)
      throw new Error(`URL inesperada: ${url}`)
    })
    const so = comPermissoes(<Equipe />, ['funcionarios:ler'])
    expect(await screen.findByText('Nenhum funcionário encontrado')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Usuários/ })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Perfis' })).toBeNull()
    expect(screen.queryByRole('button', { name: '+ Novo funcionário' })).toBeNull()
    expect(mockGet).not.toHaveBeenCalledWith('/usuarios/')
    so.unmount()

    const user = userEvent.setup()
    comPermissoes(<Equipe />, ['funcionarios:ler', 'perfis:ler', 'permissoes:ler'])
    await user.click(await screen.findByRole('button', { name: 'Perfis' }))
    expect(await screen.findByRole('button', { name: /Ver permissões/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Ver e editar permissões/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Novo perfil/ })).toBeNull()
  })

  it('Equipe: sem nenhuma permissão da equipe, explica o bloqueio; 403 não vira "nenhum funcionário"', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === '/funcionarios/') return Promise.reject({ response: { status: 403, data: { detail: 'Permissão não autorizada' } } })
      throw new Error(`URL inesperada: ${url}`)
    })
    const sem = comPermissoes(<Equipe />, ['plantao:ler'])
    expect(await screen.findByText('Sem acesso à equipe')).toBeTruthy()
    expect(screen.queryByText('Nenhum funcionário encontrado')).toBeNull()
    expect(mockGet).not.toHaveBeenCalledWith('/funcionarios/', expect.anything())
    sem.unmount()

    comPermissoes(<Equipe />, ['funcionarios:ler'])
    expect(await screen.findByText('Permissão não autorizada')).toBeTruthy()
    expect(screen.queryByText('Nenhum funcionário encontrado')).toBeNull()
  })
})

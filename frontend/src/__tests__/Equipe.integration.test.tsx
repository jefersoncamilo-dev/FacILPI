import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Equipe } from '../pages/Equipe'
import { equipeApi } from '../services/equipe'

vi.mock('../services/equipe', () => ({
  equipeApi: {
    listFuncionarios: vi.fn(),
    getFuncionario: vi.fn(),
    createFuncionario: vi.fn(),
    updateFuncionario: vi.fn(),
    inativarFuncionario: vi.fn(),
    vincularUsuario: vi.fn(),
    desvincularUsuario: vi.fn(),
    listUsuarios: vi.fn(),
    getUsuario: vi.fn(),
    createUsuario: vi.fn(),
    updateUsuario: vi.fn(),
    resetPassword: vi.fn(),
    atribuirPerfil: vi.fn(),
    revogarAcesso: vi.fn(),
    listPerfis: vi.fn(),
    createPerfil: vi.fn(),
    updatePermissoes: vi.fn(),
    listPermissoes: vi.fn(),
  },
}))

const api = vi.mocked(equipeApi)

const funcSemAcesso = {
  id: 'f1', ilpi_id: 'ilpi1', usuario_id: null,
  nome: 'Ana Souza', cpf: '12345678901', telefone: '11999998888',
  email: 'ana@test.com', cargo: 'Cuidadora', profissao: 'Cuidador',
  conselho_profissional: null, numero_conselho: null, uf_conselho: null,
  situacao: 'ativo',
}

const funcComAcesso = {
  id: 'f2', ilpi_id: 'ilpi1', usuario_id: 'u1',
  nome: 'Bruno Lima', cpf: null, telefone: null,
  email: 'bruno@test.com', cargo: 'Enfermeiro', profissao: 'Enfermeiro',
  conselho_profissional: 'COREN', numero_conselho: '12345', uf_conselho: 'SP',
  situacao: 'ativo',
}

const usuarios = [
  { id: 'u1', nome: 'Bruno Lima', email: 'bruno@test.com', ativo: true, is_superuser: false, exige_troca_senha: false },
]

const perfis = [
  { id: 'p1', ilpi_id: 'ilpi1', nome: 'Administrador', chave: 'ilpi_admin', descricao: null, escopo: 'ilpi', situacao: 'ativo' },
  { id: 'p2', ilpi_id: 'ilpi1', nome: 'Enfermeiro Plantão', chave: 'enfermeiro_plantao', descricao: null, escopo: 'ilpi', situacao: 'inativo' },
  { id: 'p9', ilpi_id: null, nome: 'Super', chave: 'platform_superuser', descricao: null, escopo: 'global', situacao: 'ativo' },
]

function mockDefaults() {
  api.listFuncionarios.mockResolvedValue({ data: [funcSemAcesso, funcComAcesso] } as any)
  api.listUsuarios.mockResolvedValue({ data: usuarios } as any)
  api.listPerfis.mockResolvedValue({ data: perfis } as any)
  api.listPermissoes.mockResolvedValue({ data: [] } as any)
}

beforeEach(() => {
  vi.clearAllMocks()
  mockDefaults()
})

async function openCardMenu(index: number, itemText: string | RegExp) {
  const user = userEvent.setup()
  const menus = screen.getAllByLabelText('Ações')
  await user.click(menus[index])
  const item = await screen.findByText(itemText)
  await user.click(item)
  return user
}

describe('Equipe page — loading / empty / error', () => {
  it('mostra skeleton durante o carregamento e depois os dados', async () => {
    let resolveList!: (v: any) => void
    api.listFuncionarios.mockReturnValueOnce(new Promise((r) => { resolveList = r }))
    render(<Equipe />)
    expect(document.querySelector('.animate-pulse')).not.toBeNull()
    resolveList({ data: [funcSemAcesso] })
    expect(await screen.findByText('Ana Souza')).toBeInTheDocument()
  })

  it('mostra estado vazio quando não há funcionários', async () => {
    api.listFuncionarios.mockResolvedValueOnce({ data: [] } as any)
    render(<Equipe />)
    expect(await screen.findByText('Nenhum funcionário encontrado')).toBeInTheDocument()
  })

  it('mostra mensagem de erro quando a API falha', async () => {
    api.listFuncionarios.mockRejectedValueOnce({ response: { data: { detail: 'Falha de rede' } } })
    render(<Equipe />)
    expect(await screen.findByText('Falha de rede')).toBeInTheDocument()
  })
})

describe('Equipe page — CRUD funcionário', () => {
  it('cria funcionário sem login e envia payload sem ilpi_id', async () => {
    const user = userEvent.setup()
    api.createFuncionario.mockResolvedValueOnce({ data: { ...funcSemAcesso, id: 'f9' } } as any)
    const { container } = render(<Equipe />)
    await screen.findByText('Ana Souza')

    await user.click(screen.getByRole('button', { name: '+ Novo funcionário' }))
    const form = container.querySelector('form')!
    const inputs = within(form).getAllByRole('textbox')
    await user.type(inputs[0], 'Carlos Novaes')
    await user.click(within(form).getByRole('button', { name: 'Cadastrar' }))

    await waitFor(() => expect(api.createFuncionario).toHaveBeenCalledTimes(1))
    const payload = api.createFuncionario.mock.calls[0][0] as unknown as Record<string, unknown>
    expect(payload.nome).toBe('Carlos Novaes')
    expect(payload).not.toHaveProperty('ilpi_id')
    expect(payload).not.toHaveProperty('usuario_id')
    expect(payload.criar_usuario).toBe(false)
  })

  it('edita funcionário enviando apenas campos do schema de update', async () => {
    const user = userEvent.setup()
    api.updateFuncionario.mockResolvedValueOnce({ data: { ...funcSemAcesso, cargo: 'Técnica' } } as any)
    const { container } = render(<Equipe />)
    await screen.findByText('Ana Souza')

    await openCardMenu(0, 'Editar')
    const form = container.querySelector('form')!
    const inputs = within(form).getAllByRole('textbox')
    const cargoInput = inputs.find((i) => (i as HTMLInputElement).value === 'Cuidadora')!
    await user.clear(cargoInput)
    await user.type(cargoInput, 'Técnica')
    await user.click(within(form).getByRole('button', { name: 'Salvar alterações' }))

    await waitFor(() => expect(api.updateFuncionario).toHaveBeenCalledTimes(1))
    expect(api.updateFuncionario).toHaveBeenCalledWith('f1', expect.objectContaining({ cargo: 'Técnica' }))
    const payload = api.updateFuncionario.mock.calls[0][1] as Record<string, unknown>
    expect(payload).not.toHaveProperty('criar_usuario')
    expect(payload).not.toHaveProperty('perfil_id')
  })

  it('inativa funcionário e atualiza situação na UI', async () => {
    api.inativarFuncionario.mockResolvedValueOnce({} as any)
    render(<Equipe />)
    await screen.findByText('Ana Souza')

    await openCardMenu(0, 'Inativar funcionário')
    const confirmBtn = await screen.findByRole('button', { name: 'Inativar funcionário' })
    await userEvent.setup().click(confirmBtn)

    await waitFor(() => expect(api.inativarFuncionario).toHaveBeenCalledWith('f1'))
    expect(await screen.findAllByText('Inativo')).not.toHaveLength(0)
  })
})

describe('Equipe page — acesso e vínculo (P1-01 / P1-02)', () => {
  it('edita usuário enviando o nome NOVO digitado (regressão P1-01)', async () => {
    const user = userEvent.setup()
    api.updateUsuario.mockResolvedValueOnce({ data: { ...usuarios[0], nome: 'Bruno Novo' } } as any)
    render(<Equipe />)
    await screen.findByText('Ana Souza')

    await user.click(screen.getByRole('button', { name: /Usuários/ }))
    await screen.findByText('bruno@test.com')
    await user.click(screen.getByRole('button', { name: /Editar/ }))

    const nameInput = await screen.findByDisplayValue('Bruno Lima')
    await user.clear(nameInput)
    await user.type(nameInput, 'Bruno Novo')
    await user.click(screen.getByRole('button', { name: 'Salvar' }))

    await waitFor(() => expect(api.updateUsuario).toHaveBeenCalledTimes(1))
    expect(api.updateUsuario).toHaveBeenCalledWith('u1', { nome: 'Bruno Novo' })
  })

  it('concede acesso: cria usuário, vincula e exibe senha temporária uma vez', async () => {
    const user = userEvent.setup()
    api.createUsuario.mockResolvedValueOnce({ data: { id: 'u9', nome: 'Ana Souza', email: 'ana@test.com', senha_temporaria: 'Tmp123!x' } } as any)
    api.vincularUsuario.mockResolvedValueOnce({ data: { ...funcSemAcesso, usuario_id: 'u9' } } as any)
    const { container } = render(<Equipe />)
    await screen.findByText('Ana Souza')

    await openCardMenu(0, 'Conceder acesso')
    const select = container.querySelector('select') as HTMLSelectElement
    // somente perfis ativos aparecem como opção
    const options = within(select).getAllByRole('option').map((o) => o.textContent)
    expect(options).toContain('Administrador')
    expect(options).not.toContain('Enfermeiro Plantão')
    expect(options).not.toContain('Super')
    await user.selectOptions(select, 'p1')
    await user.click(screen.getByRole('button', { name: 'Conceder acesso' }))

    await waitFor(() => expect(api.createUsuario).toHaveBeenCalledWith(
      expect.objectContaining({ nome: 'Ana Souza', email: 'ana@test.com', perfil_id: 'p1' }),
    ))
    expect(api.vincularUsuario).toHaveBeenCalledWith('f1', 'u9')
    expect(await screen.findByText('Tmp123!x')).toBeInTheDocument()
  })

  it('vincula usuário existente ao funcionário', async () => {
    const user = userEvent.setup()
    api.vincularUsuario.mockResolvedValueOnce({ data: { ...funcSemAcesso, usuario_id: 'u1' } } as any)
    render(<Equipe />)
    await screen.findByText('Ana Souza')

    await openCardMenu(0, 'Vincular usuário existente')
    const radio = await screen.findByRole('radio')
    await user.click(radio)
    await user.click(screen.getByRole('button', { name: 'Vincular' }))

    await waitFor(() => expect(api.vincularUsuario).toHaveBeenCalledWith('f1', 'u1'))
  })

  it('revoga acesso recarregando do backend sem inventar ativo:false (regressão P1-02)', async () => {
    const user = userEvent.setup()
    api.revogarAcesso.mockResolvedValueOnce({ data: { usuario_id: 'u1', acesso_revogado: true } } as any)
    // mount: estado pré-revogação; reloads: backend sem o vínculo
    api.listFuncionarios
      .mockResolvedValueOnce({ data: [funcSemAcesso, funcComAcesso] } as any)
      .mockResolvedValue({ data: [funcSemAcesso, { ...funcComAcesso, usuario_id: null }] } as any)
    api.listUsuarios
      .mockResolvedValueOnce({ data: usuarios } as any)
      .mockResolvedValue({ data: [] } as any)
    render(<Equipe />)
    await screen.findByText('Bruno Lima')

    await openCardMenu(1, 'Revogar acesso')
    const confirmBtn = await screen.findByRole('button', { name: 'Revogar acesso' })
    await user.click(confirmBtn)

    await waitFor(() => expect(api.revogarAcesso).toHaveBeenCalledWith('u1'))
    // sincroniza com a fonte de verdade: listas recarregadas, sem PUT inventado
    await waitFor(() => expect(api.listUsuarios.mock.calls.length).toBeGreaterThanOrEqual(2))
    expect(api.updateUsuario).not.toHaveBeenCalled()
    // funcionário permanece cadastrado...
    expect(await screen.findByText('Bruno Lima')).toBeInTheDocument()
    // ...mas o acesso desaparece da UI
    await user.click(screen.getByRole('button', { name: /Usuários/ }))
    expect(await screen.findByText('Nenhum usuário encontrado')).toBeInTheDocument()
  })

  it('reseta senha e exibe a temporária', async () => {
    const user = userEvent.setup()
    api.resetPassword.mockResolvedValueOnce({ data: { senha_temporaria: 'Reset999!' } } as any)
    render(<Equipe />)
    await screen.findByText('Ana Souza')

    await user.click(screen.getByRole('button', { name: /Usuários/ }))
    await screen.findByText('bruno@test.com')
    await user.click(screen.getByRole('button', { name: /Resetar senha/ }))
    await user.click(screen.getByRole('button', { name: 'Redefinir senha' }))

    await waitFor(() => expect(api.resetPassword).toHaveBeenCalledWith('u1'))
    expect(await screen.findByText('Reset999!')).toBeInTheDocument()
  })
})

describe('Equipe page — profissão regulamentada e perfis', () => {
  it('exige conselho para profissão regulamentada e envia no payload', async () => {
    const user = userEvent.setup()
    api.createFuncionario.mockResolvedValueOnce({ data: { ...funcSemAcesso, id: 'f9' } } as any)
    const { container } = render(<Equipe />)
    await screen.findByText('Ana Souza')

    await user.click(screen.getByRole('button', { name: '+ Novo funcionário' }))
    const form = container.querySelector('form')!
    const inputs = within(form).getAllByRole('textbox')
    await user.type(inputs[0], 'Enfermeira Nova')
    // profissão é o 5º textbox (nome, cpf, telefone, email, cargo, profissao)
    await user.type(inputs[5], 'Enfermeiro')

    const conselho = await within(form).findByPlaceholderText('Ex: COREN')
    await user.type(conselho, 'COREN')
    const selects = within(form).getAllByRole('combobox')
    const ufSelect = selects[selects.length - 1]
    await user.selectOptions(ufSelect, 'SP')
    // número do registro: último textbox do bloco de conselho
    const allInputs = within(form).getAllByRole('textbox')
    await user.type(allInputs[allInputs.length - 1], '98765')
    await user.click(within(form).getByRole('button', { name: 'Cadastrar' }))

    await waitFor(() => expect(api.createFuncionario).toHaveBeenCalledTimes(1))
    const payload = api.createFuncionario.mock.calls[0][0] as unknown as Record<string, unknown>
    expect(payload.profissao).toBe('Enfermeiro')
    expect(payload.conselho_profissional).toBe('COREN')
    expect(payload.uf_conselho).toBe('SP')
  })

  it('não mostra campos de conselho para profissão não regulamentada', async () => {
    const user = userEvent.setup()
    const { container } = render(<Equipe />)
    await screen.findByText('Ana Souza')

    await user.click(screen.getByRole('button', { name: '+ Novo funcionário' }))
    const form = container.querySelector('form')!
    const inputs = within(form).getAllByRole('textbox')
    await user.type(inputs[5], 'Cuidador')
    expect(within(form).queryByPlaceholderText('Ex: COREN')).toBeNull()
  })

  it('aba Perfis lista ativos e inativos, sem platform_superuser', async () => {
    const user = userEvent.setup()
    render(<Equipe />)
    await screen.findByText('Ana Souza')

    await user.click(screen.getByRole('button', { name: 'Perfis' }))
    expect(await screen.findByText('Administrador')).toBeInTheDocument()
    expect(await screen.findByText('Enfermeiro Plantão')).toBeInTheDocument()
    // nenhum card de perfil global selecionável (o nome só aparece no texto informativo)
    expect(screen.queryByText('Super')).toBeNull()
    expect(api.listPerfis).toHaveBeenCalled()
    expect(api.listPermissoes).toHaveBeenCalled()
  })
})

describe('Equipe page — filtro dispara uma única requisição (P2-02)', () => {
  it('trocar situacaoFilter chama listFuncionarios exatamente 1 vez', async () => {
    const user = userEvent.setup()
    render(<Equipe />)
    await screen.findByText('Ana Souza')
    expect(api.listFuncionarios).toHaveBeenCalledTimes(1)

    vi.clearAllMocks()
    mockDefaults()
    await user.click(screen.getByRole('button', { name: 'Inativos' }))

    await waitFor(() => expect(api.listFuncionarios).toHaveBeenCalledTimes(1))
    expect(api.listFuncionarios).toHaveBeenCalledWith('inativo')
  })
})

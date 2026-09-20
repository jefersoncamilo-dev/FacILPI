import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { PrivateRoute } from '../components/PrivateRoute'
import { PlatformRoute } from '../components/PlatformRoute'
import { PlatformInstituicoes } from '../pages/PlatformInstituicoes'
import { PlatformInstituicaoNova } from '../pages/PlatformInstituicaoNova'
import { PlatformInstituicaoDetalhe } from '../pages/PlatformInstituicaoDetalhe'
import { PrimeiroAcesso } from '../pages/PrimeiroAcesso'
import { api } from '../services/api'
import { TOKEN_KEY, USER_KEY, CONTEXT_KEY } from '../types/context'

// Preserva mensagemDeErro/formatDate reais: substituir o módulo inteiro deixaria
// esses helpers indefinidos nas telas sob teste.
vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
})

vi.mock('../services/context', () => ({
  contextApi: { selectContext: vi.fn(), listInstitutions: vi.fn(async () => ({ data: [] })), listPerfis: vi.fn() },
  resolveContextLabels: vi.fn(async (ctx: any) => ctx),
}))

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)
const mockPut = vi.mocked(api.put)

function jwt(payload: object): string {
  const b64 = (o: object) =>
    btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${b64({ alg: 'HS256' })}.${b64(payload)}.sig`
}

const FUTURE = Math.floor(Date.now() / 1000) + 3600
const TOKEN_OPERADOR = jwt({ sub: 'op1', email: 'admin@ilpi.com', is_superuser: true, exp: FUTURE })
const TOKEN_GESTOR = jwt({ sub: 'g1', email: 'gestor@ilpi.com', scope: 'ilpi', ilpi_id: 'ilpi1', perfil_id: 'p1', exp: FUTURE })
// Primeiro acesso: o backend devolve scope nulo, e contextFromToken apresenta
// isso como 'global'. É o caso que exige a checagem de is_superuser.
const TOKEN_PRIMEIRO_ACESSO = jwt({ sub: 'g2', email: 'novo@ilpi.com', exige_troca_senha: true, exp: FUTURE })

const ILPI_RASCUNHO = {
  id: 'ilpi1',
  razao_social: 'Casa Serena',
  nome_fantasia: 'Serena',
  situacao: 'ILPI_RASCUNHO',
  capacidade: 20,
  municipio: 'São Paulo',
  uf: 'SP',
  created_at: '2026-01-10T12:00:00Z',
}
const ILPI_ATIVA = { ...ILPI_RASCUNHO, id: 'ilpi2', razao_social: 'Vila Nova', nome_fantasia: null, situacao: 'ATIVA' }

function seed(token: string, ctx: object) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify({ id: 'x', nome: 'Operador', email: 'admin@ilpi.com' }))
  localStorage.setItem(CONTEXT_KEY, JSON.stringify(ctx))
}

function renderRotas(entrada: string) {
  return render(
    <MemoryRouter initialEntries={[entrada]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<div>TELA-LOGIN</div>} />
          <Route path="/primeiro-acesso" element={<PrivateRoute><PrimeiroAcesso /></PrivateRoute>} />
          <Route path="/" element={<PrivateRoute><div>APP-INSTITUCIONAL</div></PrivateRoute>} />
          <Route path="/platform" element={<Navigate to="/platform/instituicoes" replace />} />
          <Route path="/platform/instituicoes" element={<PlatformRoute><PlatformInstituicoes /></PlatformRoute>} />
          <Route path="/platform/instituicoes/nova" element={<PlatformRoute><PlatformInstituicaoNova /></PlatformRoute>} />
          <Route path="/platform/instituicoes/:id" element={<PlatformRoute><PlatformInstituicaoDetalhe /></PlatformRoute>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('PlatformRoute — separação de experiências', () => {
  it('1. operador global entra na Central', async () => {
    seed(TOKEN_OPERADOR, { scope: 'global' })
    mockGet.mockResolvedValue({ data: [] } as any)
    renderRotas('/platform/instituicoes')
    expect(await screen.findByRole('heading', { name: 'Instituições' })).toBeTruthy()
  })

  it('2. usuário institucional é desviado da Central', async () => {
    seed(TOKEN_GESTOR, { scope: 'ilpi', ilpi_id: 'ilpi1' })
    renderRotas('/platform/instituicoes')
    expect(await screen.findByText('APP-INSTITUCIONAL')).toBeTruthy()
  })

  it('3. gestor em primeiro acesso NÃO entra na Central', async () => {
    // contextFromToken o apresenta como global; só is_superuser o distingue.
    seed(TOKEN_PRIMEIRO_ACESSO, { scope: 'global' })
    renderRotas('/platform/instituicoes')
    expect(await screen.findByRole('heading', { name: 'Defina sua nova senha' })).toBeTruthy()
  })

  it('4. superusuário em troca obrigatória permanece no primeiro acesso, sem laço', async () => {
    const token = jwt({ sub: 'op1', email: 'admin@ilpi.com', is_superuser: true, exige_troca_senha: true, exp: FUTURE })
    seed(token, { scope: 'global' })
    renderRotas('/primeiro-acesso')
    expect(await screen.findByRole('heading', { name: 'Defina sua nova senha' })).toBeTruthy()
  })

  it('5. operador global é desviado da aplicação institucional', async () => {
    seed(TOKEN_OPERADOR, { scope: 'global' })
    mockGet.mockResolvedValue({ data: [] } as any)
    renderRotas('/')
    expect(await screen.findByRole('heading', { name: 'Instituições' })).toBeTruthy()
  })

  it('6. sem autenticação vai para login', async () => {
    renderRotas('/platform/instituicoes')
    expect(await screen.findByText('TELA-LOGIN')).toBeTruthy()
  })
})

describe('Central — listagem', () => {
  beforeEach(() => seed(TOKEN_OPERADOR, { scope: 'global' }))

  it('7. lista instituições com situação', async () => {
    mockGet.mockResolvedValue({ data: [ILPI_RASCUNHO, ILPI_ATIVA] } as any)
    renderRotas('/platform/instituicoes')
    expect(await screen.findByText('Serena')).toBeTruthy()
    expect(screen.getByText('Vila Nova')).toBeTruthy()
    expect(screen.getByText('Em configuração')).toBeTruthy()
    expect(screen.getByText('Ativa')).toBeTruthy()
  })

  it('8. estado vazio orienta o operador', async () => {
    mockGet.mockResolvedValue({ data: [] } as any)
    renderRotas('/platform/instituicoes')
    expect(await screen.findByText('Nenhuma instituição cadastrada.')).toBeTruthy()
  })

  it('9. erro de carregamento é exibido', async () => {
    mockGet.mockRejectedValue({ response: { status: 403, data: { detail: { message: 'Sem permissão' } } } })
    renderRotas('/platform/instituicoes')
    expect(await screen.findByRole('alert')).toHaveTextContent('Sem permissão')
  })

  it('10. busca filtra a lista carregada', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValue({ data: [ILPI_RASCUNHO, ILPI_ATIVA] } as any)
    renderRotas('/platform/instituicoes')
    await screen.findByText('Serena')
    await user.type(screen.getByLabelText('Buscar instituições'), 'Vila')
    await waitFor(() => expect(screen.queryByText('Serena')).toBeNull())
    expect(screen.getByText('Vila Nova')).toBeTruthy()
  })
})

describe('Central — criação e edição', () => {
  beforeEach(() => seed(TOKEN_OPERADOR, { scope: 'global' }))

  it('11. cria ILPI com o contrato real', async () => {
    const user = userEvent.setup()
    mockPost.mockResolvedValue({ data: ILPI_RASCUNHO } as any)
    mockGet.mockResolvedValue({ data: ILPI_RASCUNHO } as any)
    renderRotas('/platform/instituicoes/nova')

    await user.type(screen.getByLabelText(/Razão social/), 'Casa Serena')
    await user.type(screen.getByLabelText(/Capacidade/), '20')
    await user.click(screen.getByRole('button', { name: 'Criar instituição' }))

    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/platform/instituicoes', {
        razao_social: 'Casa Serena',
        capacidade: 20,
      }),
    )
  })

  it('12. capacidade zero não chega à rede', async () => {
    // O backend recusa com CAPACIDADE_REQUIRED; a tela nem chega a perguntar.
    // Quem barra primeiro é a restrição nativa `min=1` do campo — por isso a
    // asserção é sobre o que importa (nada é enviado), e não sobre qual das duas
    // camadas interceptou.
    const user = userEvent.setup()
    renderRotas('/platform/instituicoes/nova')
    await user.type(screen.getByLabelText(/Razão social/), 'Casa Serena')
    await user.type(screen.getByLabelText(/Capacidade/), '0')
    await user.click(screen.getByRole('button', { name: 'Criar instituição' }))
    await waitFor(() => expect(mockPost).not.toHaveBeenCalled())
  })

  it('13. edita dados sem enviar situacao', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValue({ data: ILPI_RASCUNHO } as any)
    mockPut.mockResolvedValue({ data: { ...ILPI_RASCUNHO, nome_fantasia: 'Serena II' } } as any)
    renderRotas('/platform/instituicoes/ilpi1')

    const campo = await screen.findByLabelText('Nome fantasia')
    await user.clear(campo)
    await user.type(campo, 'Serena II')
    await user.click(screen.getByRole('button', { name: 'Salvar dados' }))

    await waitFor(() => expect(mockPut).toHaveBeenCalled())
    const enviado = mockPut.mock.calls[0][1] as Record<string, unknown>
    expect(enviado.nome_fantasia).toBe('Serena II')
    expect(enviado).not.toHaveProperty('situacao')
  })
})

describe('Central — primeiro gestor e credencial', () => {
  beforeEach(() => seed(TOKEN_OPERADOR, { scope: 'global' }))

  // O detalhe mostra dois formulários na mesma tela, e "Nome"/"Telefone"/"E-mail"
  // existem nos dois. O seletor por id desambigua sem depender do texto.
  async function cadastrarGestor(user: ReturnType<typeof userEvent.setup>) {
    await user.type(await screen.findByLabelText(/Nome/, { selector: '#gestor_nome' }), 'Maria Gestora')
    await user.type(screen.getByLabelText(/E-mail/, { selector: '#gestor_email' }), 'maria@casa.com.br')
    await user.click(screen.getByRole('button', { name: 'Cadastrar primeiro gestor' }))
  }

  it('14. cria gestor e exibe a senha temporária uma vez', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValue({ data: ILPI_RASCUNHO } as any)
    mockPost.mockResolvedValue({
      data: { id: 'u1', nome: 'Maria Gestora', email: 'maria@casa.com.br', ativo: true, is_superuser: false, exige_troca_senha: true, senha_temporaria: 'Aa1!segredo' },
    } as any)

    renderRotas('/platform/instituicoes/ilpi1')
    await cadastrarGestor(user)

    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/platform/instituicoes/ilpi1/primeiro-gestor', {
        nome: 'Maria Gestora',
        email: 'maria@casa.com.br',
      }),
    )
    expect(await screen.findByTestId('senha-temporaria')).toHaveTextContent('Aa1!segredo')
    expect(screen.getByText(/exibida somente agora/i)).toBeTruthy()
  })

  it('15. senha temporária não é persistida em storage algum', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValue({ data: ILPI_RASCUNHO } as any)
    mockPost.mockResolvedValue({
      data: { id: 'u1', nome: 'Maria', email: 'maria@casa.com.br', ativo: true, is_superuser: false, exige_troca_senha: true, senha_temporaria: 'Aa1!segredo' },
    } as any)

    renderRotas('/platform/instituicoes/ilpi1')
    await cadastrarGestor(user)
    await screen.findByTestId('senha-temporaria')

    const local = JSON.stringify(Object.entries(localStorage))
    const sessao = JSON.stringify(Object.entries(sessionStorage))
    expect(local).not.toContain('Aa1!segredo')
    expect(sessao).not.toContain('Aa1!segredo')
  })

  it('16. 409 de gestor já existente aparece como mensagem do backend', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValue({ data: ILPI_RASCUNHO } as any)
    mockPost.mockRejectedValue({
      response: { status: 409, data: { detail: { code: 'PRIMEIRO_GESTOR_JA_EXISTE', message: 'Esta ILPI já possui administrador institucional' } } },
    })

    renderRotas('/platform/instituicoes/ilpi1')
    await cadastrarGestor(user)
    expect(await screen.findByRole('alert')).toHaveTextContent('já possui administrador institucional')
  })
})

describe('Central — ativação e inativação', () => {
  beforeEach(() => seed(TOKEN_OPERADOR, { scope: 'global' }))

  it('17. ativa a instituição', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValue({ data: ILPI_RASCUNHO } as any)
    mockPost.mockResolvedValue({ data: { ...ILPI_RASCUNHO, situacao: 'ATIVA' } } as any)

    renderRotas('/platform/instituicoes/ilpi1')
    await user.click(await screen.findByRole('button', { name: 'Ativar instituição' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/platform/instituicoes/ilpi1/ativar'))
    expect(await screen.findByRole('status')).toHaveTextContent('ativada')
  })

  it('18. pré-condição de ativação vem do backend', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValue({ data: ILPI_RASCUNHO } as any)
    mockPost.mockRejectedValue({
      response: { status: 422, data: { detail: { code: 'ONBOARDING_PENDENTE', message: 'Administrador institucional obrigatório' } } },
    })

    renderRotas('/platform/instituicoes/ilpi1')
    await user.click(await screen.findByRole('button', { name: 'Ativar instituição' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Administrador institucional obrigatório')
  })

  it('19. inativar exige confirmação e anuncia o bloqueio de acesso', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValue({ data: ILPI_ATIVA } as any)
    mockPost.mockResolvedValue({ data: { ...ILPI_ATIVA, situacao: 'INATIVA' } } as any)

    renderRotas('/platform/instituicoes/ilpi2')
    await user.click(await screen.findByRole('button', { name: 'Inativar instituição' }))

    // GATE-1 fechado: inativar bloqueia o contexto institucional na requisição
    // seguinte, então a tela passa a poder — e dever — dizer isso.
    expect(screen.getByText(/deixam de acessar o sistema/i)).toBeTruthy()
    expect(screen.getByText(/vínculos são preservados/i)).toBeTruthy()
    expect(mockPost).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Confirmar' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/platform/instituicoes/ilpi2/inativar'))
  })
})

describe('PLATFORM-2 — regeneração da credencial do primeiro gestor', () => {
  const URL_REGEN = '/platform/instituicoes/ilpi1/primeiro-gestor/credencial'

  it('20. regenerar exige confirmação e avisa que a senha anterior cai', async () => {
    const user = userEvent.setup()
    seed(TOKEN_OPERADOR, { scope: 'global' })
    mockGet.mockResolvedValue({ data: ILPI_RASCUNHO } as any)

    renderRotas('/platform/instituicoes/ilpi1')
    await user.click(await screen.findByRole('button', { name: 'Regerar credencial' }))

    expect(screen.getByText(/deixará de funcionar/i)).toBeTruthy()
    // Nada foi enviado antes do aceite explícito.
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('21. confirmada, chama o endpoint e mostra a nova senha uma única vez', async () => {
    const user = userEvent.setup()
    seed(TOKEN_OPERADOR, { scope: 'global' })
    mockGet.mockResolvedValue({ data: ILPI_RASCUNHO } as any)
    mockPost.mockResolvedValue({
      data: {
        id: 'u1',
        nome: 'Gestor',
        email: 'gestor@serena.com.br',
        ativo: true,
        is_superuser: false,
        exige_troca_senha: true,
        senha_temporaria: 'Aa1!nova-senha-regerada',
      },
    } as any)

    renderRotas('/platform/instituicoes/ilpi1')
    await user.click(await screen.findByRole('button', { name: 'Regerar credencial' }))
    await user.click(screen.getByRole('button', { name: 'Confirmar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(URL_REGEN))
    // Reutiliza o diálogo de credencial: mesmo aviso de exibição única.
    expect(await screen.findByTestId('senha-temporaria')).toHaveTextContent(
      'Aa1!nova-senha-regerada',
    )
    expect(screen.getByText(/exibida somente agora/i)).toBeTruthy()
  })

  it('22. a senha nunca é persistida no navegador', async () => {
    const user = userEvent.setup()
    seed(TOKEN_OPERADOR, { scope: 'global' })
    mockGet.mockResolvedValue({ data: ILPI_RASCUNHO } as any)
    const SENHA = 'Aa1!segredo-que-nao-pode-ficar'
    mockPost.mockResolvedValue({
      data: {
        id: 'u1',
        nome: 'Gestor',
        email: 'gestor@serena.com.br',
        ativo: true,
        is_superuser: false,
        exige_troca_senha: true,
        senha_temporaria: SENHA,
      },
    } as any)

    renderRotas('/platform/instituicoes/ilpi1')
    await user.click(await screen.findByRole('button', { name: 'Regerar credencial' }))
    await user.click(screen.getByRole('button', { name: 'Confirmar' }))
    await screen.findByTestId('senha-temporaria')

    const armazenado = JSON.stringify(localStorage) + JSON.stringify(sessionStorage)
    expect(armazenado).not.toContain(SENHA)

    // Fechado o diálogo, a tela não oferece o plaintext de volta.
    await user.click(screen.getByRole('button', { name: 'Já anotei, fechar' }))
    await waitFor(() => expect(screen.queryByTestId('senha-temporaria')).toBeNull())
    expect(document.body.textContent || '').not.toContain(SENHA)
  })

  it('23. ILPI inativa não oferece a ação, e explica por quê', async () => {
    seed(TOKEN_OPERADOR, { scope: 'global' })
    mockGet.mockResolvedValue({ data: { ...ILPI_RASCUNHO, situacao: 'INATIVA' } } as any)

    renderRotas('/platform/instituicoes/ilpi1')
    expect(await screen.findByText(/inativa e não recebe nova credencial/i)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Regerar credencial' })).toBeNull()
  })

  it('24. erro do backend é exibido sem inventar diagnóstico', async () => {
    const user = userEvent.setup()
    seed(TOKEN_OPERADOR, { scope: 'global' })
    mockGet.mockResolvedValue({ data: ILPI_RASCUNHO } as any)
    mockPost.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: { code: 'PRIMEIRO_GESTOR_INEXISTENTE', message: 'Esta ILPI ainda não possui administrador institucional' } },
      },
    })

    renderRotas('/platform/instituicoes/ilpi1')
    await user.click(await screen.findByRole('button', { name: 'Regerar credencial' }))
    await user.click(screen.getByRole('button', { name: 'Confirmar' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Esta ILPI ainda não possui administrador institucional',
    )
    expect(screen.queryByTestId('senha-temporaria')).toBeNull()
  })
})

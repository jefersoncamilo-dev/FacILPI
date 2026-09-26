import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { Documentos } from '../pages/Documentos'
import { ResidenteProntuario } from '../pages/ResidenteProntuario'
import { PermissoesProvider } from '../context/PermissoesContext'
import { api } from '../services/api'
import { contextApi } from '../services/context'

// Preserva os helpers reais (mensagemDeErro, formatDate); só o cliente HTTP é mockado.
vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }
})

// Só a leitura das permissões da sessão é substituída; o resto do módulo é real.
vi.mock('../services/context', async () => {
  const actual = await vi.importActual<typeof import('../services/context')>('../services/context')
  return { ...actual, contextApi: { ...actual.contextApi, permissoesDaSessao: vi.fn() } }
})

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)
const mockPut = vi.mocked(api.put)
const mockDelete = vi.mocked(api.delete)
const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

const RESIDENTES = [
  { id: 'res-1', nome: 'Maria Silva' },
  { id: 'res-2', nome: 'João Souza' },
]

const COM_ARQUIVO = {
  id: 'doc-1',
  residente_id: 'res-1',
  tipo: 'RG',
  numero: '12.345.678-9',
  arquivo_presente: true,
  arquivo_nome_original: 'rg-maria.pdf',
  arquivo_mime: 'application/pdf',
  arquivo_tamanho: 204800,
  validade: '2027-03-01',
  obrigatorio: true,
  situacao: 'pendente',
  responsavel_envio: 'Ana Recepção',
  created_at: '2026-09-10T12:00:00Z',
}

const SEM_ARQUIVO = {
  id: 'doc-2',
  residente_id: 'res-1',
  tipo: 'Cartão do SUS',
  arquivo_presente: false,
  situacao: 'pendente',
  created_at: '2026-09-11T12:00:00Z',
}

interface Opcoes {
  documentos?: unknown[]
  erroLista?: unknown
  residentes?: unknown[]
  erroResidentes?: unknown
  listaPendente?: boolean
  arquivo?: unknown
  erroArquivo?: unknown
}

function respondeCom(opcoes: Opcoes = {}) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/documentos/') {
      if (opcoes.listaPendente) return new Promise(() => {}) as any
      if (opcoes.erroLista) return Promise.reject(opcoes.erroLista)
      return Promise.resolve({ data: opcoes.documentos ?? [] } as any)
    }
    if (url === '/residentes/') {
      if (opcoes.erroResidentes) return Promise.reject(opcoes.erroResidentes)
      return Promise.resolve({ data: opcoes.residentes ?? RESIDENTES } as any)
    }
    if (url.endsWith('/arquivo')) {
      if (opcoes.erroArquivo) return Promise.reject(opcoes.erroArquivo)
      return Promise.resolve({ data: opcoes.arquivo ?? new Blob(['conteudo']) } as any)
    }
    throw new Error(`URL inesperada em Documentos: ${url}`)
  })
}

function renderPagina(rota = '/documentos') {
  return render(<MemoryRouter initialEntries={[rota]}><Documentos /></MemoryRouter>)
}

function chamadasDaLista() {
  return mockGet.mock.calls.filter(c => c[0] === '/documentos/')
}

const erroHttp = (status: number, detail: unknown) => ({ response: { status, data: { detail } } })

/** Erro em requisição `responseType: 'blob'`: o corpo também chega como Blob. */
const erroBlob = (status: number, detail: unknown) => ({
  response: { status, data: new Blob([JSON.stringify({ detail })], { type: 'application/json' }) },
})

function arquivoDe(nome: string, bytes: number, tipo = 'application/pdf') {
  const file = new File(['%PDF-1.4'], nome, { type: tipo })
  // Falsear o tamanho evita alocar 10 MB só para exercitar o limite.
  Object.defineProperty(file, 'size', { value: bytes })
  return file
}

let criarObjectURL: ReturnType<typeof vi.fn>
let revogarObjectURL: ReturnType<typeof vi.fn>
let cliqueAncora: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  // jsdom não implementa a API de ObjectURL nem navegação por âncora.
  criarObjectURL = vi.fn(() => 'blob:mock-url')
  revogarObjectURL = vi.fn()
  vi.stubGlobal('URL', Object.assign(globalThis.URL, {
    createObjectURL: criarObjectURL,
    revokeObjectURL: revogarObjectURL,
  }))
  cliqueAncora = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})

afterEach(() => {
  cliqueAncora.mockRestore()
  vi.unstubAllGlobals()
})

describe('Documentos — estados de tela', () => {
  it('1. LOADING aparece antes da resposta', async () => {
    respondeCom({ listaPendente: true })
    renderPagina()
    expect(await screen.findByText('Carregando documentos…')).toBeTruthy()
    expect(screen.queryByText('Nenhum documento cadastrado')).toBeNull()
  })

  it('2. EMPTY legítimo mostra estado vazio, sem alerta de erro', async () => {
    respondeCom({ documentos: [] })
    renderPagina()
    expect(await screen.findByText('Nenhum documento cadastrado')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('3. ERROR de rede exibe alerta e oferece nova tentativa', async () => {
    respondeCom({ erroLista: new Error('offline') })
    renderPagina()
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Tentar novamente' })).toBeTruthy()
    expect(screen.queryByText('Nenhum documento cadastrado')).toBeNull()
  })

  it('4. 403 na leitura nunca vira lista vazia', async () => {
    respondeCom({
      erroLista: erroHttp(403, { code: 'PERMISSION_DENIED', message: 'Permissão não autorizada' }),
    })
    renderPagina()
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText('Permissão não autorizada')).toBeTruthy()
    expect(screen.queryByText('Nenhum documento cadastrado')).toBeNull()
  })

  it('5. SUCCESS lista os metadados que o backend devolve', async () => {
    respondeCom({ documentos: [COM_ARQUIVO] })
    renderPagina()
    const cartao = await screen.findByRole('article')
    expect(within(cartao).getByText('RG')).toBeTruthy()
    // O nome também está nas <option> do filtro; a asserção é sobre o cartão.
    expect(within(cartao).getByText('Maria Silva')).toBeTruthy()
    expect(within(cartao).getByText('12.345.678-9')).toBeTruthy()
    expect(within(cartao).getByText('Ana Recepção')).toBeTruthy()
    expect(within(cartao).getByText('Documento obrigatório')).toBeTruthy()
    expect(within(cartao).getByText(/rg-maria\.pdf/)).toBeTruthy()
    expect(within(cartao).getByText(/200 KB/)).toBeTruthy()
  })

  it('6. validade é data de calendário e não regride um dia no fuso local', async () => {
    respondeCom({ documentos: [COM_ARQUIVO] })
    renderPagina()
    const cartao = await screen.findByRole('article')
    // formatDate neutraliza a conversão; formatDateTime imprimiria 28/02/2027.
    expect(within(cartao).getByText('01/03/2027')).toBeTruthy()
  })

  it('7. situação é comunicada por texto, não apenas por cor', async () => {
    respondeCom({ documentos: [COM_ARQUIVO, { ...SEM_ARQUIVO, situacao: 'validado' }] })
    renderPagina()
    const cartoes = await screen.findAllByRole('article')
    expect(within(cartoes[0]).getByText('Pendente')).toBeTruthy()
    expect(within(cartoes[1]).getByText('Validado')).toBeTruthy()
  })
})

describe('Documentos — contrato da API', () => {
  it('8. consulta GET /documentos/ e a lista de residentes', async () => {
    respondeCom({ documentos: [] })
    renderPagina()
    await screen.findByText('Nenhum documento cadastrado')
    const urls = mockGet.mock.calls.map(c => c[0])
    expect(urls).toContain('/documentos/')
    expect(urls).toContain('/residentes/')
    // Sem residente escolhido, nenhum filtro viaja.
    expect(chamadasDaLista()[0][1]).toEqual({ params: {} })
  })

  it('9. filtrar por residente envia residente_id ao backend', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [] })
    renderPagina()
    await screen.findByText('Nenhum documento cadastrado')

    await user.selectOptions(screen.getByLabelText('Residente'), 'res-1')

    await waitFor(() => expect(chamadasDaLista().length).toBeGreaterThanOrEqual(2))
    const ultima = chamadasDaLista().at(-1)
    expect(ultima?.[1]).toEqual({ params: { residente_id: 'res-1' } })
    expect(screen.getByRole('link', { name: 'Abrir prontuário' })).toBeTruthy()
  })

  it('10. o parâmetro de URL `residente` é só estado inicial; a API recebe residente_id', async () => {
    respondeCom({ documentos: [] })
    renderPagina('/documentos?residente=res-2')
    await screen.findByText('Este residente ainda não tem documento cadastrado.')

    expect(chamadasDaLista()[0][1]).toEqual({ params: { residente_id: 'res-2' } })
    // E o filtro já abre no residente do contexto, sem exigir nova seleção.
    expect((screen.getByLabelText('Residente') as HTMLSelectElement).value).toBe('res-2')
  })

  it('11. 404 não revela se o residente existe em outro tenant', async () => {
    respondeCom({
      erroLista: erroHttp(404, { code: 'RESOURCE_NOT_FOUND', message: 'Recurso não encontrado' }),
    })
    renderPagina('/documentos?residente=res-de-outra-ilpi')
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText('Recurso não encontrado')).toBeTruthy()
    expect(screen.queryByText(/outra institui/i)).toBeNull()
  })

  it('12. lista cheia avisa truncamento em vez de omitir em silêncio', async () => {
    const cem = Array.from({ length: 100 }, (_, i) => ({ ...SEM_ARQUIVO, id: `doc-${i}` }))
    respondeCom({ documentos: cem })
    renderPagina()
    expect(await screen.findByText(/Exibindo os 100 documentos mais recentes/)).toBeTruthy()
  })

  it('13. a tela nunca usa PUT nem DELETE de documento', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [COM_ARQUIVO, SEM_ARQUIVO] })
    mockPost.mockResolvedValueOnce({ data: { id: 'doc-novo' } } as any)
    renderPagina()

    await user.click(await screen.findByRole('button', { name: '+ Cadastrar documento' }))
    const dialog = screen.getByRole('dialog', { name: 'Cadastrar documento' })
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText('Tipo'), 'CPF')
    await user.click(within(dialog).getByRole('button', { name: 'Cadastrar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalled())
    expect(mockPut).not.toHaveBeenCalled()
    expect(mockDelete).not.toHaveBeenCalled()
  })
})

describe('Documentos — cadastro de metadados', () => {
  it('14. envia POST /documentos/ só com os campos preenchidos', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [] })
    mockPost.mockResolvedValueOnce({ data: { id: 'doc-novo' } } as any)
    renderPagina()

    await user.click(await screen.findByRole('button', { name: '+ Cadastrar documento' }))
    const dialog = screen.getByRole('dialog', { name: 'Cadastrar documento' })
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText('Tipo'), 'Laudo médico')
    await user.click(within(dialog).getByRole('button', { name: 'Cadastrar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect(mockPost.mock.calls[0][0]).toBe('/documentos/')
    // `numero`, `validade`, `obrigatorio` e `responsavel_envio` ficaram vazios:
    // não viajam como string vazia nem como false inventado.
    expect(mockPost.mock.calls[0][1]).toEqual({ residente_id: 'res-1', tipo: 'Laudo médico' })
  })

  it('15. os campos opcionais preenchidos viajam no formato da API', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [] })
    mockPost.mockResolvedValueOnce({ data: { id: 'doc-novo' } } as any)
    renderPagina('/documentos?residente=res-1')
    await screen.findByText('Este residente ainda não tem documento cadastrado.')

    await user.click(screen.getByRole('button', { name: '+ Cadastrar documento' }))
    const dialog = screen.getByRole('dialog', { name: 'Cadastrar documento' })
    await user.type(within(dialog).getByLabelText('Tipo'), 'RG')
    await user.type(within(dialog).getByLabelText('Número (opcional)'), '12.345')
    await user.type(within(dialog).getByLabelText('Validade (opcional)'), '2027-03-01')
    await user.type(within(dialog).getByLabelText('Responsável pelo envio (opcional)'), 'Ana')
    await user.click(within(dialog).getByLabelText('Documento obrigatório'))
    await user.click(within(dialog).getByRole('button', { name: 'Cadastrar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect(mockPost.mock.calls[0][1]).toEqual({
      residente_id: 'res-1',
      tipo: 'RG',
      numero: '12.345',
      // Date-only, exatamente como a coluna `Date` do backend espera.
      validade: '2027-03-01',
      obrigatorio: true,
      responsavel_envio: 'Ana',
    })
  })

  it('16. sem tipo não chama a API', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [] })
    renderPagina('/documentos?residente=res-1')
    await screen.findByText('Este residente ainda não tem documento cadastrado.')

    await user.click(screen.getByRole('button', { name: '+ Cadastrar documento' }))
    const dialog = screen.getByRole('dialog', { name: 'Cadastrar documento' })
    await user.click(within(dialog).getByRole('button', { name: 'Cadastrar' }))

    expect(within(dialog).getByRole('alert').textContent).toContain('Informe o tipo do documento.')
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('17. sucesso recarrega a listagem e confirma sem alert() nativo', async () => {
    const user = userEvent.setup()
    const alerta = vi.spyOn(window, 'alert').mockImplementation(() => {})
    respondeCom({ documentos: [] })
    mockPost.mockResolvedValueOnce({ data: { id: 'doc-novo' } } as any)
    renderPagina('/documentos?residente=res-1')
    await screen.findByText('Este residente ainda não tem documento cadastrado.')
    const antes = chamadasDaLista().length

    await user.click(screen.getByRole('button', { name: '+ Cadastrar documento' }))
    const dialog = screen.getByRole('dialog', { name: 'Cadastrar documento' })
    await user.type(within(dialog).getByLabelText('Tipo'), 'CPF')
    await user.click(within(dialog).getByRole('button', { name: 'Cadastrar' }))

    expect(await screen.findByText('Documento cadastrado.')).toBeTruthy()
    await waitFor(() => expect(chamadasDaLista().length).toBeGreaterThan(antes))
    expect(alerta).not.toHaveBeenCalled()
    alerta.mockRestore()
  })

  it('18. 403 na criação retira a ação e explica, mantendo a consulta', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [SEM_ARQUIVO] })
    mockPost.mockRejectedValueOnce(
      erroHttp(403, { code: 'PERMISSION_DENIED', message: 'Permissão não autorizada' }),
    )
    renderPagina('/documentos?residente=res-1')

    await user.click(await screen.findByRole('button', { name: '+ Cadastrar documento' }))
    const dialog = screen.getByRole('dialog', { name: 'Cadastrar documento' })
    await user.type(within(dialog).getByLabelText('Tipo'), 'CPF')
    await user.click(within(dialog).getByRole('button', { name: 'Cadastrar' }))

    expect(await screen.findByText(/não permite cadastrar documentos/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: '+ Cadastrar documento' })).toBeNull()
    // A listagem continua de pé.
    expect(screen.getByRole('article')).toBeTruthy()
  })
})

describe('Documentos — anexo de arquivo', () => {
  async function abrirAnexo(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByRole('button', { name: 'Anexar arquivo' }))
    return screen.getByRole('dialog', { name: 'Anexar arquivo' })
  }

  it('19. envia multipart com o campo `file` e sem herdar application/json', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [SEM_ARQUIVO] })
    mockPost.mockResolvedValueOnce({ data: { ...SEM_ARQUIVO, arquivo_presente: true } } as any)
    renderPagina()

    const dialog = await abrirAnexo(user)
    await user.upload(within(dialog).getByLabelText('Arquivo'), arquivoDe('sus.pdf', 2048))
    await user.click(within(dialog).getByRole('button', { name: 'Anexar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    const [url, corpo, config] = mockPost.mock.calls[0] as [string, FormData, any]
    expect(url).toBe('/documentos/doc-2/arquivo')
    expect(corpo).toBeInstanceOf(FormData)
    // O backend lê `File(...)` com o nome `file`; outro nome vira 422.
    expect((corpo.get('file') as File).name).toBe('sus.pdf')
    // Sem este override o transformRequest do axios serializaria o FormData
    // como JSON, porque a instância declara application/json.
    expect(config.headers['Content-Type']).toBe('multipart/form-data')
    expect(config.headers['Content-Type']).not.toContain('application/json')
  })

  it('20. arquivo acima de 10 MB é recusado na tela, sem round-trip', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [SEM_ARQUIVO] })
    renderPagina()

    const dialog = await abrirAnexo(user)
    await user.upload(within(dialog).getByLabelText('Arquivo'), arquivoDe('grande.pdf', 11 * 1024 * 1024))
    await user.click(within(dialog).getByRole('button', { name: 'Anexar' }))

    expect(within(dialog).getByRole('alert').textContent).toContain('excede o limite de 10 MB')
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('21. arquivo vazio é recusado na tela, espelhando ARQUIVO_VAZIO', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [SEM_ARQUIVO] })
    renderPagina()

    const dialog = await abrirAnexo(user)
    await user.upload(within(dialog).getByLabelText('Arquivo'), arquivoDe('vazio.pdf', 0))
    await user.click(within(dialog).getByRole('button', { name: 'Anexar' }))

    expect(within(dialog).getByRole('alert').textContent).toContain('está vazio')
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('22. 409 de arquivo já anexado é exibido sem quebrar a tela', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [SEM_ARQUIVO] })
    mockPost.mockRejectedValueOnce(
      erroHttp(409, { code: 'DOCUMENTO_ARQUIVO_JA_ANEXADO', message: 'Documento já possui arquivo anexado' }),
    )
    renderPagina()

    const dialog = await abrirAnexo(user)
    await user.upload(within(dialog).getByLabelText('Arquivo'), arquivoDe('sus.pdf', 2048))
    await user.click(within(dialog).getByRole('button', { name: 'Anexar' }))

    expect(await within(dialog).findByRole('alert')).toBeTruthy()
    expect(within(dialog).getByText('Documento já possui arquivo anexado')).toBeTruthy()
  })

  it('23. 422 de tipo não permitido chega do backend, que decide pelo conteúdo', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [SEM_ARQUIVO] })
    mockPost.mockRejectedValueOnce(
      erroHttp(422, { code: 'ARQUIVO_TIPO_NAO_PERMITIDO', message: 'Tipo de arquivo não permitido. Aceitos: PDF, JPEG, PNG.' }),
    )
    renderPagina()

    const dialog = await abrirAnexo(user)
    // Extensão .pdf com conteúdo que o backend recusa: a tela não finge validar.
    await user.upload(within(dialog).getByLabelText('Arquivo'), arquivoDe('falso.pdf', 2048))
    await user.click(within(dialog).getByRole('button', { name: 'Anexar' }))

    expect(await within(dialog).findByText(/Tipo de arquivo não permitido/)).toBeTruthy()
  })

  it('24. sucesso recarrega a listagem e confirma', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [SEM_ARQUIVO] })
    mockPost.mockResolvedValueOnce({ data: { ...SEM_ARQUIVO, arquivo_presente: true } } as any)
    renderPagina()
    const antes = chamadasDaLista().length

    const dialog = await abrirAnexo(user)
    await user.upload(within(dialog).getByLabelText('Arquivo'), arquivoDe('sus.pdf', 2048))
    await user.click(within(dialog).getByRole('button', { name: 'Anexar' }))

    expect(await screen.findByText('Arquivo anexado.')).toBeTruthy()
    await waitFor(() => expect(chamadasDaLista().length).toBeGreaterThan(antes))
  })

  it('25. 403 no anexo retira a ação e mantém consulta e download', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [SEM_ARQUIVO, COM_ARQUIVO] })
    mockPost.mockRejectedValueOnce(
      erroHttp(403, { code: 'PERMISSION_DENIED', message: 'Permissão não autorizada' }),
    )
    renderPagina()

    const dialog = await abrirAnexo(user)
    await user.upload(within(dialog).getByLabelText('Arquivo'), arquivoDe('sus.pdf', 2048))
    await user.click(within(dialog).getByRole('button', { name: 'Anexar' }))

    expect(await screen.findByText(/não permite anexar arquivos/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Anexar arquivo' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Baixar arquivo' })).toBeTruthy()
  })
})

describe('Documentos — download autenticado', () => {
  it('26. baixa como blob pelo cliente autenticado, sem token na URL', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [COM_ARQUIVO] })
    renderPagina()

    await user.click(await screen.findByRole('button', { name: 'Baixar arquivo' }))

    await waitFor(() => expect(criarObjectURL).toHaveBeenCalledTimes(1))
    const chamada = mockGet.mock.calls.find(c => c[0] === '/documentos/doc-1/arquivo')
    expect(chamada).toBeTruthy()
    expect((chamada?.[1] as any).responseType).toBe('blob')
    expect(chamada?.[0]).not.toContain('token')
  })

  it('27. o ObjectURL é revogado depois da entrega', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [COM_ARQUIVO] })
    renderPagina()

    await user.click(await screen.findByRole('button', { name: 'Baixar arquivo' }))

    await waitFor(() => expect(cliqueAncora).toHaveBeenCalledTimes(1))
    // A revogação é adiada um tique para não abortar o download recém-iniciado.
    await waitFor(() => expect(revogarObjectURL).toHaveBeenCalledWith('blob:mock-url'))
  })

  it('28. erro em corpo blob continua legível na tela', async () => {
    const user = userEvent.setup()
    respondeCom({
      documentos: [COM_ARQUIVO],
      erroArquivo: erroBlob(404, { code: 'DOCUMENTO_ARQUIVO_AUSENTE', message: 'Documento não possui arquivo anexado' }),
    })
    renderPagina()

    await user.click(await screen.findByRole('button', { name: 'Baixar arquivo' }))

    // Sem a leitura do Blob, cairia no texto padrão genérico.
    expect(await screen.findByText('Documento não possui arquivo anexado')).toBeTruthy()
    expect(revogarObjectURL).not.toHaveBeenCalled()
  })

  it('29. documento sem arquivo não oferece download', async () => {
    respondeCom({ documentos: [SEM_ARQUIVO] })
    renderPagina()
    const cartao = await screen.findByRole('article')
    expect(within(cartao).getByText('Sem arquivo anexado')).toBeTruthy()
    expect(within(cartao).queryByRole('button', { name: 'Baixar arquivo' })).toBeNull()
    expect(within(cartao).getByRole('button', { name: 'Anexar arquivo' })).toBeTruthy()
  })
})

describe('Documentos — validação', () => {
  const ID_VALIDADOR = '3f2a9c1e-7b4d-4e8a-9c21-5d6e7f8a9b0c'
  const VALIDADO = {
    ...SEM_ARQUIVO,
    id: 'doc-3',
    tipo: 'Certidão de nascimento',
    situacao: 'validado',
    validado_por: ID_VALIDADOR,
    validado_em: '2026-09-25T13:30:00Z',
  }

  /** Tela dentro do shell de permissões, com as chaves que o backend devolveria. */
  function renderComPermissoes(permissoes: string[]) {
    mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes } } as any)
    return render(
      <MemoryRouter initialEntries={['/documentos']}>
        <PermissoesProvider><Documentos /></PermissoesProvider>
      </MemoryRouter>,
    )
  }

  async function abrirValidacao(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByRole('button', { name: 'Validar documento' }))
    return screen.getByRole('dialog', { name: 'Validar documento' })
  }

  it('34. com documentos:validar, confirma e chama POST /documentos/{id}/validar', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [COM_ARQUIVO] })
    mockPost.mockResolvedValueOnce({ data: { ...COM_ARQUIVO, situacao: 'validado' } } as any)
    renderComPermissoes(['documentos:ler', 'documentos:validar'])
    const antes = chamadasDaLista().length

    const dialog = await abrirValidacao(user)
    expect(within(dialog).getByText('RG')).toBeTruthy()
    expect(within(dialog).getByText('Maria Silva')).toBeTruthy()
    await user.click(within(dialog).getByRole('button', { name: 'Validar' }))

    // Corpo vazio: autoria e horário vêm da sessão, nunca do cliente.
    expect(mockPost).toHaveBeenCalledWith('/documentos/doc-1/validar', {})
    expect(mockPost).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('Documento validado.')).toBeTruthy()
    expect(screen.queryByRole('dialog')).toBeNull()
    await waitFor(() => expect(chamadasDaLista().length).toBeGreaterThan(antes))
  })

  it('35. sem documentos:validar, a ação não aparece', async () => {
    respondeCom({ documentos: [COM_ARQUIVO, SEM_ARQUIVO] })
    renderComPermissoes(['documentos:ler', 'documentos:criar', 'documentos:atualizar'])

    expect((await screen.findAllByRole('article')).length).toBe(2)
    // Garante que a resposta das permissões já foi aplicada: antes dela a ação
    // também fica oculta, e a asserção passaria por acaso.
    await waitFor(() => expect(mockPermissoes).toHaveBeenCalled())
    await act(async () => {})

    expect(screen.queryByRole('button', { name: 'Validar documento' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Anexar arquivo' })).toBeTruthy()
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('36. 409 exibe a mensagem do backend e recarrega a lista', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [COM_ARQUIVO] })
    mockPost.mockRejectedValueOnce(
      erroHttp(409, { code: 'DOCUMENTO_JA_VALIDADO', message: 'Documento já validado' }),
    )
    renderComPermissoes(['documentos:ler', 'documentos:validar'])
    const antes = chamadasDaLista().length

    const dialog = await abrirValidacao(user)
    await user.click(within(dialog).getByRole('button', { name: 'Validar' }))

    expect(await within(dialog).findByRole('alert')).toBeTruthy()
    expect(within(dialog).getByText('Documento já validado')).toBeTruthy()
    // Repetir o envio só devolveria o mesmo 409.
    expect(within(dialog).queryByRole('button', { name: 'Validar' })).toBeNull()
    expect(within(dialog).getByRole('button', { name: 'Voltar' })).toBeTruthy()
    await waitFor(() => expect(chamadasDaLista().length).toBeGreaterThan(antes))
    expect(screen.queryByText('Documento validado.')).toBeNull()
  })

  it('37. documento já validado não oferece a ação e mostra quem validou e quando', async () => {
    respondeCom({ documentos: [VALIDADO] })
    renderComPermissoes(['documentos:ler', 'documentos:validar', 'documentos:criar'])

    const cartao = await screen.findByRole('article')
    await waitFor(() => expect(mockPermissoes).toHaveBeenCalled())
    await act(async () => {})

    expect(within(cartao).getByText('Validado')).toBeTruthy()
    expect(within(cartao).queryByRole('button', { name: 'Validar documento' })).toBeNull()
    // 25/09 13:30 UTC = 10:30 em Brasília.
    expect(within(cartao).getByText(/Validado em 25\/09\/2026,? 10:30/)).toBeTruthy()
    const autor = within(cartao).getByText('3f2a9c1e…')
    expect(autor.getAttribute('title')).toBe(ID_VALIDADOR)
    // Validado não recebe arquivo (409 no backend): a tela não oferece o anexo.
    expect(within(cartao).getByText('Sem arquivo anexado')).toBeTruthy()
    expect(within(cartao).queryByRole('button', { name: 'Anexar arquivo' })).toBeNull()
  })

  it('38. cancelar a confirmação não chama a API', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [COM_ARQUIVO] })
    renderComPermissoes(['documentos:ler', 'documentos:validar'])

    const dialog = await abrirValidacao(user)
    await user.click(within(dialog).getByRole('button', { name: 'Cancelar' }))

    expect(screen.queryByRole('dialog')).toBeNull()
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('39. sem arquivo anexado, a confirmação avisa que depois não será possível anexar', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [SEM_ARQUIVO] })
    renderComPermissoes(['documentos:ler', 'documentos:validar'])

    const dialog = await abrirValidacao(user)
    expect(within(dialog).getByText(/sem arquivo anexado\. Depois de validado, não será possível anexar/)).toBeTruthy()
  })

  it('40. 403 retira a ação e explica, mantendo a consulta', async () => {
    const user = userEvent.setup()
    respondeCom({ documentos: [COM_ARQUIVO] })
    mockPost.mockRejectedValueOnce(
      erroHttp(403, { code: 'PERMISSION_DENIED', message: 'Permissão não autorizada' }),
    )
    // Fora do shell as permissões não são conhecidas: só o backend recusa.
    renderPagina()

    const dialog = await abrirValidacao(user)
    await user.click(within(dialog).getByRole('button', { name: 'Validar' }))

    expect(await screen.findByText(/não permite validar documentos/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Validar documento' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Baixar arquivo' })).toBeTruthy()
  })
})

describe('Documentos — layout responsivo', () => {
  it('30. a listagem escala de uma para três colunas', async () => {
    respondeCom({ documentos: [COM_ARQUIVO] })
    renderPagina()
    const cartao = await screen.findByRole('article')
    const grade = cartao.parentElement?.className ?? ''
    expect(grade).toContain('md:grid-cols-2')
    expect(grade).toContain('xl:grid-cols-3')
  })

  it('31. filtro e ações empilham no celular e alinham a partir de sm', async () => {
    respondeCom({ documentos: [] })
    renderPagina()
    const filtro = (await screen.findByLabelText('Residente')).parentElement?.className ?? ''
    expect(filtro).toContain('flex-col')
    expect(filtro).toContain('sm:flex-row')
  })
})

describe('Prontuário — entrada de Documentos no contexto do residente', () => {
  const RESIDENTE = { id: 'r1', nome: 'Maria da Silva', situacao: 'Ativo', data_nascimento: '1940-05-10', sexo: 'F' }
  const PRONTUARIO_VAZIO = { items: [], next_cursor: null, has_more: false }

  function renderProntuario() {
    mockGet.mockImplementation((url: string) => {
      if (url === '/residentes/r1') return Promise.resolve({ data: RESIDENTE } as any)
      if (url === '/residentes/r1/prontuario') return Promise.resolve({ data: PRONTUARIO_VAZIO } as any)
      throw new Error(`URL inesperada no prontuário: ${url}`)
    })
    return render(
      <MemoryRouter initialEntries={['/residentes/r1']}>
        <Routes>
          <Route path="/residentes/:id" element={<ResidenteProntuario />} />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('32. o prontuário leva a Documentos já com o residente da rota', async () => {
    renderProntuario()
    const link = await screen.findByRole('link', { name: 'Documentos' })
    expect(link.getAttribute('href')).toBe('/documentos?residente=r1')
  })

  it('33. não duplica a listagem de documentos dentro do prontuário', async () => {
    renderProntuario()
    await screen.findByRole('link', { name: 'Documentos' })
    // A integração é navegação: nenhuma consulta ao acervo é disparada aqui.
    expect(mockGet.mock.calls.map(c => c[0])).not.toContain('/documentos/')
  })
})

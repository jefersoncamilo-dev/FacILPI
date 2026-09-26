import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { Intercorrencias } from '../pages/Intercorrencias'
import { ResidenteProntuario } from '../pages/ResidenteProntuario'
import { api } from '../services/api'
import * as servico from '../services/intercorrencias'

// Preserva os helpers reais (mensagemDeErro, formatDateTime); só o cliente HTTP é mockado.
vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() } }
})

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)
const mockPut = vi.mocked(api.put)
const mockPatch = vi.mocked(api.patch)
const mockDelete = vi.mocked(api.delete)

const RESIDENTES = [
  { id: 'res-1', nome: 'Maria Silva' },
  { id: 'res-2', nome: 'João Souza' },
]

const REGISTRO = {
  id: 'int-1',
  residente_id: 'res-1',
  tipo: 'Queda no banheiro',
  gravidade: 'moderada' as const,
  situacao: 'aberta' as const,
  ocorrido_em: '2026-09-16T03:00:00Z',
  data: '2026-09-16T07:20:00Z',
  responsavel: 'Enf. Ana Lima',
  sbar_situacao: 'Encontrada sentada no chão',
  providencia: 'Avaliada, sem lesão aparente',
  desfecho: null,
}

interface Opcoes {
  registros?: unknown[]
  erroLista?: unknown
  residentes?: unknown[]
  erroResidentes?: unknown
  listaPendente?: boolean
}

function respondeCom(opcoes: Opcoes = {}) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/intercorrencias/') {
      if (opcoes.listaPendente) return new Promise(() => {}) as any
      if (opcoes.erroLista) return Promise.reject(opcoes.erroLista)
      return Promise.resolve({ data: opcoes.registros ?? [] } as any)
    }
    if (url === '/residentes/') {
      if (opcoes.erroResidentes) return Promise.reject(opcoes.erroResidentes)
      return Promise.resolve({ data: opcoes.residentes ?? RESIDENTES } as any)
    }
    throw new Error(`URL inesperada em Intercorrencias: ${url}`)
  })
}

function renderPagina() {
  return render(<MemoryRouter><Intercorrencias /></MemoryRouter>)
}

const urlsChamadas = () => mockGet.mock.calls.map(c => c[0])
const chamadasDaLista = () => mockGet.mock.calls.filter(c => c[0] === '/intercorrencias/')

async function abrirModal(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: '+ Registrar intercorrência' }))
  return screen.getByRole('dialog', { name: 'Registrar intercorrência' })
}

const erroHttp = (status: number, detail: unknown) => ({ response: { status, data: { detail } } })

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('Intercorrências — estados de tela', () => {
  it('1. LOADING aparece antes da resposta', async () => {
    respondeCom({ listaPendente: true })
    renderPagina()
    expect(await screen.findByText('Carregando intercorrências…')).toBeTruthy()
    expect(screen.queryByText('Nenhuma intercorrência registrada')).toBeNull()
  })

  it('2. EMPTY legítimo mostra estado vazio, sem alerta de erro', async () => {
    respondeCom({ registros: [] })
    renderPagina()
    expect(await screen.findByText('Nenhuma intercorrência registrada')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('3. ERROR exibe alerta e oferece nova tentativa', async () => {
    respondeCom({ erroLista: new Error('offline') })
    renderPagina()
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Tentar novamente' })).toBeTruthy()
    expect(screen.queryByText('Nenhuma intercorrência registrada')).toBeNull()
  })

  it('4. 403 na leitura nunca vira lista vazia', async () => {
    respondeCom({ erroLista: erroHttp(403, { code: 'PERMISSION_DENIED', message: 'Permissão não autorizada' }) })
    renderPagina()
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText('Permissão não autorizada')).toBeTruthy()
    expect(screen.queryByText('Nenhuma intercorrência registrada')).toBeNull()
  })

  it('5. SUCCESS lista com tipo, gravidade, situação, hora do evento e autoria', async () => {
    respondeCom({ registros: [REGISTRO] })
    renderPagina()
    const cartao = await screen.findByRole('article')
    expect(within(cartao).getByText('Maria Silva')).toBeTruthy()
    expect(within(cartao).getByText('Queda no banheiro')).toBeTruthy()
    expect(within(cartao).getByText('Moderada')).toBeTruthy()
    expect(within(cartao).getByText('Aberta')).toBeTruthy()
    expect(within(cartao).getByText('Registrado por Enf. Ana Lima')).toBeTruthy()
    expect(within(cartao).getByText(/Encontrada sentada no chão/)).toBeTruthy()
    expect(within(cartao).getByText(/Avaliada, sem lesão aparente/)).toBeTruthy()
  })
})

describe('Intercorrências — contrato da API', () => {
  it('6. consulta GET /intercorrencias/ e a lista de residentes', async () => {
    respondeCom({ registros: [REGISTRO] })
    renderPagina()
    await screen.findByRole('article')
    expect(urlsChamadas()).toContain('/intercorrencias/')
    expect(urlsChamadas()).toContain('/residentes/')
  })

  it('7. filtrar por residente envia residente_id e oferece o prontuário', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [REGISTRO] })
    renderPagina()
    await screen.findByRole('article')

    await user.selectOptions(screen.getByLabelText('Residente'), 'res-2')

    await waitFor(() => {
      expect(chamadasDaLista().some(c => (c[1] as any)?.params?.residente_id === 'res-2')).toBe(true)
    })
    expect(screen.getByRole('link', { name: 'Abrir prontuário' }).getAttribute('href')).toBe('/residentes/res-2')
  })

  it('8. criação válida envia POST com apenas os campos do contrato', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    mockPost.mockResolvedValueOnce({ data: { id: 'int-novo' } } as any)
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText('Tipo'), 'Engasgo')
    await user.selectOptions(within(dialog).getByLabelText('Gravidade'), 'grave')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    const [url, payload] = mockPost.mock.calls[0] as [string, Record<string, unknown>]
    expect(url).toBe('/intercorrencias/')
    expect(payload.residente_id).toBe('res-1')
    expect(payload.tipo).toBe('Engasgo')
    expect(payload.gravidade).toBe('grave')
    // Campos do backend jamais viajam do cliente.
    for (const proibido of ['ilpi_id', 'responsavel', 'situacao', 'desfecho', 'data']) {
      expect(payload).not.toHaveProperty(proibido)
    }
    // SBAR e providência são opcionais: em branco, não são enviados.
    for (const opcional of ['sbar_situacao', 'sbar_contexto', 'sbar_avaliacao', 'sbar_recomendacao', 'providencia']) {
      expect(payload).not.toHaveProperty(opcional)
    }
  })

  it('9. SBAR e providência preenchidos viajam no payload', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    mockPost.mockResolvedValueOnce({ data: { id: 'int-novo' } } as any)
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText('Tipo'), 'Queda')
    await user.type(within(dialog).getByLabelText('Situação'), 'Encontrada no chão')
    await user.type(within(dialog).getByLabelText('Providência'), 'Sinais vitais aferidos')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    const payload = mockPost.mock.calls[0][1] as Record<string, unknown>
    expect(payload.sbar_situacao).toBe('Encontrada no chão')
    expect(payload.providencia).toBe('Sinais vitais aferidos')
    expect(payload).not.toHaveProperty('sbar_contexto')
  })

  it('10. sucesso recarrega a listagem e confirma sem alert() nativo', async () => {
    const user = userEvent.setup()
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})
    respondeCom({ registros: [] })
    mockPost.mockResolvedValueOnce({ data: { id: 'int-novo' } } as any)
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText('Tipo'), 'Queda')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    expect(await screen.findByText('Intercorrência registrada.')).toBeTruthy()
    await waitFor(() => expect(chamadasDaLista().length).toBeGreaterThanOrEqual(2))
    expect(alertSpy).not.toHaveBeenCalled()
    alertSpy.mockRestore()
  })

  it('11. a tela nunca usa PATCH, PUT ou DELETE', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [REGISTRO] })
    mockPost.mockResolvedValueOnce({ data: { id: 'int-novo' } } as any)
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText('Tipo'), 'Queda')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect(mockPatch).not.toHaveBeenCalled()
    expect(mockPut).not.toHaveBeenCalled()
    expect(mockDelete).not.toHaveBeenCalled()
    // Sem encerramento nem correção: esses fluxos não pertencem a este ciclo.
    expect(screen.queryByRole('button', { name: /encerrar|corrigir|editar|excluir/i })).toBeNull()
    expect(Object.keys(servico).some(k => /encerrar|corrigir|atualizar|excluir/i.test(k))).toBe(false)
  })
})

describe('Intercorrências — ocorrido_em', () => {
  it('12. vem preenchido com o momento atual', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    renderPagina()

    const dialog = await abrirModal(user)
    const campo = within(dialog).getByLabelText('Data e hora da ocorrência') as HTMLInputElement
    expect(campo.value).toBeTruthy()
    const diferenca = Math.abs(new Date(campo.value).getTime() - Date.now())
    expect(diferenca).toBeLessThan(120_000)
  })

  it('13. impede escolher futuro pelo atributo max e envia ISO com fuso', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    mockPost.mockResolvedValueOnce({ data: { id: 'int-novo' } } as any)
    renderPagina()

    const dialog = await abrirModal(user)
    const campo = within(dialog).getByLabelText('Data e hora da ocorrência') as HTMLInputElement
    expect(campo.getAttribute('max')).toBeTruthy()
    expect(new Date(campo.getAttribute('max') as string).getTime()).toBeLessThanOrEqual(Date.now() + 60_000)

    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText('Tipo'), 'Queda')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    const payload = mockPost.mock.calls[0][1] as { ocorrido_em?: string }
    // toISOString sempre emite UTC com Z: timezone-aware, como o backend exige.
    expect(payload.ocorrido_em).toMatch(/Z$/)
    expect(Number.isNaN(new Date(payload.ocorrido_em as string).getTime())).toBe(false)
  })

  it('14. aceita hora retroativa e a converte a partir da hora local', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    mockPost.mockResolvedValueOnce({ data: { id: 'int-novo' } } as any)
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText('Tipo'), 'Queda noturna')
    fireEvent.change(within(dialog).getByLabelText('Data e hora da ocorrência'), {
      target: { value: '2026-09-10T03:20' },
    })
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    const payload = mockPost.mock.calls[0][1] as { ocorrido_em?: string }
    expect(payload.ocorrido_em).toBe(new Date('2026-09-10T03:20').toISOString())
  })

  it('15. hora futura é recusada na tela, sem chamar a API', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText('Tipo'), 'Queda')
    const daquiUmaHora = new Date(Date.now() + 3_600_000)
    fireEvent.change(within(dialog).getByLabelText('Data e hora da ocorrência'), {
      target: { value: servico.paraInputLocal(daquiUmaHora) },
    })
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('A ocorrência não pode estar no futuro.')
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('16. não existe edição posterior de ocorrido_em na listagem', async () => {
    respondeCom({ registros: [REGISTRO] })
    renderPagina()
    const cartao = await screen.findByRole('article')
    expect(within(cartao).queryByRole('button')).toBeNull()
    expect(within(cartao).queryByRole('textbox')).toBeNull()
  })
})

describe('Intercorrências — validações espelhadas', () => {
  it('17. tipo vazio não chama a API', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Informe o tipo da intercorrência.')
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('18. residente não selecionado na tela geral bloqueia o envio', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    renderPagina()

    const dialog = await abrirModal(user)
    await user.type(within(dialog).getByLabelText('Tipo'), 'Queda')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Selecione o residente.')
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('19. gravidade oferece exatamente os valores aceitos pelo backend', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    renderPagina()

    const dialog = await abrirModal(user)
    const select = within(dialog).getByLabelText('Gravidade') as HTMLSelectElement
    expect([...select.options].map(o => o.value)).toEqual(['leve', 'moderada', 'grave'])
    // Sempre há um valor válido: o contrato exige gravidade e o campo nunca fica vazio.
    expect(select.value).toBe('leve')
  })

  it('20. tipo acima de 100 caracteres é recusado antes da API', async () => {
    respondeCom({ registros: [] })
    const { erro, payload } = servico.montarPayload('res-1', {
      ...servico.formularioVazio(),
      tipo: 'x'.repeat(101),
    })
    expect(erro).toBe('O tipo deve ter no máximo 100 caracteres.')
    expect(payload).toBeNull()
  })
})

describe('Intercorrências — respostas de erro do backend', () => {
  it('21. 404 não revela se o residente existe em outro tenant', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    mockPost.mockRejectedValueOnce(erroHttp(404, { code: 'RESOURCE_NOT_FOUND', message: 'Recurso nao encontrado' }))
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText('Tipo'), 'Queda')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    const alerta = await within(dialog).findByRole('alert')
    expect(alerta).toHaveTextContent('Recurso nao encontrado')
    expect(alerta.textContent).not.toMatch(/institui|ILPI|outro tenant/i)
  })

  it('22. 422 do backend é exibido de forma compreensível', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    mockPost.mockRejectedValueOnce(erroHttp(422, 'Ocorrido em nao pode estar no futuro'))
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText('Tipo'), 'Queda')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Ocorrido em nao pode estar no futuro')
  })

  it('23. 409 do backend é exibido sem expor detalhe interno', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    mockPost.mockRejectedValueOnce(
      erroHttp(409, { code: 'INTERCORRENCIA_CONFLITO', message: 'Registro alterado; consulte novamente' }),
    )
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText('Tipo'), 'Queda')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    const alerta = await within(dialog).findByRole('alert')
    expect(alerta).toHaveTextContent('Registro alterado; consulte novamente')
    // `code` é identificador técnico e não vai para a tela.
    expect(alerta.textContent).not.toMatch(/INTERCORRENCIA_CONFLITO/)
  })

  it('24. 403 na criação retira a ação e explica, mantendo a consulta', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [REGISTRO] })
    mockPost.mockRejectedValueOnce(erroHttp(403, { code: 'PERMISSION_DENIED', message: 'Permissão não autorizada' }))
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText('Tipo'), 'Queda')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    await within(dialog).findByRole('alert')
    await user.click(within(dialog).getByRole('button', { name: 'Fechar' }))

    expect(await screen.findByText('Seu perfil não permite registrar intercorrências. A consulta continua disponível.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '+ Registrar intercorrência' })).toBeNull()
    expect(within(screen.getByRole('article')).getByText('Maria Silva')).toBeTruthy()
  })

  it('25. falha ao listar residentes degrada para o identificador', async () => {
    respondeCom({ registros: [REGISTRO], erroResidentes: new Error('sem permissão') })
    renderPagina()
    expect(await screen.findByText('res-1')).toBeTruthy()
    expect(screen.getByText(/Não foi possível carregar a lista de residentes/)).toBeTruthy()
  })
})

describe('Intercorrências — layout responsivo', () => {
  it('26. listagem escala de uma para três colunas', async () => {
    respondeCom({ registros: [REGISTRO] })
    renderPagina()
    const cartao = await screen.findByRole('article')
    expect(cartao.parentElement?.className).toContain('md:grid-cols-2')
    expect(cartao.parentElement?.className).toContain('xl:grid-cols-3')
  })
})

describe('Prontuário — registro no contexto do residente', () => {
  const RESIDENTE = { id: 'r1', nome: 'Maria da Silva', situacao: 'Ativo', data_nascimento: '1940-05-10', sexo: 'F' }
  const PRONTUARIO_VAZIO = { items: [], next_cursor: null, has_more: false }

  function respondeProntuario() {
    mockGet.mockImplementation((url: string) => {
      if (url === '/residentes/r1') return Promise.resolve({ data: RESIDENTE } as any)
      if (url === '/residentes/r1/prontuario') return Promise.resolve({ data: PRONTUARIO_VAZIO } as any)
      throw new Error(`URL inesperada no prontuário: ${url}`)
    })
  }

  function renderProntuario() {
    return render(
      <MemoryRouter initialEntries={['/residentes/r1']}>
        <Routes>
          <Route path="/residentes/:id" element={<ResidenteProntuario />} />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('27. as duas ações convivem com hierarquia e empilham no celular', async () => {
    respondeProntuario()
    renderProntuario()

    const sinais = await screen.findByRole('button', { name: '+ Registrar sinais vitais' })
    const intercorrencia = screen.getByRole('button', { name: '+ Registrar intercorrência' })
    expect(sinais.className).toContain('btn-primary')
    // UX-11 (#101): as duas são ações frequentes e ficam preenchidas; a
    // hierarquia agora é de cor — rotina em verde, atenção em laranja.
    expect(intercorrencia.className).toContain('btn-alerta')
    expect(sinais.parentElement?.className).toContain('flex-col')
    expect(sinais.parentElement?.className).toContain('sm:flex-row')
  })

  it('28. registra com o residente da rota, sem deixar trocá-lo', async () => {
    const user = userEvent.setup()
    respondeProntuario()
    mockPost.mockResolvedValueOnce({ data: { id: 'int-novo' } } as any)
    renderProntuario()

    await user.click(await screen.findByRole('button', { name: '+ Registrar intercorrência' }))
    const dialog = screen.getByRole('dialog', { name: 'Registrar intercorrência' })

    expect(within(dialog).getByText('Maria da Silva')).toBeTruthy()
    expect(within(dialog).queryByLabelText('Residente')).toBeNull()

    await user.type(within(dialog).getByLabelText('Tipo'), 'Queda')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect(mockPost.mock.calls[0][0]).toBe('/intercorrencias/')
    expect(mockPost.mock.calls[0][1]).toMatchObject({ residente_id: 'r1', tipo: 'Queda', gravidade: 'leve' })
  })

  it('29. sucesso recarrega o prontuário para refletir a origem intercorrencia', async () => {
    const user = userEvent.setup()
    respondeProntuario()
    mockPost.mockResolvedValueOnce({ data: { id: 'int-novo' } } as any)
    renderProntuario()

    await user.click(await screen.findByRole('button', { name: '+ Registrar intercorrência' }))
    const dialog = screen.getByRole('dialog', { name: 'Registrar intercorrência' })
    await user.type(within(dialog).getByLabelText('Tipo'), 'Queda')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    expect(await screen.findByText('Intercorrência registrada.')).toBeTruthy()
    await waitFor(() =>
      expect(urlsChamadas().filter(u => u === '/residentes/r1/prontuario').length).toBeGreaterThanOrEqual(2),
    )
  })

  it('30. 403 retira apenas a ação de intercorrência, preservando sinais vitais', async () => {
    const user = userEvent.setup()
    respondeProntuario()
    mockPost.mockRejectedValueOnce(erroHttp(403, { code: 'PERMISSION_DENIED', message: 'Permissão não autorizada' }))
    renderProntuario()

    await user.click(await screen.findByRole('button', { name: '+ Registrar intercorrência' }))
    const dialog = screen.getByRole('dialog', { name: 'Registrar intercorrência' })
    await user.type(within(dialog).getByLabelText('Tipo'), 'Queda')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    await within(dialog).findByRole('alert')
    await user.click(within(dialog).getByRole('button', { name: 'Fechar' }))

    expect(await screen.findByText('Seu perfil não permite registrar intercorrências. A consulta continua disponível.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '+ Registrar intercorrência' })).toBeNull()
    // A capacidade de sinais vitais é independente e continua oferecida.
    expect(screen.getByRole('button', { name: '+ Registrar sinais vitais' })).toBeTruthy()
  })
})

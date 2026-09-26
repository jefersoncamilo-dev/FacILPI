import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { SinaisVitais } from '../pages/SinaisVitais'
import { ResidenteProntuario } from '../pages/ResidenteProntuario'
import { api } from '../services/api'
import * as servico from '../services/sinaisVitais'

// Preserva os helpers reais (mensagemDeErro, formatDateTime); só o cliente HTTP é mockado.
vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }
})

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)
const mockPut = vi.mocked(api.put)
const mockDelete = vi.mocked(api.delete)

const RESIDENTES = [
  { id: 'res-1', nome: 'Maria Silva' },
  { id: 'res-2', nome: 'João Souza' },
]

const REGISTRO = {
  id: 'sv-1',
  residente_id: 'res-1',
  temperatura: 36.8,
  pressao_sistolica: 120,
  pressao_diastolica: 80,
  saturacao: 97,
  profissional: 'Enf. Ana Lima',
  data: '2026-09-15T12:00:00Z',
  observacao: 'Aferição de rotina',
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
    if (url === '/sinais-vitais/') {
      if (opcoes.listaPendente) return new Promise(() => {}) as any
      if (opcoes.erroLista) return Promise.reject(opcoes.erroLista)
      return Promise.resolve({ data: opcoes.registros ?? [] } as any)
    }
    if (url === '/residentes/') {
      if (opcoes.erroResidentes) return Promise.reject(opcoes.erroResidentes)
      return Promise.resolve({ data: opcoes.residentes ?? RESIDENTES } as any)
    }
    throw new Error(`URL inesperada em SinaisVitais: ${url}`)
  })
}

function renderPagina() {
  return render(<MemoryRouter><SinaisVitais /></MemoryRouter>)
}

function urlsChamadas() {
  return mockGet.mock.calls.map(c => c[0])
}

function chamadasDaLista() {
  return mockGet.mock.calls.filter(c => c[0] === '/sinais-vitais/')
}

async function abrirModal(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: '+ Registrar aferição' }))
  return screen.getByRole('dialog', { name: 'Registrar sinais vitais' })
}

const erroHttp = (status: number, detail: unknown) => ({ response: { status, data: { detail } } })

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('SinaisVitais — estados de tela', () => {
  it('1. LOADING aparece antes da resposta', async () => {
    respondeCom({ listaPendente: true })
    renderPagina()
    expect(await screen.findByText('Carregando sinais vitais…')).toBeTruthy()
    expect(screen.queryByText('Nenhum sinal vital registrado')).toBeNull()
  })

  it('2. EMPTY legítimo mostra estado vazio, sem alerta de erro', async () => {
    respondeCom({ registros: [] })
    renderPagina()
    expect(await screen.findByText('Nenhum sinal vital registrado')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('3. ERROR de rede exibe alerta e oferece nova tentativa', async () => {
    respondeCom({ erroLista: new Error('offline') })
    renderPagina()
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Tentar novamente' })).toBeTruthy()
    expect(screen.queryByText('Nenhum sinal vital registrado')).toBeNull()
  })

  it('4. 403 na leitura nunca vira lista vazia', async () => {
    respondeCom({
      erroLista: erroHttp(403, { code: 'PERMISSION_DENIED', message: 'Permissão não autorizada' }),
    })
    renderPagina()
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText('Permissão não autorizada')).toBeTruthy()
    expect(screen.queryByText('Nenhum sinal vital registrado')).toBeNull()
  })

  it('5. SUCCESS lista registros com unidades e autoria do backend', async () => {
    respondeCom({ registros: [REGISTRO] })
    renderPagina()
    // O nome também está nas <option> do filtro; a asserção é sobre o cartão.
    const cartao = await screen.findByRole('article')
    expect(within(cartao).getByText('Maria Silva')).toBeTruthy()
    expect(within(cartao).getByText('36,8 °C')).toBeTruthy()
    expect(within(cartao).getByText('120 mmHg')).toBeTruthy()
    expect(within(cartao).getByText('97 %')).toBeTruthy()
    expect(within(cartao).getByText('Registrado por Enf. Ana Lima')).toBeTruthy()
    // Campos não medidos não aparecem inventados como zero.
    expect(within(cartao).queryByText(/bpm/)).toBeNull()
    expect(within(cartao).queryByText(/mg\/dL/)).toBeNull()
  })
})

describe('SinaisVitais — contrato da API', () => {
  it('6. consulta GET /sinais-vitais/ e a lista de residentes', async () => {
    respondeCom({ registros: [REGISTRO] })
    renderPagina()
    await screen.findByRole('article')
    expect(urlsChamadas()).toContain('/sinais-vitais/')
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
    const link = screen.getByRole('link', { name: 'Abrir prontuário' })
    expect(link.getAttribute('href')).toBe('/residentes/res-2')
  })

  it('8. registro válido envia POST /sinais-vitais/ só com os campos preenchidos', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    mockPost.mockResolvedValueOnce({ data: { id: 'sv-novo' } } as any)
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText(/Temperatura/), '36,8')
    await user.type(within(dialog).getByLabelText(/Saturação/), '97')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    const [url, payload] = mockPost.mock.calls[0]
    expect(url).toBe('/sinais-vitais/')
    expect(payload).toEqual({ residente_id: 'res-1', temperatura: 36.8, saturacao: 97 })
    // Tenant e autoria vêm da sessão: a tela nunca os envia.
    expect(payload).not.toHaveProperty('ilpi_id')
    expect(payload).not.toHaveProperty('profissional')
  })

  it('9. data retroativa é aceita e viaja como instante ISO', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    mockPost.mockResolvedValueOnce({ data: { id: 'sv-novo' } } as any)
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText(/Temperatura/), '37')
    fireEvent.change(within(dialog).getByLabelText('Data e hora da aferição'), {
      target: { value: '2026-09-10T08:30' },
    })
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    const payload = mockPost.mock.calls[0][1] as { data?: string }
    expect(payload.data).toBe(new Date('2026-09-10T08:30').toISOString())
  })

  it('10. sucesso recarrega a listagem e confirma sem alert() nativo', async () => {
    const user = userEvent.setup()
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})
    respondeCom({ registros: [] })
    mockPost.mockResolvedValueOnce({ data: { id: 'sv-novo' } } as any)
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText(/Peso/), '62,5')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    expect(await screen.findByText('Sinais vitais registrados.')).toBeTruthy()
    await waitFor(() => expect(chamadasDaLista().length).toBeGreaterThanOrEqual(2))
    expect(alertSpy).not.toHaveBeenCalled()
    alertSpy.mockRestore()
  })

  it('11. a tela nunca usa PUT nem DELETE de sinal vital', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [REGISTRO] })
    mockPost.mockResolvedValueOnce({ data: { id: 'sv-novo' } } as any)
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText(/Glicemia/), '95')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect(mockPut).not.toHaveBeenCalled()
    expect(mockDelete).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: /excluir|apagar|editar/i })).toBeNull()
    // O serviço não expõe superfície de alteração que o backend não tem.
    expect(Object.keys(servico).some(k => /atualizar|editar|excluir|remover/i.test(k))).toBe(false)
  })
})

describe('SinaisVitais — validações espelhadas do backend', () => {
  it('12. sem nenhum sinal preenchido não chama a API', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText('Observação'), 'só observação')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Informe pelo menos um sinal vital.')
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('13. saturação fora de 0..100 é recusada na tela', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText(/Saturação/), '120')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Saturação deve estar entre 0 e 100 %.')
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('14. valor negativo em campo com piso é recusado', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText(/Peso/), '-3')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Peso não pode ser menor que 0 kg.')
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('15. campo inteiro recusa fração, como o Pydantic', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText(/Frequência cardíaca/), '72,5')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Frequência cardíaca aceita apenas número inteiro.')
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('16. sistólica <= diastólica apenas avisa e NÃO bloqueia', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    mockPost.mockResolvedValueOnce({ data: { id: 'sv-novo' } } as any)
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText(/Pressão sistólica/), '80')
    await user.type(within(dialog).getByLabelText(/Pressão diastólica/), '120')

    expect(within(dialog).getByText(/Sistólica menor ou igual à diastólica/)).toBeTruthy()

    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect(mockPost.mock.calls[0][1]).toMatchObject({ pressao_sistolica: 80, pressao_diastolica: 120 })
  })

  it('17. temperatura não recebe piso inventado pela tela', () => {
    const definicao = servico.SINAIS_VITAIS_CAMPOS.find(c => c.campo === 'temperatura')
    expect(definicao?.min).toBeUndefined()
    expect(definicao?.max).toBeUndefined()
    const { erro, payload } = servico.montarPayload('res-1', {
      ...servico.FORMULARIO_SINAIS_VAZIO,
      valores: { ...servico.FORMULARIO_SINAIS_VAZIO.valores, temperatura: '34,2' },
    })
    expect(erro).toBeNull()
    expect(payload).toEqual({ residente_id: 'res-1', temperatura: 34.2 })
  })
})

describe('SinaisVitais — respostas de erro do backend', () => {
  it('18. 422 do backend é exibido sem quebrar a tela', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    mockPost.mockRejectedValueOnce(
      erroHttp(422, [{ loc: ['body'], msg: 'Value error, Informe pelo menos um sinal vital' }]),
    )
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText(/Temperatura/), '36,5')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Informe pelo menos um sinal vital')
  })

  it('19. 404 não revela se o residente existe em outro tenant', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    mockPost.mockRejectedValueOnce(
      erroHttp(404, { code: 'RESOURCE_NOT_FOUND', message: 'Recurso não encontrado' }),
    )
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText(/Temperatura/), '36,5')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    const alerta = await within(dialog).findByRole('alert')
    expect(alerta).toHaveTextContent('Recurso não encontrado')
    expect(alerta.textContent).not.toMatch(/institui|ILPI|outro tenant/i)
  })

  it('20. 403 na criação retira a ação e explica, mantendo a consulta', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [REGISTRO] })
    mockPost.mockRejectedValueOnce(
      erroHttp(403, { code: 'PERMISSION_DENIED', message: 'Permissão não autorizada' }),
    )
    renderPagina()

    const dialog = await abrirModal(user)
    await user.selectOptions(within(dialog).getByLabelText('Residente'), 'res-1')
    await user.type(within(dialog).getByLabelText(/Temperatura/), '36,5')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    await within(dialog).findByRole('alert')
    await user.click(within(dialog).getByRole('button', { name: 'Fechar' }))

    expect(await screen.findByText('Seu perfil não permite registrar sinais vitais. A consulta continua disponível.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '+ Registrar aferição' })).toBeNull()
    expect(within(screen.getByRole('article')).getByText('Maria Silva')).toBeTruthy()
  })

  it('21. falha ao listar residentes degrada para o identificador, sem derrubar a tela', async () => {
    respondeCom({ registros: [REGISTRO], erroResidentes: new Error('sem permissão') })
    renderPagina()
    expect(await screen.findByText('res-1')).toBeTruthy()
    expect(screen.getByText(/Não foi possível carregar a lista de residentes/)).toBeTruthy()
  })
})

describe('SinaisVitais — layout responsivo', () => {
  it('22. campos em uma coluna no celular e duas a partir de sm', async () => {
    const user = userEvent.setup()
    respondeCom({ registros: [] })
    renderPagina()

    const dialog = await abrirModal(user)
    const grade = within(dialog).getByLabelText(/Temperatura/).closest('div')?.parentElement
    expect(grade?.className).toContain('grid-cols-1')
    expect(grade?.className).toContain('sm:grid-cols-2')
  })

  it('23. a listagem escala de uma para três colunas', async () => {
    respondeCom({ registros: [REGISTRO] })
    renderPagina()
    const cartao = await screen.findByRole('article')
    expect(cartao.parentElement?.className).toContain('md:grid-cols-2')
    expect(cartao.parentElement?.className).toContain('xl:grid-cols-3')
  })
})

describe('Prontuário — entrada preferencial no contexto do residente', () => {
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

  it('24. registra com o residente da rota, sem deixar trocá-lo', async () => {
    const user = userEvent.setup()
    respondeProntuario()
    mockPost.mockResolvedValueOnce({ data: { id: 'sv-novo' } } as any)
    renderProntuario()

    await user.click(await screen.findByRole('button', { name: '+ Registrar sinais vitais' }))
    const dialog = screen.getByRole('dialog', { name: 'Registrar sinais vitais' })

    expect(within(dialog).getByText('Maria da Silva')).toBeTruthy()
    expect(within(dialog).queryByLabelText('Residente')).toBeNull()

    await user.type(within(dialog).getByLabelText(/Temperatura/), '36,9')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect(mockPost.mock.calls[0][0]).toBe('/sinais-vitais/')
    expect(mockPost.mock.calls[0][1]).toEqual({ residente_id: 'r1', temperatura: 36.9 })
  })

  it('25. sucesso recarrega o prontuário para refletir a origem sinal_vital', async () => {
    const user = userEvent.setup()
    respondeProntuario()
    mockPost.mockResolvedValueOnce({ data: { id: 'sv-novo' } } as any)
    renderProntuario()

    await user.click(await screen.findByRole('button', { name: '+ Registrar sinais vitais' }))
    const dialog = screen.getByRole('dialog', { name: 'Registrar sinais vitais' })
    await user.type(within(dialog).getByLabelText(/Temperatura/), '36,9')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    expect(await screen.findByText('Sinais vitais registrados.')).toBeTruthy()
    await waitFor(() =>
      expect(urlsChamadas().filter(u => u === '/residentes/r1/prontuario').length).toBeGreaterThanOrEqual(2),
    )
  })

  it('26. 403 na criação retira a ação também no prontuário', async () => {
    const user = userEvent.setup()
    respondeProntuario()
    mockPost.mockRejectedValueOnce(
      erroHttp(403, { code: 'PERMISSION_DENIED', message: 'Permissão não autorizada' }),
    )
    renderProntuario()

    await user.click(await screen.findByRole('button', { name: '+ Registrar sinais vitais' }))
    const dialog = screen.getByRole('dialog', { name: 'Registrar sinais vitais' })
    await user.type(within(dialog).getByLabelText(/Temperatura/), '36,9')
    await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

    await within(dialog).findByRole('alert')
    await user.click(within(dialog).getByRole('button', { name: 'Fechar' }))

    expect(await screen.findByText('Seu perfil não permite registrar sinais vitais. A consulta continua disponível.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '+ Registrar sinais vitais' })).toBeNull()
  })
})

describe('SinaisVitais — atalho do Início (UX-11 / #101)', () => {
  it('?registrar=1 abre o registro direto; fechar não reabre', async () => {
    const user = userEvent.setup()
    respondeCom()
    render(<MemoryRouter initialEntries={['/sinais?registrar=1']}><SinaisVitais /></MemoryRouter>)
    expect(await screen.findByRole('dialog', { name: 'Registrar sinais vitais' })).toBeTruthy()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    await new Promise(r => setTimeout(r, 50))
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { Residentes } from '../pages/Residentes'
import { ResidenteProntuario } from '../pages/ResidenteProntuario'
import { api } from '../services/api'
import type { ProntuarioResponse } from '../services/prontuario'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return {
    ...actual,
    api: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
  }
})

const mockGet = vi.mocked(api.get)

const RESIDENTE = { id: 'r1', nome: 'Maria da Silva', situacao: 'Ativo', data_nascimento: '1940-05-10', sexo: 'F' }

function evento(overrides: Partial<ProntuarioResponse['items'][number]> = {}) {
  return {
    origem: 'avaliacao' as const,
    categoria: 'clinico' as const,
    tipo: 'avaliacao',
    registro_id: 'ev1',
    residente_id: 'r1',
    ocorrido_em: new Date().toISOString(),
    registrado_em: new Date().toISOString(),
    autor_id: 'Enf. Ana Lima',
    resumo: 'Avaliação funcional',
    situacao: null,
    estornado: false,
    substituido: false,
    substituido_por: null,
    substituto: false,
    substitui_id: null,
    motivo_estorno: null,
    link: null,
    ...overrides,
  }
}

function renderTela(idInicial = 'r1') {
  return render(
    <MemoryRouter initialEntries={[`/residentes/${idInicial}`]}>
      <Routes>
        <Route path="/residentes" element={<Residentes />} />
        <Route path="/residentes/:id" element={<ResidenteProntuario />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ResidenteProntuario', () => {
  it('1. renderiza eventos recebidos e agrupa por data', async () => {
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({ data: { items: [evento()], next_cursor: null, has_more: false } } as any)
    renderTela()
    expect(await screen.findByText('Avaliação funcional')).toBeTruthy()
    expect(screen.getByText('Hoje')).toBeTruthy()
    expect(screen.getByText('Maria da Silva')).toBeTruthy()
  })

  it('2. estado vazio quando items=[]', async () => {
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({ data: { items: [], next_cursor: null, has_more: false } } as any)
    renderTela()
    expect(await screen.findByText('Nenhum evento encontrado')).toBeTruthy()
  })

  it('3. estado de loading aparece antes da resposta', async () => {
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    let resolver: (v: any) => void = () => {}
    mockGet.mockImplementationOnce(() => new Promise(r => { resolver = r }))
    renderTela()
    expect(await screen.findByText('Carregando prontuário…')).toBeTruthy()
    resolver({ data: { items: [], next_cursor: null, has_more: false } })
    await waitFor(() => expect(screen.queryByText('Carregando prontuário…')).toBeNull())
  })

  it('4. 403 integral (sem eventos prévios) mostra erro de tela inteira', async () => {
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockRejectedValueOnce({ response: { status: 403 } })
    renderTela()
    expect(await screen.findByText('Você não tem permissão para ver estes registros.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Tentar novamente' })).toBeTruthy()
  })

  it('5. 404 do residente mostra mensagem genérica, sem revelar cross-tenant', async () => {
    mockGet.mockRejectedValueOnce({ response: { status: 404 } })
    renderTela()
    expect(await screen.findByText('Residente não encontrado.')).toBeTruthy()
  })

  it('6. 422 de filtro é distinto de 403/404', async () => {
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockRejectedValueOnce({ response: { status: 422 } })
    renderTela()
    expect(await screen.findByText('Os filtros informados são inválidos.')).toBeTruthy()
  })

  it('7. resposta parcial (algumas origens) renderiza normalmente, sem aviso de dados omitidos', async () => {
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({ data: { items: [evento()], next_cursor: null, has_more: false } } as any)
    renderTela()
    expect(await screen.findByText('Avaliação funcional')).toBeTruthy()
    expect(screen.queryByText(/omitid/i)).toBeNull()
    expect(screen.queryByText(/faltam/i)).toBeNull()
  })

  it('8. 403 ao trocar filtro preserva eventos já carregados e mostra erro associado ao filtro', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({ data: { items: [evento()], next_cursor: null, has_more: false } } as any)
    renderTela()
    expect(await screen.findByText('Avaliação funcional')).toBeTruthy()

    mockGet.mockRejectedValueOnce({ response: { status: 403 } })
    const selects = screen.getAllByRole('combobox')
    await user.selectOptions(selects[0], 'medicacao')

    expect(await screen.findByText('Você não tem permissão para ver estes registros.')).toBeTruthy()
    // evento anterior continua visível — não foi substituído por erro de tela inteira
    expect(screen.getByText('Avaliação funcional')).toBeTruthy()
  })

  it('9. paginação: carregar mais anexa itens usando next_cursor/has_more', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({
      data: { items: [evento({ registro_id: 'ev1' })], next_cursor: 'cursor-1', has_more: true },
    } as any)
    renderTela()
    expect(await screen.findByText('Avaliação funcional')).toBeTruthy()
    const botao = screen.getByRole('button', { name: 'Carregar mais' })

    mockGet.mockResolvedValueOnce({
      data: { items: [evento({ registro_id: 'ev2', resumo: 'Segunda avaliação' })], next_cursor: null, has_more: false },
    } as any)
    await user.click(botao)
    expect(await screen.findByText('Segunda avaliação')).toBeTruthy()
    expect(screen.getByText('Avaliação funcional')).toBeTruthy()
    expect(mockGet).toHaveBeenLastCalledWith('/residentes/r1/prontuario', expect.objectContaining({ params: expect.objectContaining({ cursor: 'cursor-1' }) }))
  })

  it('10. falha ao carregar página adicional preserva os eventos já carregados', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({
      data: { items: [evento()], next_cursor: 'cursor-1', has_more: true },
    } as any)
    renderTela()
    expect(await screen.findByText('Avaliação funcional')).toBeTruthy()

    mockGet.mockRejectedValueOnce({ response: { status: 500 } })
    await user.click(screen.getByRole('button', { name: 'Carregar mais' }))

    expect(await screen.findByText('Não foi possível carregar o prontuário agora.')).toBeTruthy()
    expect(screen.getByText('Avaliação funcional')).toBeTruthy()
  })

  it('11. evento estornado mostra texto explícito, não só cor', async () => {
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({
      data: { items: [evento({ estornado: true, motivo_estorno: 'Registro duplicado' })], next_cursor: null, has_more: false },
    } as any)
    renderTela()
    expect(await screen.findByText('Estornado')).toBeTruthy()
    expect(screen.getByText('Motivo: Registro duplicado')).toBeTruthy()
  })

  it('12. evento substituído mostra texto explícito', async () => {
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({
      data: { items: [evento({ substituido: true })], next_cursor: null, has_more: false },
    } as any)
    renderTela()
    expect(await screen.findByText('Substituído')).toBeTruthy()
  })

  it('13. autor em texto livre é exibido como recebido', async () => {
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({
      data: { items: [evento({ autor_id: 'Enf. Ana Lima' })], next_cursor: null, has_more: false },
    } as any)
    renderTela()
    expect(await screen.findByText('Enf. Ana Lima')).toBeTruthy()
  })

  it('14. autor em UUID válido é exibido abreviado, com valor completo em title', async () => {
    const uuid = 'f3a9c1d2-1234-4abc-9def-0123456789ab'
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({
      data: { items: [evento({ autor_id: uuid })], next_cursor: null, has_more: false },
    } as any)
    renderTela()
    const abreviado = await screen.findByTitle(uuid)
    expect(abreviado.textContent).toBe('f3a9c1d2…')
  })

  it('15. link de evento sem tela de destino não é clicável', async () => {
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({
      data: { items: [evento({ link: '/api/avaliacoes/ev1' })], next_cursor: null, has_more: false },
    } as any)
    renderTela()
    expect(await screen.findByText('Detalhe ainda não disponível')).toBeTruthy()
    expect(screen.queryByRole('link', { name: /avaliacoes/i })).toBeNull()
  })

  it('16. navegação Residentes → Prontuário ao clicar no card', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValueOnce({ data: [RESIDENTE] } as any)
    render(
      <MemoryRouter initialEntries={['/residentes']}>
        <Routes>
          <Route path="/residentes" element={<Residentes />} />
          <Route path="/residentes/:id" element={<ResidenteProntuario />} />
        </Routes>
      </MemoryRouter>,
    )
    const card = await screen.findByText('Maria da Silva')
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({ data: { items: [], next_cursor: null, has_more: false } } as any)
    await user.click(card)
    expect(await screen.findByRole('heading', { name: 'Maria da Silva' })).toBeTruthy()
  })

  it('17. retorno Prontuário → Residentes pelo link "← Residentes"', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({ data: { items: [], next_cursor: null, has_more: false } } as any)
    render(
      <MemoryRouter initialEntries={['/residentes/r1']}>
        <Routes>
          <Route path="/residentes" element={<div>TELA-RESIDENTES</div>} />
          <Route path="/residentes/:id" element={<ResidenteProntuario />} />
        </Routes>
      </MemoryRouter>,
    )
    await screen.findByText('Nenhum evento encontrado')
    await user.click(screen.getByText('← Residentes'))
    expect(await screen.findByText('TELA-RESIDENTES')).toBeTruthy()
  })

  it('18. filtro mobile reutiliza o Modal existente (role=dialog, aria-modal)', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({ data: { items: [], next_cursor: null, has_more: false } } as any)
    renderTela()
    await screen.findByText('Nenhum evento encontrado')
    await user.click(screen.getByRole('button', { name: 'Filtrar' }))
    const dialog = screen.getByRole('dialog', { name: 'Filtrar prontuário' })
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    within(dialog).getByRole('button', { name: 'Aplicar' })
  })

  it('19. impede pedidos simultâneos de "carregar mais"', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({
      data: { items: [evento()], next_cursor: 'cursor-1', has_more: true },
    } as any)
    renderTela()
    const botao = await screen.findByRole('button', { name: 'Carregar mais' })

    let resolver: (v: any) => void = () => {}
    mockGet.mockImplementationOnce(() => new Promise(r => { resolver = r }))
    await user.click(botao)
    await user.click(screen.getByRole('button', { name: 'Carregando…' }))
    resolver({ data: { items: [], next_cursor: null, has_more: false } })
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(3))
  })

  it('20. trocar filtro reseta o cursor e substitui a lista', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({
      data: { items: [evento()], next_cursor: 'cursor-1', has_more: true },
    } as any)
    renderTela()
    await screen.findByText('Avaliação funcional')

    mockGet.mockResolvedValueOnce({
      data: { items: [evento({ registro_id: 'ev2', resumo: 'Segunda avaliação' })], next_cursor: 'cursor-2', has_more: true },
    } as any)
    await user.click(screen.getByRole('button', { name: 'Carregar mais' }))
    await screen.findByText('Segunda avaliação')

    mockGet.mockResolvedValueOnce({
      data: { items: [evento({ registro_id: 'ev3', resumo: 'Após o filtro' })], next_cursor: null, has_more: false },
    } as any)
    await user.selectOptions(screen.getAllByRole('combobox')[0], 'medicacao')
    await screen.findByText('Após o filtro')

    // params exatos: cursor volta a ausente e nada de tenant/autoria/executor é enviado
    expect(mockGet).toHaveBeenLastCalledWith('/residentes/r1/prontuario', {
      params: {
        categoria: 'medicacao',
        origem: undefined,
        desde: undefined,
        ate: undefined,
        incluir_movimentacoes: true,
        limit: 20,
        cursor: undefined,
      },
    })
    // lista substituída, não anexada
    expect(screen.queryByText('Avaliação funcional')).toBeNull()
    expect(screen.queryByText('Segunda avaliação')).toBeNull()
  })

  it('21. período vira o instante UTC do dia em São Paulo, sem deslocar o dia', async () => {
    const vazio = { data: { items: [], next_cursor: null, has_more: false } }
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce(vazio as any) // carga inicial
    mockGet.mockResolvedValueOnce(vazio as any) // troca de "De"
    mockGet.mockResolvedValueOnce(vazio as any) // troca de "Até"
    renderTela()
    await screen.findByText('Nenhum evento encontrado')

    fireEvent.change(screen.getAllByLabelText('De')[0], { target: { value: '2026-05-10' } })
    await waitFor(() =>
      expect(mockGet).toHaveBeenLastCalledWith(
        '/residentes/r1/prontuario',
        expect.objectContaining({ params: expect.objectContaining({ desde: '2026-05-10T03:00:00.000Z' }) }),
      ),
    )

    fireEvent.change(screen.getAllByLabelText('Até')[0], { target: { value: '2026-05-10' } })
    await waitFor(() =>
      expect(mockGet).toHaveBeenLastCalledWith(
        '/residentes/r1/prontuario',
        expect.objectContaining({ params: expect.objectContaining({ ate: '2026-05-11T02:59:59.999Z' }) }),
      ),
    )
  })

  it('22. resposta fora de ordem não sobrescreve o filtro mais recente', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({ data: { items: [evento()], next_cursor: null, has_more: false } } as any)
    renderTela()
    await screen.findByText('Avaliação funcional')

    // primeira troca de filtro fica pendente
    let resolverPrimeira: (v: any) => void = () => {}
    mockGet.mockImplementationOnce(() => new Promise(r => { resolverPrimeira = r }))
    await user.selectOptions(screen.getAllByRole('combobox')[0], 'clinico')

    // segunda troca responde antes
    mockGet.mockResolvedValueOnce({
      data: { items: [evento({ registro_id: 'ev-final', resumo: 'Resultado do último filtro' })], next_cursor: null, has_more: false },
    } as any)
    await user.selectOptions(screen.getAllByRole('combobox')[1], 'sinal_vital')
    await screen.findByText('Resultado do último filtro')

    // a requisição superada responde por último e deve ser descartada
    resolverPrimeira({
      data: { items: [evento({ registro_id: 'ev-obsoleto', resumo: 'Resultado obsoleto' })], next_cursor: null, has_more: false },
    })
    await new Promise(r => setTimeout(r, 0))
    expect(screen.queryByText('Resultado obsoleto')).toBeNull()
    expect(screen.getByText('Resultado do último filtro')).toBeTruthy()
  })

  it('23. cursor inválido (400) limpa a paginação e impede repetir a chamada', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({
      data: { items: [evento()], next_cursor: 'cursor-1', has_more: true },
    } as any)
    renderTela()
    await screen.findByText('Avaliação funcional')

    mockGet.mockRejectedValueOnce({ response: { status: 400 } })
    await user.click(screen.getByRole('button', { name: 'Carregar mais' }))

    expect(await screen.findByText('A navegação expirou. Reaplique os filtros para continuar.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Carregar mais' })).toBeNull()
    expect(screen.getByText('Avaliação funcional')).toBeTruthy()
  })

  it('24. falha transitória (500) na paginação mantém o botão para nova tentativa', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({
      data: { items: [evento()], next_cursor: 'cursor-1', has_more: true },
    } as any)
    renderTela()
    await screen.findByText('Avaliação funcional')

    mockGet.mockRejectedValueOnce({ response: { status: 500 } })
    await user.click(screen.getByRole('button', { name: 'Carregar mais' }))

    expect(await screen.findByText('Não foi possível carregar o prontuário agora.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Carregar mais' })).toBeTruthy()
  })

  it('25. paginação fica indisponível durante a troca de filtro e volta com o cursor novo', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({
      data: { items: [evento()], next_cursor: 'cursor-1', has_more: true },
    } as any)
    renderTela()
    await screen.findByText('Avaliação funcional')
    expect(screen.getByRole('button', { name: 'Carregar mais' })).toBeTruthy()

    // troca de filtro em voo: a lista anterior continua visível, mas a paginação dela não vale mais
    let resolver: (v: any) => void = () => {}
    mockGet.mockImplementationOnce(() => new Promise(r => { resolver = r }))
    await user.selectOptions(screen.getAllByRole('combobox')[0], 'medicacao')

    expect(screen.getByText('Avaliação funcional')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Carregar mais' })).toBeNull()

    resolver({
      data: { items: [evento({ registro_id: 'ev2', resumo: 'Resultado filtrado' })], next_cursor: 'cursor-2', has_more: true },
    })
    await screen.findByText('Resultado filtrado')

    // a paginação volta ligada ao novo conjunto, nunca ao cursor anterior
    mockGet.mockResolvedValueOnce({ data: { items: [], next_cursor: null, has_more: false } } as any)
    await user.click(screen.getByRole('button', { name: 'Carregar mais' }))
    await waitFor(() =>
      expect(mockGet).toHaveBeenLastCalledWith(
        '/residentes/r1/prontuario',
        expect.objectContaining({ params: expect.objectContaining({ cursor: 'cursor-2' }) }),
      ),
    )
  })

  it('26. nome do residente so trunca a partir de lg e tem o nome completo em title', async () => {
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({ data: { items: [], next_cursor: null, has_more: false } } as any)
    renderTela()
    const titulo = await screen.findByRole('heading', { name: 'Maria da Silva' })

    // Em telas estreitas o nome quebra em vez de cortar; o corte fica restrito a lg.
    expect(titulo.className).not.toMatch(/(^|\s)truncate(\s|$)/)
    expect(titulo.className).toContain('lg:truncate')
    // Alternativa de leitura quando o corte acontece na coluna lateral fixa.
    expect(titulo.getAttribute('title')).toBe('Maria da Silva')
  })

  it('27. link de retorno tem alvo de toque de 44px', async () => {
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({ data: { items: [], next_cursor: null, has_more: false } } as any)
    renderTela()
    await screen.findByText('Nenhum evento encontrado')

    const voltar = screen.getByText('← Residentes')
    expect(voltar.className).toContain('min-h-[44px]')
    expect(voltar.className).toContain('items-center')
  })

  it('28. inicial decorativa do cabecalho e marcada como aria-hidden', async () => {
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({ data: { items: [], next_cursor: null, has_more: false } } as any)
    const { container } = renderTela()

    // O h1 continua acessivel: o avatar e irmao dele, nao ancestral.
    expect(await screen.findByRole('heading', { name: 'Maria da Silva' })).toBeTruthy()
    const avatar = container.querySelector('[aria-hidden="true"]')
    expect(avatar?.textContent).toBe('M')
  })

  it('29. nome acessivel do card nao comeca com a inicial duplicada', async () => {
    mockGet.mockResolvedValueOnce({ data: [RESIDENTE] } as any)
    render(
      <MemoryRouter initialEntries={['/residentes']}>
        <Routes>
          <Route path="/residentes" element={<Residentes />} />
        </Routes>
      </MemoryRouter>,
    )
    // Ancorado no inicio: sem aria-hidden o nome acessivel seria "MMaria da Silva...".
    const card = await screen.findByRole('link', { name: /^Maria da Silva/ })
    expect(card.getAttribute('href')).toBe('/residentes/r1')
  })

  it('30. container do nome estica na coluna lateral para o truncate poder atuar', async () => {
    mockGet.mockResolvedValueOnce({ data: RESIDENTE } as any)
    mockGet.mockResolvedValueOnce({ data: { items: [], next_cursor: null, has_more: false } } as any)
    renderTela()
    const titulo = await screen.findByRole('heading', { name: 'Maria da Silva' })

    // Em lg o container e flex-col com items-start: sem self-stretch o filho dimensiona pelo
    // conteudo, o min-w-0 nao constrange e o h1 transborda o card em vez de truncar.
    const containerDoNome = titulo.parentElement!
    expect(containerDoNome.className).toContain('min-w-0')
    expect(containerDoNome.className).toContain('lg:self-stretch')
  })

  // Issue #34 — lista de residentes
  const RESIDENTE_LONGO = {
    id: 'r9',
    nome: 'Maria das Gracas Conceicao Albuquerque dos Santos Nascimento',
    situacao: 'ativo',
    data_nascimento: '1938-03-21',
    sexo: 'F',
    cpf: '12345678901',
    grau_dependencia: 'Grau II',
    alergias: 'Alergia a dipirona',
  }

  function renderListaResidentes() {
    return render(
      <MemoryRouter initialEntries={['/residentes']}>
        <Routes>
          <Route path="/residentes" element={<Residentes />} />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('31. card do residente tem min-w-0 para nao esticar a coluna do grid', async () => {
    mockGet.mockResolvedValueOnce({ data: [RESIDENTE_LONGO] } as any)
    renderListaResidentes()
    const link = await screen.findByRole('link', { name: /^Maria das Gracas/ })

    // O item do grid e o card, ancestral do link. Sem min-w-0 o `truncate` do nome eleva o
    // min-content da coluna e a pagina ganha rolagem lateral (jsdom nao mede isso: ver Issue).
    const card = link.parentElement!
    expect(card.className).toContain('card')
    expect(card.className).toContain('min-w-0')
  })

  it('32. nome acessivel do link traz so nome, situacao e data numerica', async () => {
    mockGet.mockResolvedValueOnce({ data: [RESIDENTE_LONGO] } as any)
    renderListaResidentes()
    const link = await screen.findByRole('link', { name: /^Maria das Gracas/ })

    // getByRole computa o nome acessivel de verdade (respeita aria-hidden), ao contrario de
    // textContent. O que DEVE entrar:
    expect(screen.getByRole('link', { name: /ativo/ })).toBe(link)
    // Data em formato numerico. Regex frouxa de proposito: formatDate desloca datas-so-data em
    // um dia por fuso, defeito pre-existente e fora do escopo desta Issue — travar o valor aqui
    // congelaria o bug no teste.
    expect(screen.getByRole('link', { name: /\d{2}\/\d{2}\/1938/ })).toBe(link)

    // O que NAO pode entrar:
    expect(screen.queryByRole('link', { name: /CPF/ })).toBeNull()
    expect(screen.queryByRole('link', { name: /Grau II/ })).toBeNull()
    expect(screen.queryByRole('link', { name: /[Aa]lergia/ })).toBeNull()
    expect(screen.queryByRole('link', { name: /• F/ })).toBeNull()
  })

  it('33. alergia fica fora do link, porem visivel e acessivel', async () => {
    mockGet.mockResolvedValueOnce({ data: [RESIDENTE_LONGO] } as any)
    renderListaResidentes()
    const link = await screen.findByRole('link', { name: /^Maria das Gracas/ })

    // Informacao clinica de seguranca: nao pode receber aria-hidden nem sumir do leitor de tela.
    const alergia = screen.getByText('Alergia a dipirona')
    expect(alergia.closest('a')).toBeNull()
    expect(alergia.closest('[aria-hidden="true"]')).toBeNull()
    expect(link.contains(alergia)).toBe(false)
  })

  it('34. sexo e icone de alerta ficam marcados como decorativos', async () => {
    mockGet.mockResolvedValueOnce({ data: [RESIDENTE_LONGO] } as any)
    renderListaResidentes()
    await screen.findByRole('link', { name: /^Maria das Gracas/ })

    const decorativos = [...document.querySelectorAll('[aria-hidden="true"]')].map(e => e.textContent?.trim())
    expect(decorativos).toContain('M')        // avatar
    expect(decorativos).toContain('• F')      // sexo
    expect(decorativos).toContain('⚠️')        // icone de alerta
  })

  // Os tres testes abaixo travam a area clicavel do card. jsdom nao faz layout, entao nenhum
  // deles mede pixels: o que travam e a estrutura que produz a area (overlay absoluto ancorado
  // no card). A medicao real foi feita no navegador e esta registrada na Issue #34.

  it('35. o link cobre o card inteiro por overlay, nao so a faixa de identificacao', async () => {
    mockGet.mockResolvedValueOnce({ data: [RESIDENTE_LONGO] } as any)
    renderListaResidentes()
    const link = await screen.findByRole('link', { name: /^Maria das Gracas/ })
    const card = link.parentElement!

    // O overlay so cobre o card se o card for o bloco de contencao do absolute.
    expect(card.className).toContain('relative')
    expect(link.className).toContain('after:absolute')
    expect(link.className).toContain('after:inset-0')
    // ...e se nada entre o link e o card criar um bloco de contencao intermediario.
    expect(link.parentElement).toBe(card)

    // O conteudo que saiu do link continua dentro do card e, portanto, sob o overlay:
    // clicar na alergia ou no badge de grau navega, como acontecia antes da Issue #34.
    expect(card.contains(screen.getByText('Alergia a dipirona'))).toBe(true)
    expect(card.contains(screen.getByText('Grau II'))).toBe(true)
  })

  it('36. a sombra de hover do card so existe onde o card inteiro navega', async () => {
    mockGet.mockResolvedValueOnce({ data: [RESIDENTE_LONGO] } as any)
    renderListaResidentes()
    const link = await screen.findByRole('link', { name: /^Maria das Gracas/ })
    const card = link.parentElement!

    // hover:shadow-cardHover em area nao clicavel e falsa affordance: sinaliza clique onde
    // nada acontece. Se a sombra existir, a cobertura tem de existir junto.
    if (card.className.includes('hover:shadow-cardHover')) {
      expect(card.className).toContain('relative')
      expect(link.className).toContain('after:inset-0')
    }
  })

  it('37. o anel de foco e desenhado no overlay, cobrindo a area clicavel real', async () => {
    mockGet.mockResolvedValueOnce({ data: [RESIDENTE_LONGO] } as any)
    renderListaResidentes()
    const link = await screen.findByRole('link', { name: /^Maria das Gracas/ })

    // O anel continua disparado pelo elemento interativo (o proprio <a>), mas pintado no
    // pseudo-elemento: um anel so na faixa visivel indicaria uma area menor que a clicavel.
    expect(link.className).toContain('focus-visible:after:ring-2')
    expect(link.className).not.toMatch(/(^|\s)focus-visible:ring-2/)
  })
})

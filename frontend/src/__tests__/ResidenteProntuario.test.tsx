import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
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
})

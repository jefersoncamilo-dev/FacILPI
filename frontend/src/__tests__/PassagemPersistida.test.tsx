import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PassagensAReceber, PassarPlantao } from '../components/plantao/PassagemPersistida'
import { api } from '../services/api'
import type { ItemPassagem, Passagem, Previa } from '../services/passagem'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
})

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)

function item(parcial: Partial<ItemPassagem>): ItemPassagem {
  return {
    id: 'i1', origem: 'alerta', alerta_id: null, regra: null, referencia_id: 'x', residente_id: 'r1', residente_nome: 'Hilda Sintetica',
    gravidade: null, natureza: null, titulo: 'Intercorrência grave aberta: Queda', previsto_em: null, categoria: null, texto: null,
    situacao_atual: 'aberto', ...parcial,
  }
}

function passagem(parcial: Partial<Passagem>): Passagem {
  return {
    id: 'p1', area_id: 'a1', area_nome: 'Ala B', plantao_id: 'pl1', janela_inicio: '2026-09-28T10:00:00Z', janela_fim: '2026-09-28T22:00:00Z',
    situacao: 'entregue', entregue_por_nome: 'Ana Sintetica', entregue_por_mim: false, entregue_em: '2026-09-28T22:00:00Z',
    recebida_por_nome: null, recebida_em: null, da_minha_area: true, itens_sem_acesso: 0,
    itens: [
      item({ id: 'i1' }),
      item({ id: 'i2', origem: 'atividade', titulo: 'Cuidado sem registro: Banho', situacao_atual: 'resolvido' }),
      item({ id: 'i4', natureza: 'pendencia', titulo: 'Sem PAIS vigente' }),
      item({ id: 'i3', origem: 'observacao', categoria: 'comportamento', texto: 'Agitada no fim da tarde', titulo: 'Agitada no fim da tarde', situacao_atual: null }),
    ],
    ...parcial,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('Passagens a receber (#125)', () => {
  it('mostra a situação atual de cada item e confirma o recebimento', async () => {
    let lista = [passagem({})]
    mockGet.mockImplementation(async () => ({ data: lista }) as any)
    mockPost.mockImplementation(async () => { lista = []; return { data: { ...passagem({}), situacao: 'recebida' } } as any })
    render(<PassagensAReceber podeReceber />)
    const cartao = await screen.findByRole('article', { name: 'Passagem de Ana Sintetica' })
    expect(within(cartao).getByText('Ala B · entregue por Ana Sintetica')).toBeTruthy()
    expect(within(cartao).getByText('sua área')).toBeTruthy()
    expect(within(cartao).getAllByText('Ainda aberto')).toHaveLength(2)
    expect(within(cartao).getByText('Resolvido desde então')).toBeTruthy()
    expect(within(cartao).getByText('Agitada no fim da tarde')).toBeTruthy()
    // Item da central com natureza pendência não é rotulado como "Alerta".
    expect(within(cartao).getByText('Sem PAIS vigente').nextElementSibling?.textContent).toBe('Pendência · Hilda Sintetica')
    await userEvent.click(within(cartao).getByRole('button', { name: /Confirmar recebimento/ }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/passagens/p1/receber', {}))
    expect(await screen.findByText(/Recebimento confirmado/)).toBeTruthy()
    expect(await screen.findByText('Nenhuma passagem aguardando recebimento.')).toBeTruthy()
  })

  it('quem entregou não confirma; itens sem acesso aparecem só como contagem', async () => {
    mockGet.mockResolvedValue({ data: [passagem({ entregue_por_mim: true, itens_sem_acesso: 2 })] } as any)
    render(<PassagensAReceber podeReceber />)
    const cartao = await screen.findByRole('article', { name: 'Passagem de Ana Sintetica' })
    expect(within(cartao).queryByRole('button', { name: /Confirmar recebimento/ })).toBeNull()
    expect(within(cartao).getByText(/Mais 2 itens de módulos que seu perfil não consulta/)).toBeTruthy()
  })
})

describe('Passar plantão (#125)', () => {
  it('mostra o resumo do servidor, aceita observação curta e entrega encerrando o plantão', async () => {
    const previa: Previa = { area_id: 'a1', area_nome: 'Ala B', janela_inicio: '2026-09-28T10:00:00Z', janela_fim: '2026-09-28T22:00:00Z', itens: [item({})] }
    mockGet.mockImplementation(async (url: string) => {
      if (url === '/passagens/previa') return { data: previa } as any
      if (url === '/plantoes/atual') return { data: { pode_registrar: true, funcionario_id: 'f1', plantao: { id: 'pl1' } } } as any
      return { data: [] } as any
    })
    mockPost.mockResolvedValue({ data: passagem({ entregue_por_mim: true }) } as any)
    render(<PassarPlantao />)
    await userEvent.click(screen.getByRole('button', { name: /Preparar passagem/ }))
    const resumo = await screen.findByRole('list', { name: 'Resumo automático' })
    expect(within(resumo).getByText('Intercorrência grave aberta: Queda')).toBeTruthy()

    const form = screen.getByRole('form', { name: 'Nova observação' })
    await userEvent.selectOptions(within(form).getByRole('combobox', { name: 'Categoria' }), 'comportamento')
    await userEvent.selectOptions(within(form).getByRole('combobox', { name: 'Residente (opcional)' }), 'r1')
    const texto = within(form).getByRole('textbox', { name: 'Observação' }) as HTMLTextAreaElement
    expect(texto.maxLength).toBe(280)
    await userEvent.type(texto, 'Agitada no fim da tarde')
    await userEvent.click(within(form).getByRole('button', { name: /Adicionar observação/ }))
    expect(within(screen.getByRole('list', { name: 'Observações' })).getByText('Comportamento: Agitada no fim da tarde')).toBeTruthy()

    expect((screen.getByRole('checkbox', { name: 'Encerrar meu plantão ao entregar' }) as HTMLInputElement).checked).toBe(true)
    await userEvent.click(screen.getByRole('button', { name: /Entregar passagem/ }))
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/passagens/', {
      area_id: 'a1', encerrar_plantao: true,
      observacoes: [{ categoria: 'comportamento', residente_id: 'r1', texto: 'Agitada no fim da tarde' }],
    }))
    expect(await screen.findByText(/Passagem entregue/)).toBeTruthy()
  })
})

import { rotuloDoItem, type PlantaoItem, type PlantaoOrigem } from '../../services/plantao'

/**
 * UX-01A.2 — formas de ler a MESMA fila do plantão. Tudo aqui é apresentação:
 * nenhum item é criado, escondido por regra clínica ou reordenado dentro do
 * grupo (vale a ordem da projeção oficial).
 */
export type Visao = 'horario' | 'cuidado' | 'residente'
export type Situacao = 'todos' | 'pendentes' | 'atrasados'

// `curto` é o texto visível em telas estreitas; o nome acessível é sempre o `rotulo`.
export const VISOES: { valor: Visao; rotulo: string; curto: string }[] = [
  { valor: 'horario', rotulo: 'Por horário', curto: 'Horário' },
  { valor: 'cuidado', rotulo: 'Por cuidado', curto: 'Cuidado' },
  { valor: 'residente', rotulo: 'Por residente', curto: 'Residente' },
]

export const SITUACOES: { valor: Situacao; rotulo: string }[] = [
  { valor: 'todos', rotulo: 'Todos' },
  { valor: 'pendentes', rotulo: 'Pendentes' },
  { valor: 'atrasados', rotulo: 'Atrasados' },
]

export interface Filtros {
  situacao: Situacao
  origem: PlantaoOrigem | 'todas'
  residenteId: string | null
}

export const FILTROS_PADRAO: Filtros = { situacao: 'todos', origem: 'todas', residenteId: null }

export interface Grupo {
  chave: string
  titulo: string
  itens: PlantaoItem[]
}

/** UX-01C: "Marcar" em grupo só pega o que já venceu ou vence em até 1 h. */
export const JANELA_MARCAR_EM_LOTE_MS = 60 * 60 * 1000

/**
 * A fila mostra 24 h à frente; marcar em grupo cuidados de amanhã e registrá-los
 * como "Realizado" agora seria um registro falso. Esses continuam marcáveis um a
 * um, de propósito (decisão de quem marca), mas nunca entram pelo atalho do grupo.
 */
export function marcavelEmGrupo(item: PlantaoItem, agora: number): boolean {
  return Boolean(item.previsto_em) && new Date(item.previsto_em!).getTime() <= agora + JANELA_MARCAR_EM_LOTE_MS
}

export function estaAtrasado(item: PlantaoItem, agora: number): boolean {
  return Boolean(item.previsto_em) && new Date(item.previsto_em!).getTime() < agora
}

/** "Pendentes" = ainda no prazo (inclui intercorrência aberta, que não tem horário). */
export function atendeSituacao(item: PlantaoItem, situacao: Situacao, agora: number): boolean {
  if (situacao === 'todos') return true
  return situacao === 'atrasados' ? estaAtrasado(item, agora) : !estaAtrasado(item, agora)
}

export function filtrar(itens: PlantaoItem[], filtros: Filtros, agora: number): PlantaoItem[] {
  return itens.filter(item =>
    atendeSituacao(item, filtros.situacao, agora)
    && (filtros.origem === 'todas' || item.origem === filtros.origem)
    && (!filtros.residenteId || item.residente_id === filtros.residenteId))
}

// Sem tipo de cuidado estruturado (CUID-01), "mesmo cuidado" = mesma descrição
// ignorando caixa, acentos e espaços. Agrupa só textos idênticos nesse sentido.
export function chaveDoCuidado(item: PlantaoItem): string {
  if (item.origem !== 'cuidado') return item.origem
  const texto = (item.descricao || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, ' ').trim()
  return `cuidado:${texto}`
}

function primeiroHorario(itens: PlantaoItem[]): number {
  const tempos = itens.filter(i => i.previsto_em).map(i => new Date(i.previsto_em!).getTime())
  return tempos.length ? Math.min(...tempos) : Number.POSITIVE_INFINITY
}

function agruparPor(itens: PlantaoItem[], chave: (i: PlantaoItem) => string, titulo: (i: PlantaoItem) => string): Grupo[] {
  const grupos = new Map<string, Grupo>()
  for (const item of itens) {
    const k = chave(item)
    const grupo = grupos.get(k) ?? { chave: k, titulo: titulo(item), itens: [] }
    grupo.itens.push(item)
    grupos.set(k, grupo)
  }
  return [...grupos.values()]
}

export function agrupar(itens: PlantaoItem[], visao: Visao, nomes: Record<string, string>, agora: number): Grupo[] {
  if (visao === 'horario') {
    return [
      { chave: 'atrasadas', titulo: 'Atrasadas', itens: itens.filter(i => estaAtrasado(i, agora)) },
      { chave: 'proximas', titulo: 'Próximas', itens: itens.filter(i => i.previsto_em && !estaAtrasado(i, agora)) },
      { chave: 'sem-horario', titulo: 'Intercorrências abertas', itens: itens.filter(i => !i.previsto_em) },
    ].filter(g => g.itens.length > 0)
  }
  if (visao === 'cuidado') {
    const titulo = (i: PlantaoItem) =>
      i.origem === 'cuidado' ? rotuloDoItem(i) : i.origem === 'medicacao' ? 'Medicação' : 'Intercorrências abertas'
    return agruparPor(itens, chaveDoCuidado, titulo)
      .sort((a, b) => primeiroHorario(a.itens) - primeiroHorario(b.itens) || a.titulo.localeCompare(b.titulo, 'pt-BR'))
  }
  // Por residente: quem tem algo atrasado primeiro, depois o horário mais cedo, depois o nome.
  return agruparPor(itens, i => i.residente_id, i => nomes[i.residente_id] || i.residente_id)
    .sort((a, b) =>
      Number(b.itens.some(i => estaAtrasado(i, agora))) - Number(a.itens.some(i => estaAtrasado(i, agora)))
      || primeiroHorario(a.itens) - primeiroHorario(b.itens)
      || a.titulo.localeCompare(b.titulo, 'pt-BR'))
}

/** "35 min", "2h05", "3h" — curto para o selo "Atrasado …" caber numa linha em 360px. */
export function tempoDeAtraso(previstoEm: string, agora: number): string {
  const minutos = Math.max(1, Math.floor((agora - new Date(previstoEm).getTime()) / 60000))
  if (minutos < 60) return `${minutos} min`
  const horas = Math.floor(minutos / 60)
  const resto = minutos % 60
  return resto ? `${horas}h${String(resto).padStart(2, '0')}` : `${horas}h`
}

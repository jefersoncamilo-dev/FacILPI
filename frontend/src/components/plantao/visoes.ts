import { rotuloDoItem, type PlantaoItem, type PlantaoOrigem } from '../../services/plantao'
import { compararPorGrau, grauDaApi } from '../../lib/grau'

/**
 * UX-01A.2 — formas de ler a MESMA fila do plantão. Tudo aqui é apresentação:
 * nenhum item é criado ou escondido por regra clínica.
 *
 * UX-GRAU G3a — a ordem do trabalho é urgência, depois grau de dependência
 * (sem grau, III, II, I), depois horário. Empate mantém a ordem da projeção.
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

function horario(item: PlantaoItem): number {
  return item.previsto_em ? new Date(item.previsto_em).getTime() : Number.POSITIVE_INFINITY
}

function comparar(a: number, b: number): number {
  return a < b ? -1 : a > b ? 1 : 0
}

/** Urgência (atrasado primeiro), depois grau (sem grau, III, II, I), depois horário. */
export function compararTarefas(a: PlantaoItem, b: PlantaoItem, agora: number): number {
  return Number(estaAtrasado(b, agora)) - Number(estaAtrasado(a, agora))
    || compararPorGrau(grauDaApi(a.grau), grauDaApi(b.grau))
    || comparar(horario(a), horario(b))
}

function ordenar(itens: PlantaoItem[], agora: number): PlantaoItem[] {
  return [...itens].sort((a, b) => compararTarefas(a, b, agora))
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
    // Faixas de urgência: o que venceu, o que vence em até 1 h, intercorrência
    // aberta (sem horário) e o resto. Dentro de cada faixa: grau, depois horário.
    const agoraOuJa = (i: PlantaoItem) => !estaAtrasado(i, agora) && marcavelEmGrupo(i, agora)
    return [
      { chave: 'atrasadas', titulo: 'Atrasadas', itens: itens.filter(i => estaAtrasado(i, agora)) },
      { chave: 'agora', titulo: 'Agora (próxima 1 h)', itens: itens.filter(agoraOuJa) },
      { chave: 'sem-horario', titulo: 'Intercorrências abertas', itens: itens.filter(i => !i.previsto_em) },
      { chave: 'proximas', titulo: 'Próximas', itens: itens.filter(i => i.previsto_em && !estaAtrasado(i, agora) && !agoraOuJa(i)) },
    ].filter(g => g.itens.length > 0).map(g => ({ ...g, itens: ordenar(g.itens, agora) }))
  }
  if (visao === 'cuidado') {
    const titulo = (i: PlantaoItem) =>
      i.origem === 'cuidado' ? rotuloDoItem(i) : i.origem === 'medicacao' ? 'Medicação' : 'Intercorrências abertas'
    return agruparPor(itens, chaveDoCuidado, titulo)
      .map(g => ({ ...g, itens: ordenar(g.itens, agora) }))
      .sort((a, b) => primeiroHorario(a.itens) - primeiroHorario(b.itens) || a.titulo.localeCompare(b.titulo, 'pt-BR'))
  }
  // Por residente: quem tem algo atrasado primeiro, depois o grau, depois o
  // horário mais cedo, depois o nome. Dentro do residente, a ordem é a mesma.
  return agruparPor(itens, i => i.residente_id, i => nomes[i.residente_id] || i.residente_id)
    .map(g => ({ ...g, itens: ordenar(g.itens, agora) }))
    .sort((a, b) =>
      Number(b.itens.some(i => estaAtrasado(i, agora))) - Number(a.itens.some(i => estaAtrasado(i, agora)))
      || compararPorGrau(grauDaApi(a.itens[0].grau), grauDaApi(b.itens[0].grau))
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

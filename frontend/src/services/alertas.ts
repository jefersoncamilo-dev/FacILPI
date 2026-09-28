import { api } from './api'

/**
 * Central de alertas e pendências (#107, #117) — espelha AlertaGestorResponse
 * (backend/src/application/schemas.py) e GET /central-alertas/
 * (backend/src/application/alertas.py).
 *
 * Alerta é PROJEÇÃO: calculado a cada consulta a partir da fonte oficial e
 * some quando o problema é resolvido lá. Nada é marcado, gravado ou
 * dispensado por aqui — "resolver" é sempre ir à tela de origem.
 */
export type Gravidade = 'critico' | 'atencao' | 'aviso'
export type Categoria = 'admissao_documentos' | 'avaliacao_grau_pais' | 'plantao' | 'ocupacao_equipe'
/** Independente da gravidade: alerta pede ação no plantão; pendência é algo a regularizar. */
export type Natureza = 'alerta' | 'pendencia' | 'informativo' | 'atividade'

export interface Alerta {
  /** Estável: regra:referência[:contexto] — a ordem e a chave de tela não mudam ao recalcular. */
  id: string
  regra: string
  categoria: Categoria
  gravidade: Gravidade
  natureza: Natureza
  titulo: string
  detalhe: string | null
  residente_id: string | null
  residente_nome: string | null
  referencia_id: string | null
  /** Localização operacional mínima do residente (não exige acesso a Quartos e Leitos). */
  unidade: string | null
  quarto: string | null
  leito: string | null
  local: string | null
  /** Quando nasceu a situação de origem. */
  desde: string | null
  /** Quando vence/venceu — só quando o domínio tem vencimento real. */
  prazo: string | null
}

export type ContagemAlertas = Record<Gravidade | Natureza | 'total', number>

export interface CentralAlertas {
  gerado_em: string
  contagem: ContagemAlertas
  /** Já na ordem do backend (gravidade, alerta antes de pendência, mais atrasado primeiro). */
  alertas: Alerta[]
}

export async function listarAlertas(): Promise<CentralAlertas> {
  const { data } = await api.get<CentralAlertas>('/central-alertas/')
  return data
}

export const GRAVIDADES: Gravidade[] = ['critico', 'atencao', 'aviso']

export const ROTULO_NATUREZA: Record<Natureza, string> = {
  alerta: 'Alerta',
  pendencia: 'Pendência',
  informativo: 'Informativo',
  atividade: 'Atividade',
}

export const ROTULO_GRAVIDADE: Record<Gravidade, string> = {
  critico: 'Crítico',
  atencao: 'Atenção',
  aviso: 'Aviso',
}

export const CATEGORIAS: Categoria[] = ['admissao_documentos', 'avaliacao_grau_pais', 'plantao', 'ocupacao_equipe']

export const ROTULO_CATEGORIA: Record<Categoria, string> = {
  admissao_documentos: 'Admissão e documentos',
  avaliacao_grau_pais: 'Avaliação, grau e PAIS',
  plantao: 'Plantão',
  ocupacao_equipe: 'Ocupação e equipe',
}

export interface Destino {
  to: string
  /** Módulo de origem, para "em Meu Plantão". */
  rotulo: string
  /** O que fazer, dito como ação. */
  acao: string
}

/** Onde e como cada alerta é resolvido — o único mapa de destinos (sino, Central, Início, Meu Plantão). */
export function destinoDoAlerta(a: Alerta): Destino {
  switch (a.regra) {
    case 'admissao_parada':
      return { to: `/admissoes/${a.referencia_id}`, rotulo: 'Admissões', acao: 'Continuar admissão' }
    case 'documento_aguardando_validacao':
      return { to: '/documentos', rotulo: 'Documentos', acao: 'Validar documento' }
    case 'documento_vencido':
    case 'documento_vencendo':
      return { to: '/documentos', rotulo: 'Documentos', acao: 'Atualizar documento' }
    case 'avaliacao_vencida':
      return { to: '/avaliacoes', rotulo: 'Avaliações', acao: 'Realizar avaliação' }
    case 'grau_ausente':
    case 'grau_vencido':
      return { to: '/avaliacoes', rotulo: 'Avaliações', acao: 'Definir grau de dependência' }
    case 'pais_parado':
    case 'pais_vencido':
      return { to: `/plano/${a.referencia_id}`, rotulo: 'Plano de Cuidados', acao: 'Abrir PAIS' }
    case 'pais_ausente':
      return { to: '/plano', rotulo: 'Plano de Cuidados', acao: 'Elaborar PAIS' }
    case 'cuidados_sem_registro':
      return { to: '/plantao', rotulo: 'Meu Plantão', acao: 'Registrar cuidados' }
    case 'doses_sem_registro':
      return { to: '/plantao', rotulo: 'Meu Plantão', acao: 'Registrar doses' }
    case 'intercorrencia_grave_aberta':
    case 'intercorrencia_aberta_prolongada':
      return { to: '/intercorrencias', rotulo: 'Intercorrências', acao: 'Ver intercorrência' }
    case 'residente_sem_leito':
      return { to: '/quartos', rotulo: 'Quartos e Leitos', acao: 'Alocar leito' }
    case 'ausencia_prolongada':
      return { to: '/quartos', rotulo: 'Quartos e Leitos', acao: 'Ver ausência' }
    case 'acesso_nao_utilizado':
      return { to: '/equipe', rotulo: 'Equipe', acao: 'Ver equipe' }
    default:
      return a.residente_id
        ? { to: `/residentes/${a.residente_id}`, rotulo: 'Prontuário', acao: 'Abrir prontuário' }
        : { to: '/', rotulo: 'Início', acao: 'Abrir' }
  }
}

const FUSO = 'America/Sao_Paulo'
const DIA_CIVIL = new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: FUSO })

/** Dias de calendário (no fuso da ILPI) entre dois instantes. */
function diasCivis(de: Date, ate: Date): number {
  const dia = (d: Date) => Date.parse(`${DIA_CIVIL.format(d)}T00:00:00Z`)
  return Math.round((dia(ate) - dia(de)) / 86_400_000)
}

/** "3 min", "2 h", "1 dia" — duração curta para cartões. */
export function duracaoCurta(ms: number): string {
  const minutos = Math.max(0, Math.floor(ms / 60_000))
  if (minutos < 1) return 'menos de 1 min'
  if (minutos < 60) return `${minutos} min`
  const horas = Math.floor(minutos / 60)
  if (horas < 24) return `${horas} h`
  const dias = Math.floor(horas / 24)
  return `${dias} ${dias === 1 ? 'dia' : 'dias'}`
}

/**
 * "Quando?" do cartão, derivado do contrato de tempo (#117): prazo futuro →
 * "vence hoje / amanhã / em N dias"; prazo passado → "atrasado há …" (alerta)
 * ou "venceu há …" (pendência); só origem → "há …". `agora` é do cliente.
 */
export function quandoDoAlerta(a: Pick<Alerta, 'desde' | 'prazo' | 'natureza'>, agora: Date = new Date()): string | null {
  const prazo = a.prazo ? new Date(a.prazo) : null
  const desde = a.desde ? new Date(a.desde) : null
  if (prazo && !Number.isNaN(prazo.getTime())) {
    if (prazo > agora) {
      // O último instante válido é o dia do vencimento (prazo = 00:00 do dia seguinte).
      const dias = diasCivis(agora, new Date(prazo.getTime() - 1))
      if (dias <= 0) return 'vence hoje'
      if (dias === 1) return 'vence amanhã'
      return `vence em ${dias} dias`
    }
    const atraso = duracaoCurta(agora.getTime() - prazo.getTime())
    return a.natureza === 'alerta' ? `atrasado há ${atraso}` : `venceu há ${atraso}`
  }
  if (desde && !Number.isNaN(desde.getTime())) return `há ${duracaoCurta(agora.getTime() - desde.getTime())}`
  return null
}

/** Limiares da v1 (constantes de backend/src/application/alertas.py), em linguagem simples. */
export const LIMIARES = [
  'Admissão sem avanço há mais de 7 dias.',
  'Documento vencido ou que vence em até 30 dias; documento obrigatório ainda não validado.',
  'PAIS sem mudança há mais de 7 dias enquanto não entra em vigência.',
  'Cuidados e doses com horário já passado nas últimas 24 horas e sem registro.',
  'Intercorrência grave aberta, ou qualquer intercorrência aberta há mais de 24 horas.',
  'Hospitalização ou saída sem retorno há mais de 7 dias; acesso criado e não usado há mais de 7 dias.',
]

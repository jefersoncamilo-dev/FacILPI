import { api } from './api'

/**
 * Central de alertas do gestor (#107) — espelha AlertaGestorResponse
 * (backend/src/application/schemas.py) e GET /central-alertas/
 * (backend/src/application/alertas.py).
 *
 * Alerta é PROJEÇÃO: calculado a cada consulta a partir da fonte oficial e
 * some quando o problema é resolvido lá. Nada é marcado, gravado ou
 * dispensado por aqui — "resolver" é sempre ir à tela de origem.
 */
export type Gravidade = 'critico' | 'atencao' | 'aviso'
export type Categoria = 'admissao_documentos' | 'avaliacao_grau_pais' | 'plantao' | 'ocupacao_equipe'

export interface Alerta {
  id: string
  regra: string
  categoria: Categoria
  gravidade: Gravidade
  titulo: string
  detalhe: string | null
  residente_id: string | null
  residente_nome: string | null
  referencia_id: string | null
  desde: string | null
}

export interface CentralAlertas {
  gerado_em: string
  contagem: Record<Gravidade, number>
  alertas: Alerta[]
}

export async function listarAlertas(): Promise<CentralAlertas> {
  const { data } = await api.get<CentralAlertas>('/central-alertas/')
  return data
}

export const GRAVIDADES: Gravidade[] = ['critico', 'atencao', 'aviso']

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

/** Onde cada alerta é resolvido — a mesma ideia do "Resolver em" da admissão. */
export function destinoDoAlerta(a: Alerta): { to: string; rotulo: string } {
  switch (a.regra) {
    case 'admissao_parada':
      return { to: `/admissoes/${a.referencia_id}`, rotulo: 'Admissões' }
    case 'documento_aguardando_validacao':
    case 'documento_vencido':
    case 'documento_vencendo':
      return { to: '/documentos', rotulo: 'Documentos' }
    case 'avaliacao_vencida':
    case 'grau_ausente':
    case 'grau_vencido':
      return { to: '/avaliacoes', rotulo: 'Avaliações' }
    case 'pais_parado':
    case 'pais_vencido':
      return { to: `/plano/${a.referencia_id}`, rotulo: 'Plano de Cuidados' }
    case 'pais_ausente':
      return { to: '/plano', rotulo: 'Plano de Cuidados' }
    case 'cuidados_sem_registro':
    case 'doses_sem_registro':
      return { to: '/plantao', rotulo: 'Meu Plantão' }
    case 'intercorrencia_grave_aberta':
    case 'intercorrencia_aberta_prolongada':
      return { to: '/intercorrencias', rotulo: 'Intercorrências' }
    case 'residente_sem_leito':
    case 'ausencia_prolongada':
      return { to: '/quartos', rotulo: 'Quartos e Leitos' }
    case 'acesso_nao_utilizado':
      return { to: '/equipe', rotulo: 'Equipe' }
    default:
      return a.residente_id ? { to: `/residentes/${a.residente_id}`, rotulo: 'Prontuário' } : { to: '/', rotulo: 'Início' }
  }
}

/** "há 3 dias", "há 2 horas", "há poucos minutos". */
export function haQuantoTempo(iso: string | null, agora: Date = new Date()): string | null {
  if (!iso) return null
  const minutos = Math.floor((agora.getTime() - new Date(iso).getTime()) / 60000)
  if (Number.isNaN(minutos)) return null
  if (minutos < 60) return 'há poucos minutos'
  const horas = Math.floor(minutos / 60)
  if (horas < 24) return `há ${horas} ${horas === 1 ? 'hora' : 'horas'}`
  const dias = Math.floor(horas / 24)
  return `há ${dias} ${dias === 1 ? 'dia' : 'dias'}`
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

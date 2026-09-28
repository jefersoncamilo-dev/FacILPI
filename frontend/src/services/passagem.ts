import { api } from './api'

/**
 * Passagem de plantão persistida (#125) — espelha backend/src/application/passagem.py.
 *
 * A passagem é o REGISTRO do que foi comunicado na troca de turno, não fonte
 * de fatos clínicos: a parte automática é montada pelo servidor a partir das
 * fontes; a parte manual são observações curtas. Quem recebe vê a situação
 * ATUAL de cada fonte.
 */
export type CategoriaObservacao = 'assistencial' | 'comportamento' | 'familia_visitas' | 'estrutura_materiais' | 'outro'
export type OrigemItem = 'alerta' | 'intercorrencia' | 'atividade' | 'ausencia' | 'observacao'

export interface ItemPassagem {
  id: string | null
  origem: OrigemItem
  alerta_id: string | null
  regra: string | null
  referencia_id: string | null
  residente_id: string | null
  residente_nome: string | null
  gravidade: string | null
  natureza: string | null
  titulo: string
  previsto_em: string | null
  categoria: CategoriaObservacao | null
  texto: string | null
  situacao_atual: 'aberto' | 'resolvido' | null
}

export interface Previa {
  area_id: string | null
  area_nome: string | null
  janela_inicio: string
  janela_fim: string
  itens: ItemPassagem[]
}

export interface Passagem {
  id: string
  area_id: string | null
  area_nome: string | null
  plantao_id: string | null
  janela_inicio: string
  janela_fim: string
  situacao: 'entregue' | 'recebida'
  entregue_por_nome: string
  entregue_por_mim: boolean
  entregue_em: string
  recebida_por_nome: string | null
  recebida_em: string | null
  da_minha_area: boolean
  itens: ItemPassagem[]
  /** Itens cuja origem quem consulta não lê (só a contagem). */
  itens_sem_acesso: number
}

export interface ObservacaoNova {
  categoria: CategoriaObservacao
  residente_id?: string
  texto: string
}

export const LIMITE_OBSERVACAO = 280

export const ROTULO_CATEGORIA: Record<CategoriaObservacao, string> = {
  assistencial: 'Assistencial',
  comportamento: 'Comportamento',
  familia_visitas: 'Família e visitas',
  estrutura_materiais: 'Estrutura e materiais',
  outro: 'Outro',
}

export const ROTULO_ORIGEM: Record<OrigemItem, string> = {
  alerta: 'Alerta',
  intercorrencia: 'Intercorrência',
  atividade: 'Atividade não concluída',
  ausencia: 'Ausência',
  observacao: 'Observação',
}

export const passagemApi = {
  previa: (areaId?: string) => api.get<Previa>('/passagens/previa', { params: areaId ? { area_id: areaId } : {} }).then(r => r.data),
  listar: (situacao: 'entregue' | 'recebida' | 'todas' = 'entregue') =>
    api.get<Passagem[]>('/passagens/', { params: { situacao } }).then(r => r.data),
  entregar: (dados: { area_id?: string; observacoes: ObservacaoNova[]; encerrar_plantao: boolean }) =>
    api.post<Passagem>('/passagens/', dados).then(r => r.data),
  receber: (id: string) => api.post<Passagem>(`/passagens/${id}/receber`, {}).then(r => r.data),
}

import { api } from './api'

/**
 * Espelha o PAIS (backend/src/application/pais.py e schemas PlanoCuidados*,
 * Necessidade*, Meta*, Intervencao*) — UX-07 / #80. A máquina de estados é a
 * do backend; a tela só oferece a próxima ação válida e deixa o servidor decidir.
 *
 *   rascunho → em_elaboracao → em_revisao → aprovado → vigente → encerrado
 *   (aprovado/vigente geram nova versão; ao ativar, a anterior vira substituído)
 *
 * Conteúdo (necessidades, metas, intervenções) só muda em rascunho ou em
 * elaboração; depois, só por nova versão. Aprovar exige ao menos uma
 * necessidade, uma meta e uma intervenção ativas. Revisar e aprovar registram
 * quem revisou/aprovou e quando (o momento da ação). Uma nova versão só entra
 * em vigência depois que a vigente é encerrada (test_d1_pais::test_11).
 */
export type SituacaoPais = 'rascunho' | 'em_elaboracao' | 'em_revisao' | 'aprovado' | 'vigente' | 'encerrado' | 'substituido'

export const CICLO: SituacaoPais[] = ['rascunho', 'em_elaboracao', 'em_revisao', 'aprovado', 'vigente']

export const ROTULO_PAIS: Record<SituacaoPais, string> = {
  rascunho: 'Rascunho',
  em_elaboracao: 'Em elaboração',
  em_revisao: 'Em revisão',
  aprovado: 'Aprovado',
  vigente: 'Vigente',
  encerrado: 'Encerrado',
  substituido: 'Substituído',
}

export const EDITAVEL: SituacaoPais[] = ['rascunho', 'em_elaboracao']
export const TERMINAIS_PAIS: SituacaoPais[] = ['encerrado', 'substituido']

export interface Necessidade { id: string; descricao: string; categoria: string | null; gravidade: string | null; evidencias: string | null; origem: string; situacao: 'ativa' | 'inativa' }
export interface Meta { id: string; descricao: string; indicador: string | null; valor_esperado: string | null; prazo: string | null; responsavel_funcionario_id: string | null; situacao: 'ativa' | 'inativa' }
export interface Intervencao {
  id: string; descricao: string; necessidade_id: string | null; frequencia: string | null; horario: string | null
  perfil_responsavel: string | null; profissional_designado_id: string | null; prioridade: string | null; instrucoes: string | null; situacao: 'ativa' | 'inativa'
}

export interface Plano {
  id: string
  residente_id: string
  versao: number
  objetivos: string | null
  data_inicial: string
  data_final: string | null
  situacao: SituacaoPais
  revisor_funcionario_id: string | null
  aprovador_funcionario_id: string | null
  revisado_em: string | null
  aprovado_em: string | null
  motivo_encerramento: string | null
  encerrado_em: string | null
  anterior_id: string | null
  motivo_versao: string | null
  superseded_by: string | null
  created_at: string | null
  necessidades: Necessidade[]
  metas: Meta[]
  intervencoes: Intervencao[]
}

export type TipoItem = 'necessidades' | 'metas' | 'intervencoes'

const BASE = '/planos-cuidados/'

export const paisApi = {
  listar: () => api.get<Plano[]>(BASE, { params: { limit: 500 } }).then(r => r.data),
  obter: (id: string) => api.get<Plano>(`${BASE}${id}`).then(r => r.data),
  criar: (dados: { residente_id: string; data_inicial: string; data_final?: string; objetivos?: string }) =>
    api.post<Plano>(BASE, dados).then(r => r.data),
  iniciarElaboracao: (id: string) => api.patch<Plano>(`${BASE}${id}`, { situacao: 'em_elaboracao' }).then(r => r.data),
  revisar: (id: string, funcionario_id: string) => api.post<Plano>(`${BASE}${id}/revisar`, { funcionario_id }).then(r => r.data),
  aprovar: (id: string, funcionario_id: string) => api.post<Plano>(`${BASE}${id}/aprovar`, { funcionario_id }).then(r => r.data),
  ativar: (id: string) => api.post<Plano>(`${BASE}${id}/ativar`, {}).then(r => r.data),
  novaVersao: (id: string, motivo: string) => api.post<Plano>(`${BASE}${id}/nova-versao`, { motivo }).then(r => r.data),
  encerrar: (id: string, motivo: string, funcionario_id: string) =>
    api.post<Plano>(`${BASE}${id}/encerrar`, { motivo, funcionario_id }).then(r => r.data),
  adicionar: (id: string, tipo: TipoItem, dados: Record<string, string>) =>
    api.post(`${BASE}${id}/${tipo}`, dados).then(r => r.data),
  inativar: (id: string, tipo: TipoItem, itemId: string) =>
    api.patch(`${BASE}${id}/${tipo}/${itemId}`, { situacao: 'inativa' }).then(r => r.data),
}

/** Próxima ação do ciclo para cada situação, com a permissão que o backend exige. */
export const PROXIMA_ACAO: Partial<Record<SituacaoPais, {
  acao: 'iniciar' | 'revisar' | 'aprovar' | 'ativar'; rotulo: string; sucesso: string; permissao: string; exigeFuncionario?: 'Revisado por' | 'Aprovado por'
}>> = {
  rascunho: { acao: 'iniciar', rotulo: 'Iniciar elaboração', sucesso: 'Elaboração iniciada.', permissao: 'planos_cuidados:atualizar' },
  em_elaboracao: { acao: 'revisar', rotulo: 'Registrar revisão', sucesso: 'Revisão registrada.', permissao: 'planos_cuidados:revisar', exigeFuncionario: 'Revisado por' },
  em_revisao: { acao: 'aprovar', rotulo: 'Registrar aprovação', sucesso: 'Aprovação registrada.', permissao: 'planos_cuidados:aprovar', exigeFuncionario: 'Aprovado por' },
  aprovado: { acao: 'ativar', rotulo: 'Colocar em vigência', sucesso: 'Plano em vigência.', permissao: 'planos_cuidados:aprovar' },
}

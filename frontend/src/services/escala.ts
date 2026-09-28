import { api } from './api'

/**
 * Estrutura operacional (#120) — espelha backend/src/application/operacao.py.
 *
 * Responsabilidade NÃO é permissão: dizer que alguém responde pela Ala B não
 * abre nenhuma tela nova para essa pessoa. Quem pode ver o quê continua sendo
 * decidido pelo backend (RBAC).
 */
export type TipoArea = 'ala' | 'setor' | 'unidade' | 'grupo'

export interface LeitoDaArea {
  vinculo_id: string
  quarto_leito_id: string
  unidade: string | null
  quarto: string
  leito: string
  ocupado: boolean
  desde: string
}

export interface Area {
  id: string
  nome: string
  tipo: TipoArea
  descricao: string | null
  situacao: 'ativa' | 'inativa'
  leitos: LeitoDaArea[]
}

export interface Turno {
  id: string
  nome: string
  hora_inicio: string
  hora_fim: string
  situacao: 'ativo' | 'inativo'
}

export interface Responsabilidade {
  id: string
  plantao_id: string
  funcionario_id: string
  funcionario_nome: string
  area_id: string
  area_nome: string
  inicio_em: string
  fim_em: string | null
  motivo_fim: 'fim_plantao' | 'transferencia' | 'ajuste' | null
}

export interface Plantao {
  id: string
  funcionario_id: string
  funcionario_nome: string
  turno_id: string | null
  turno_nome: string | null
  inicio_em: string
  fim_em: string | null
  situacao: 'em_andamento' | 'encerrado'
  /** #122: escala planejada que este plantão cumpre (null = cobertura sem escala). */
  escala_id?: string | null
  responsabilidades: Responsabilidade[]
}

export type EstadoEscala = 'prevista' | 'presente' | 'realizada' | 'nao_iniciada' | 'ausente' | 'substituida' | 'cancelada'

/** Escala PLANEJADA (#122): quem deveria trabalhar. O plantão real continua em `Plantao`. */
export interface Escala {
  id: string
  funcionario_id: string
  funcionario_nome: string
  turno_id: string | null
  turno_nome: string | null
  area_id: string | null
  area_nome: string | null
  inicio_previsto: string
  fim_previsto: string
  tipo: 'regular' | 'substituicao' | 'cobertura'
  situacao: 'prevista' | 'ausente' | 'cancelada'
  motivo: string | null
  substitui_escala_id: string | null
  substituta_id: string | null
  substituto_nome: string | null
  plantao_id: string | null
  /** Previsto × efetivo, derivado agora pelo backend. */
  estado: EstadoEscala
}

export interface EscalaDia {
  dia: string
  fuso: string
  escalas: Escala[]
  coberturas_sem_escala: Plantao[]
}

export const ROTULO_ESTADO_ESCALA: Record<EstadoEscala, string> = {
  prevista: 'Prevista',
  presente: 'Presente',
  realizada: 'Realizada',
  nao_iniciada: 'Não iniciada',
  ausente: 'Ausente',
  substituida: 'Substituída',
  cancelada: 'Cancelada',
}

export interface PlantaoAtual {
  pode_registrar: boolean
  funcionario_id: string | null
  plantao: Plantao | null
  /** #122: escalas previstas da própria pessoa ainda por cumprir. */
  escalas_pendentes?: Escala[]
}

export interface AreaAgora {
  area: Area
  responsaveis: Responsabilidade[]
  /** null quando a sessão não lê residentes (RBAC). */
  residentes: number | null
}

export interface EscalaAgora {
  gerado_em: string
  areas: AreaAgora[]
  plantoes_sem_area: Plantao[]
}

export const ROTULO_TIPO_AREA: Record<TipoArea, string> = {
  ala: 'Ala',
  setor: 'Setor',
  unidade: 'Unidade',
  grupo: 'Grupo',
}

export const rotuloLeitoDaArea = (l: Pick<LeitoDaArea, 'unidade' | 'quarto' | 'leito'>) =>
  [l.unidade, `Quarto ${l.quarto}`, `Leito ${l.leito}`].filter(Boolean).join(' · ')

export const escalaApi = {
  areas: () => api.get<Area[]>('/escala/areas').then(r => r.data),
  criarArea: (dados: { nome: string; tipo: TipoArea; descricao?: string }) => api.post<Area>('/escala/areas', dados).then(r => r.data),
  atualizarArea: (id: string, dados: Partial<Pick<Area, 'nome' | 'tipo' | 'descricao' | 'situacao'>>) =>
    api.patch<Area>(`/escala/areas/${id}`, dados).then(r => r.data),
  vincularLeito: (areaId: string, quartoLeitoId: string) =>
    api.post<Area>(`/escala/areas/${areaId}/leitos`, { quarto_leito_id: quartoLeitoId }).then(r => r.data),
  removerLeito: (areaId: string, quartoLeitoId: string) =>
    api.post<Area>(`/escala/areas/${areaId}/leitos/${quartoLeitoId}/remover`, {}).then(r => r.data),
  turnos: () => api.get<Turno[]>('/escala/turnos').then(r => r.data),
  criarTurno: (dados: { nome: string; hora_inicio: string; hora_fim: string }) => api.post<Turno>('/escala/turnos', dados).then(r => r.data),
  atualizarTurno: (id: string, dados: Partial<Pick<Turno, 'nome' | 'hora_inicio' | 'hora_fim' | 'situacao'>>) =>
    api.patch<Turno>(`/escala/turnos/${id}`, dados).then(r => r.data),
  agora: () => api.get<EscalaAgora>('/escala/agora').then(r => r.data),
  transferir: (dados: { area_id: string; para_plantao_id: string; de_funcionario_id?: string }) =>
    api.post<Responsabilidade[]>('/escala/responsabilidades/transferir', dados).then(r => r.data),
  encerrarResponsabilidade: (id: string) => api.post<Responsabilidade>(`/escala/responsabilidades/${id}/encerrar`, {}).then(r => r.data),
  dia: (dia?: string) => api.get<EscalaDia>('/escala/previsto', { params: dia ? { dia } : {} }).then(r => r.data),
  criarEscala: (dados: { funcionario_id: string; turno_id?: string; area_id?: string; data?: string; tipo?: 'regular' | 'cobertura' }) =>
    api.post<Escala>('/escala/previsto', dados).then(r => r.data),
  ausencia: (id: string, motivo: string) => api.post<Escala>(`/escala/previsto/${id}/ausencia`, { motivo }).then(r => r.data),
  substituir: (id: string, funcionario_id: string, motivo: string) =>
    api.post<Escala[]>(`/escala/previsto/${id}/substituir`, { funcionario_id, motivo }).then(r => r.data),
  cancelar: (id: string, motivo: string) => api.post<Escala>(`/escala/previsto/${id}/cancelar`, { motivo }).then(r => r.data),
}

export const plantoesApi = {
  atual: () => api.get<PlantaoAtual>('/plantoes/atual').then(r => r.data),
  iniciar: (dados: { area_ids: string[]; turno_id?: string; escala_id?: string }) => api.post<Plantao>('/plantoes/iniciar', dados).then(r => r.data),
  encerrar: (id: string) => api.post<Plantao>(`/plantoes/${id}/encerrar`, {}).then(r => r.data),
}

import { api } from './api'

// Espelha PlantaoItem de backend/src/application/schemas.py e a projeção de
// backend/src/application/rotina.py. `/plantao/` é READ-ONLY: nenhuma linha é
// criada ali. Toda escrita vai para o endpoint oficial do fato subjacente.
export type PlantaoOrigem = 'cuidado' | 'medicacao' | 'intercorrencia'

export interface PlantaoItem {
  origem: PlantaoOrigem
  registro_id: string
  residente_id: string
  descricao: string
  // Intercorrência aberta não tem horário previsto; a projeção envia null e
  // ordena esses itens por último.
  previsto_em?: string | null
  // Só `cuidado` carrega prioridade (vem da ProgramacaoCuidado).
  prioridade?: string | null
  // G3: "Ala B · Quarto 12 · Leito A" do leito atual; null sem leito.
  local?: string | null
  // UX-01E: grau de dependência ATIVO ('Grau I' | 'Grau II' | 'Grau III'); null sem grau.
  grau?: string | null
}

export interface PlantaoConsultaParams {
  a_partir_de?: string
  ate?: string
  residente_id?: string
  limit?: number
}

// Mesmo default do backend (rotina.py). Declarado aqui para que a tela saiba
// quando a projeção pode ter sido truncada e avise, em vez de omitir em silêncio.
export const PLANTAO_LIMIT_PADRAO = 200

/**
 * Texto do item na tela (UX-11 / #101). A projeção devolve descrições técnicas
 * sem acento ("Dose prevista de medicacao", "Intercorrencia aberta: Queda");
 * o contrato não muda — só o que aparece para a equipe.
 */
export function rotuloDoItem(item: Pick<PlantaoItem, 'origem' | 'descricao'>): string {
  if (item.origem === 'medicacao') return 'Dose prevista de medicação'
  if (item.origem === 'intercorrencia') {
    const tipo = (item.descricao || '').replace(/^Intercorr[eê]ncia aberta:\s*/i, '').trim()
    return tipo ? `Intercorrência aberta: ${tipo}` : 'Intercorrência aberta'
  }
  return item.descricao || 'Cuidado programado'
}

export const PLANTAO_ORIGENS: { value: PlantaoOrigem; label: string }[] = [
  { value: 'cuidado', label: 'Cuidados' },
  { value: 'medicacao', label: 'Medicação' },
  { value: 'intercorrencia', label: 'Intercorrências' },
]

export async function getPlantao(params: PlantaoConsultaParams = {}): Promise<PlantaoItem[]> {
  const { data } = await api.get<PlantaoItem[]>('/plantao/', { params })
  return data
}

// ---- Escrita: cada origem tem seu endpoint oficial ----

// ExecucaoCreate: justificativa é obrigatória quando o resultado não é "executada".
export type ResultadoCuidado = 'executada' | 'recusada' | 'omitida'

export interface ExecucaoCuidadoPayload {
  ocorrencia_id: string
  resultado: ResultadoCuidado
  ocorrido_em: string
  observacao?: string
  justificativa?: string
  percentual_consumido?: PercentualConsumido
}

// G4 (D6): quanto da refeição foi consumido; opcional e só com "executada".
export type PercentualConsumido = 0 | 25 | 50 | 75 | 100
export const PERCENTUAIS_CONSUMO: PercentualConsumido[] = [0, 25, 50, 75, 100]

export async function registrarExecucaoCuidado(payload: ExecucaoCuidadoPayload) {
  const { data } = await api.post('/execucoes-cuidado/', payload)
  return data
}

// UX-01A: rótulos operacionais; o enum do backend não muda.
export const ROTULO_RESULTADO_CUIDADO: Record<ResultadoCuidado, string> = {
  executada: 'Realizado',
  recusada: 'Recusado',
  omitida: 'Não realizado',
}

export interface RegistroCuidado {
  resultado: ResultadoCuidado
  justificativa?: string
  observacao?: string
  // G7: horário real do cuidado (ISO), até 24 h para trás; ausente = agora.
  ocorrido_em?: string
  percentual_consumido?: PercentualConsumido | null
}

/**
 * Registro de UM cuidado do plantão, no instante atual (ou no informado). Ponto único de escrita
 * da tela: o registro em lote (UX-01C) chama esta função item a item — o banco
 * continua recebendo uma execução por ocorrência.
 */
export async function registrarCuidado(item: Pick<PlantaoItem, 'registro_id'>, registro: RegistroCuidado) {
  const justificativa = registro.justificativa?.trim()
  const observacao = registro.observacao?.trim()
  return registrarExecucaoCuidado({
    ocorrencia_id: item.registro_id,
    resultado: registro.resultado,
    ocorrido_em: registro.ocorrido_em ?? new Date().toISOString(),
    ...(registro.resultado !== 'executada' && justificativa ? { justificativa } : {}),
    ...(observacao ? { observacao } : {}),
    ...(registro.resultado === 'executada' && registro.percentual_consumido != null
      ? { percentual_consumido: registro.percentual_consumido } : {}),
  })
}

// ---- UX-01F: correção de registros de cuidado (decisão A) ----
// Correção = estorno (`execucoes:corrigir`): o registro original nunca é apagado,
// fica marcado como corrigido com motivo, autor e horário. Só cuidados.

export interface ExecucaoRegistrada {
  id: string
  residente_id: string
  ocorrencia_id: string
  resultado: ResultadoCuidado
  ocorrido_em: string
  observacao?: string | null
  justificativa?: string | null
  estornado_em?: string | null
  motivo_estorno?: string | null
  substitui_id?: string | null
  descricao?: string | null
  executor_nome?: string | null
}

export async function listarRegistrosRecentes(aPartirDe: string): Promise<ExecucaoRegistrada[]> {
  const { data } = await api.get<ExecucaoRegistrada[]>('/execucoes-cuidado/', { params: { a_partir_de: aPartirDe, limit: 200 } })
  return data
}

export interface Correcao {
  motivo: string
  // null = anular: o registro não deveria existir e o cuidado volta para a fila.
  novo: RegistroCuidado | null
}

export async function corrigirRegistro(registro: ExecucaoRegistrada, correcao: Correcao) {
  const justificativa = correcao.novo?.justificativa?.trim()
  const observacao = correcao.novo?.observacao?.trim()
  const { data } = await api.post(`/execucoes-cuidado/${registro.id}/estornar`, {
    motivo: correcao.motivo.trim(),
    ...(correcao.novo
      ? {
          substituto: {
            ocorrencia_id: registro.ocorrencia_id,
            resultado: correcao.novo.resultado,
            // Corrige o resultado, não o horário: o fato continua no mesmo instante.
            ocorrido_em: registro.ocorrido_em,
            ...(correcao.novo.resultado !== 'executada' && justificativa ? { justificativa } : {}),
            ...(observacao ? { observacao } : {}),
          },
        }
      : {}),
  })
  return data
}

// C5AdministracaoCreate: quantidade obrigatória quando "administrada";
// justificativa obrigatória nos demais resultados.
export type ResultadoDose = 'administrada' | 'recusada' | 'omitida'

export interface AdministracaoPayload {
  dose_prevista_id: string
  resultado: ResultadoDose
  ocorrido_em: string
  quantidade_realizada?: number
  justificativa?: string
  observacao?: string
}

export async function registrarAdministracao(payload: AdministracaoPayload) {
  const { data } = await api.post('/administracoes/', payload)
  return data
}

// IntercorrenciaEncerrar: desfecho não pode ser vazio.
export async function encerrarIntercorrencia(intercorrenciaId: string, desfecho: string) {
  const { data } = await api.post(`/intercorrencias/${intercorrenciaId}/encerrar`, { desfecho })
  return data
}

// Nome do residente não vem na projeção, só o id. A busca é auxiliar: se falhar,
// a tela mostra o id — degradar o rótulo é aceitável, esconder pendência não é.
export interface ResidenteResumo {
  id: string
  nome: string
  // Texto livre do cadastro; o avatar só usa se for imagem (data:image ou https).
  foto?: string | null
}

export async function getResidentesResumo(): Promise<ResidenteResumo[]> {
  const { data } = await api.get<ResidenteResumo[]>('/residentes/')
  return data
}

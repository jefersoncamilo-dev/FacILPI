import { api } from './api'

// Espelha IntercorrenciaCreate/IntercorrenciaResponse (backend/src/application/schemas.py:832-900)
// e o roteador de backend/src/main.py:1209-1340.
//
// Contrato do módulo neste ciclo: apenas leitura e criação. Correção (PATCH) e
// encerramento existem no backend mas ficam fora do B2 — o encerramento já é
// feito pelo Meu Plantão e não deve ser duplicado aqui.
//
// Tenant (`ilpi_id`), autoria (`responsavel`), `situacao`, `desfecho` e o
// timestamp técnico `data` são resolvidos pelo backend. O cliente nunca os envia.

export type Gravidade = 'leve' | 'moderada' | 'grave'

export const GRAVIDADES: { value: Gravidade; label: string }[] = [
  { value: 'leve', label: 'Leve' },
  { value: 'moderada', label: 'Moderada' },
  { value: 'grave', label: 'Grave' },
]

export interface IntercorrenciaPayload {
  residente_id: string
  tipo: string
  gravidade: Gravidade
  /** Instante ISO com fuso. Opcional no backend; a tela sempre envia o que exibe. */
  ocorrido_em?: string
  sbar_situacao?: string
  sbar_contexto?: string
  sbar_avaliacao?: string
  sbar_recomendacao?: string
  providencia?: string
}

export interface Intercorrencia {
  id: string
  residente_id: string
  tipo: string
  gravidade: Gravidade
  situacao: 'aberta' | 'encerrada'
  ocorrido_em?: string | null
  /** Timestamp técnico de criação do registro (registrado_em). */
  data?: string | null
  responsavel?: string | null
  desfecho?: string | null
  sbar_situacao?: string | null
  sbar_contexto?: string | null
  sbar_avaliacao?: string | null
  sbar_recomendacao?: string | null
  providencia?: string | null
}

// Teto RÍGIDO do backend: `min(limit, 100)` em main.py:1223. Pedir mais não
// devolve mais. Declarado aqui para que a tela avise truncamento em vez de
// omitir registros em silêncio.
export const INTERCORRENCIAS_LIMIT_PADRAO = 100

export interface IntercorrenciasConsultaParams {
  residente_id?: string
  skip?: number
  limit?: number
}

export async function getIntercorrencias(
  params: IntercorrenciasConsultaParams = {},
): Promise<Intercorrencia[]> {
  const { data } = await api.get<Intercorrencia[]>('/intercorrencias/', { params })
  return data
}

export async function registrarIntercorrencia(
  payload: IntercorrenciaPayload,
): Promise<Intercorrencia> {
  const { data } = await api.post<Intercorrencia>('/intercorrencias/', payload)
  return data
}

// ---- Formulário: estado, conversão e validação espelhada ----

export interface FormularioIntercorrencia {
  tipo: string
  gravidade: Gravidade
  /** Valor cru do input `datetime-local`, na hora local do dispositivo. */
  ocorridoEm: string
  sbarSituacao: string
  sbarContexto: string
  sbarAvaliacao: string
  sbarRecomendacao: string
  providencia: string
}

/** `YYYY-MM-DDTHH:mm` na hora local — formato exigido por `datetime-local`. */
export function paraInputLocal(instante: Date): string {
  const deslocado = new Date(instante.getTime() - instante.getTimezoneOffset() * 60_000)
  return deslocado.toISOString().slice(0, 16)
}

export function formularioVazio(agora: Date = new Date()): FormularioIntercorrencia {
  return {
    tipo: '',
    gravidade: 'leve',
    // Default visual "agora": o plantonista costuma registrar no instante do
    // evento e só ajusta quando anota depois.
    ocorridoEm: paraInputLocal(agora),
    sbarSituacao: '',
    sbarContexto: '',
    sbarAvaliacao: '',
    sbarRecomendacao: '',
    providencia: '',
  }
}

export interface ResultadoPayload {
  erro: string | null
  payload: IntercorrenciaPayload | null
}

export function montarPayload(
  residenteId: string,
  form: FormularioIntercorrencia,
  agora: Date = new Date(),
): ResultadoPayload {
  if (!residenteId) return { erro: 'Selecione o residente.', payload: null }

  const tipo = form.tipo.trim()
  // Espelha `tipo_nao_vazio` e `Field(min_length=1, max_length=100)`.
  if (!tipo) return { erro: 'Informe o tipo da intercorrência.', payload: null }
  if (tipo.length > 100) return { erro: 'O tipo deve ter no máximo 100 caracteres.', payload: null }

  if (!form.ocorridoEm.trim()) {
    return { erro: 'Informe a data e hora da ocorrência.', payload: null }
  }
  const instante = new Date(form.ocorridoEm)
  if (Number.isNaN(instante.getTime())) {
    return { erro: 'Data e hora da ocorrência inválidas.', payload: null }
  }
  // Espelha a recusa do handler (main.py). O backend continua sendo a autoridade:
  // o relógio do dispositivo pode estar adiantado e o 422 é tratado na tela.
  if (instante.getTime() > agora.getTime()) {
    return { erro: 'A ocorrência não pode estar no futuro.', payload: null }
  }

  const payload: IntercorrenciaPayload = {
    residente_id: residenteId,
    tipo,
    gravidade: form.gravidade,
    // toISOString sempre emite UTC com sufixo Z — o backend exige fuso.
    ocorrido_em: instante.toISOString(),
  }

  const opcionais: [keyof IntercorrenciaPayload, string][] = [
    ['sbar_situacao', form.sbarSituacao],
    ['sbar_contexto', form.sbarContexto],
    ['sbar_avaliacao', form.sbarAvaliacao],
    ['sbar_recomendacao', form.sbarRecomendacao],
    ['providencia', form.providencia],
  ]
  for (const [campo, valor] of opcionais) {
    const limpo = valor.trim()
    if (limpo) payload[campo] = limpo as never
  }

  return { erro: null, payload }
}

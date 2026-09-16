import { api } from './api'

// Espelha SinalVitalCreate/SinalVitalResponse (backend/src/application/schemas.py:795-829)
// e o roteador de backend/src/main.py:1102-1194.
//
// Contrato do módulo: correção é um NOVO INSERT. O backend não expõe PUT nem
// DELETE de sinal vital, e este serviço não os inventa.
// Tenant e autoria (`profissional`) vêm da sessão — o payload nunca os envia.

export type CampoSinal =
  | 'temperatura'
  | 'pressao_sistolica'
  | 'pressao_diastolica'
  | 'frequencia_cardiaca'
  | 'frequencia_respiratoria'
  | 'saturacao'
  | 'glicemia'
  | 'peso'

export interface SinalVitalPayload extends Partial<Record<CampoSinal, number>> {
  residente_id: string
  /** Instante ISO com fuso. Omitido = backend usa `datetime.now(timezone.utc)`. */
  data?: string
  observacao?: string
}

export interface SinalVital extends Partial<Record<CampoSinal, number | null>> {
  id: string
  residente_id: string
  profissional?: string | null
  data?: string | null
  observacao?: string | null
}

export interface DefinicaoSinal {
  campo: CampoSinal
  label: string
  /** Unidade implícita do backend (schemas.py:792-794), explicitada aqui só para a tela. */
  unidade: string
  /** O backend declara `Optional[int]`; float com parte fracionária vira 422 no Pydantic. */
  inteiro: boolean
  /** Presentes apenas onde o schema declara `Field(ge=...)`/`Field(le=...)`. */
  min?: number
  max?: number
}

// A ordem é a clínica usual de aferição, não a do schema.
// `temperatura` NÃO tem `min`: o schema a declara como `Optional[float]` sem
// `ge`, e inventar um piso aqui criaria regra que o backend não tem.
export const SINAIS_VITAIS_CAMPOS: readonly DefinicaoSinal[] = [
  { campo: 'temperatura', label: 'Temperatura', unidade: '°C', inteiro: false },
  { campo: 'pressao_sistolica', label: 'Pressão sistólica', unidade: 'mmHg', inteiro: true, min: 0 },
  { campo: 'pressao_diastolica', label: 'Pressão diastólica', unidade: 'mmHg', inteiro: true, min: 0 },
  { campo: 'frequencia_cardiaca', label: 'Frequência cardíaca', unidade: 'bpm', inteiro: true, min: 0 },
  { campo: 'frequencia_respiratoria', label: 'Frequência respiratória', unidade: 'irpm', inteiro: true, min: 0 },
  { campo: 'saturacao', label: 'Saturação', unidade: '%', inteiro: true, min: 0, max: 100 },
  { campo: 'glicemia', label: 'Glicemia', unidade: 'mg/dL', inteiro: false, min: 0 },
  { campo: 'peso', label: 'Peso', unidade: 'kg', inteiro: false, min: 0 },
]

// Mesmo default de `list_sinais_vitais` (main.py:1125). Declarado aqui para que a
// tela avise quando a página pode ter sido truncada, em vez de omitir em silêncio.
export const SINAIS_VITAIS_LIMIT_PADRAO = 100

export interface SinaisVitaisConsultaParams {
  residente_id?: string
  skip?: number
  limit?: number
}

export async function getSinaisVitais(params: SinaisVitaisConsultaParams = {}): Promise<SinalVital[]> {
  const { data } = await api.get<SinalVital[]>('/sinais-vitais/', { params })
  return data
}

export async function registrarSinalVital(payload: SinalVitalPayload): Promise<SinalVital> {
  const { data } = await api.post<SinalVital>('/sinais-vitais/', payload)
  return data
}

// ---- Formulário: estado, parsing e validação espelhada ----

export interface FormularioSinais {
  valores: Record<CampoSinal, string>
  /** Valor cru do input `datetime-local` (hora local do dispositivo). */
  data: string
  observacao: string
}

export const FORMULARIO_SINAIS_VAZIO: FormularioSinais = {
  valores: {
    temperatura: '',
    pressao_sistolica: '',
    pressao_diastolica: '',
    frequencia_cardiaca: '',
    frequencia_respiratoria: '',
    saturacao: '',
    glicemia: '',
    peso: '',
  },
  data: '',
  observacao: '',
}

// Vírgula decimal é o que a equipe digita ("36,8"). `<input type="number">`
// descarta a vírgula em boa parte dos navegadores, e o campo pareceria estar
// "comendo" a tecla — por isso os campos são texto e a conversão acontece aqui.
// A regex recusa o que `Number` aceitaria por engano (string vazia vira 0,
// espaços viram 0, "1e3" vira 1000).
const NUMERO_ACEITO = /^-?\d+(?:[.,]\d+)?$/

export function parseNumero(bruto: string): number | null {
  const texto = bruto.trim()
  if (!texto) return null
  if (!NUMERO_ACEITO.test(texto)) return Number.NaN
  return Number(texto.replace(',', '.'))
}

/** Converte o valor local do input para instante ISO com fuso. */
export function dataLocalParaISO(valor: string): string | null {
  const texto = valor.trim()
  if (!texto) return null
  // Formas date-time sem offset são interpretadas como hora local (ES2020+),
  // que é exatamente o que o plantonista digitou.
  const instante = new Date(texto)
  if (Number.isNaN(instante.getTime())) return null
  return instante.toISOString()
}

export interface ResultadoPayload {
  erro: string | null
  payload: SinalVitalPayload | null
}

export function montarPayload(residenteId: string, form: FormularioSinais): ResultadoPayload {
  if (!residenteId) return { erro: 'Selecione o residente.', payload: null }

  const numeros: Partial<Record<CampoSinal, number>> = {}
  for (const def of SINAIS_VITAIS_CAMPOS) {
    const bruto = form.valores[def.campo] ?? ''
    if (!bruto.trim()) continue

    const valor = parseNumero(bruto)
    if (valor === null || Number.isNaN(valor)) {
      return { erro: `${def.label} deve ser um número válido.`, payload: null }
    }
    if (def.inteiro && !Number.isInteger(valor)) {
      return { erro: `${def.label} aceita apenas número inteiro.`, payload: null }
    }
    const abaixo = def.min !== undefined && valor < def.min
    const acima = def.max !== undefined && valor > def.max
    if (abaixo || acima) {
      // Campo com faixa fechada (saturação) fala em faixa; os demais só têm piso.
      const mensagem = def.max !== undefined
        ? `${def.label} deve estar entre ${def.min ?? 0} e ${def.max} ${def.unidade}.`
        : `${def.label} não pode ser menor que ${def.min} ${def.unidade}.`
      return { erro: mensagem, payload: null }
    }
    numeros[def.campo] = valor
  }

  // Espelha o validador `pelo_menos_um_sinal` (schemas.py:808-822).
  if (Object.keys(numeros).length === 0) {
    return { erro: 'Informe pelo menos um sinal vital.', payload: null }
  }

  const payload: SinalVitalPayload = { residente_id: residenteId, ...numeros }

  // `data` só viaja quando preenchida: ausente, o backend carimba o instante atual.
  if (form.data.trim()) {
    const iso = dataLocalParaISO(form.data)
    if (!iso) return { erro: 'Data e hora inválidas.', payload: null }
    payload.data = iso
  }
  if (form.observacao.trim()) payload.observacao = form.observacao.trim()

  return { erro: null, payload }
}

/**
 * Aviso NÃO bloqueante. O backend não compara sistólica e diastólica
 * (main.py:1099-1100), então a tela avisa e deixa registrar.
 */
export function avisoPressao(form: FormularioSinais): string | null {
  const sistolica = parseNumero(form.valores.pressao_sistolica)
  const diastolica = parseNumero(form.valores.pressao_diastolica)
  if (sistolica === null || diastolica === null) return null
  if (Number.isNaN(sistolica) || Number.isNaN(diastolica)) return null
  if (sistolica > diastolica) return null
  return 'Sistólica menor ou igual à diastólica. Confira os valores — o registro será aceito assim mesmo.'
}

/** Só os sinais realmente medidos, já com unidade, para exibição em lista. */
export function sinaisMedidos(registro: SinalVital): { label: string; texto: string }[] {
  const medidos: { label: string; texto: string }[] = []
  for (const def of SINAIS_VITAIS_CAMPOS) {
    const valor = registro[def.campo]
    if (valor === null || valor === undefined) continue
    medidos.push({ label: def.label, texto: `${String(valor).replace('.', ',')} ${def.unidade}` })
  }
  return medidos
}

import { api, mensagemDeErro } from './api'

// Espelha DocumentoCreate/DocumentoResponse (backend/src/application/schemas.py:926-971),
// o roteador da factory (backend/src/main.py:463-485), o anexo da A3 (main.py:635),
// o download autenticado (main.py:755) e o ato de validação (main.py:586).
//
// Contrato do módulo neste ciclo: listar, filtrar por residente, criar
// metadados, anexar arquivo, baixar e validar (#105 — a Documentação da
// admissão só avança com os obrigatórios validados). Edição (PUT) e inativação
// seguem fora do D2 por decisão da Control Tower — o backend continua
// oferecendo as duas.
//
// Tenant (`instituicao_id`), `situacao` inicial e a autoria do anexo
// (`anexado_por`/`anexado_em`) e da validação (`validado_por`/`validado_em`)
// são resolvidos pelo backend. O cliente nunca envia.

export interface DocumentoPayload {
  residente_id: string
  tipo: string
  numero?: string
  /** Data de calendário `YYYY-MM-DD`: a coluna é `Date`, sem hora nem fuso. */
  validade?: string
  obrigatorio?: boolean
  responsavel_envio?: string
}

export interface Documento {
  id: string
  residente_id?: string | null
  tipo: string
  numero?: string | null
  /**
   * Campo calculado pelo backend. A chave de storage (`arquivo`) é marcada
   * `exclude=True` e nunca chega ao cliente — é `arquivo_presente` que decide
   * entre oferecer "Anexar" e oferecer "Baixar".
   */
  arquivo_presente: boolean
  arquivo_nome_original?: string | null
  arquivo_mime?: string | null
  arquivo_tamanho?: number | null
  arquivo_hash?: string | null
  anexado_por?: string | null
  anexado_em?: string | null
  validade?: string | null
  obrigatorio?: boolean | null
  situacao?: string | null
  responsavel_envio?: string | null
  validado_por?: string | null
  validado_em?: string | null
  created_at?: string | null
}

// Default do handler da factory (`limit: int = 100`, main.py:275). Diferente de
// intercorrências, a factory NÃO tem teto (`min(limit, 100)`): este número é o
// que a tela recebe quando não pede outro, e serve para avisar truncamento em
// vez de omitir documentos em silêncio.
export const DOCUMENTOS_LIMIT_PADRAO = 100

export interface DocumentosConsultaParams {
  residente_id?: string
  skip?: number
  limit?: number
}

export async function getDocumentos(
  params: DocumentosConsultaParams = {},
): Promise<Documento[]> {
  const { data } = await api.get<Documento[]>('/documentos/', { params })
  return data
}

export async function criarDocumento(payload: DocumentoPayload): Promise<Documento> {
  const { data } = await api.post<Documento>('/documentos/', payload)
  return data
}

// ---- Validação ----

/**
 * Ato dedicado, sem volta pela tela: o backend não oferece invalidar nem
 * revalidar (409 `DOCUMENTO_JA_VALIDADO`). O corpo vai vazio porque
 * `DocumentoValidar` é `extra="forbid"` — autoria e horário vêm da sessão —, mas
 * precisa existir: sem corpo o FastAPI responde 422.
 */
export async function validarDocumento(documentoId: string): Promise<Documento> {
  const { data } = await api.post<Documento>(`/documentos/${documentoId}/validar`, {})
  return data
}

// ---- Anexo ----

/** `ARQUIVO_MAX_BYTES` de backend/src/main.py:557. */
export const ARQUIVO_MAX_BYTES = 10 * 1024 * 1024

/**
 * Guia o seletor do sistema. NÃO é validação: o backend decide o tipo pela
 * assinatura do conteúdo (`ARQUIVO_ASSINATURAS`, main.py:564), descartando
 * extensão e content-type do multipart.
 */
export const ARQUIVO_ACCEPT = '.pdf,.jpg,.jpeg,.png'
export const ARQUIVO_TIPOS_ROTULO = 'PDF, JPEG ou PNG, até 10 MB'

/**
 * Só o que o cliente sabe com certeza: tamanho. O tipo fica com o backend —
 * `file.type` é um palpite do sistema operacional pela extensão e vem vazio em
 * casos legítimos; recusar por ele bloquearia arquivo válido.
 */
export function validarArquivo(file: File | null): string | null {
  if (!file) return 'Selecione um arquivo.'
  if (file.size === 0) return 'O arquivo está vazio.'
  if (file.size > ARQUIVO_MAX_BYTES) return 'O arquivo excede o limite de 10 MB.'
  return null
}

export async function anexarArquivo(documentoId: string, file: File): Promise<Documento> {
  const form = new FormData()
  // O backend lê o campo `file` (File(...) em main.py:639); outro nome vira 422.
  form.append('file', file)

  const { data } = await api.post<Documento>(`/documentos/${documentoId}/arquivo`, form, {
    // A instância declara `Content-Type: application/json` (api.ts:8) e o
    // transformRequest do axios 1.x serializa FormData como JSON quando o
    // content-type é JSON (axios.cjs:2392) — o upload sairia como JSON e o
    // backend recusaria. Declarar multipart SEM boundary é o caminho correto:
    // o adaptador remove o header (axios.cjs:5162 no xhr, 5818 no fetch) para
    // que a plataforma o reemita com o boundary real.
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

// ---- Download ----

export interface ArquivoBaixado {
  blob: Blob
  nomeArquivo: string
}

/**
 * O backend emite `Content-Disposition` com o nome original, mas o CORS não
 * declara `expose_headers` (main.py:80-86), então esse cabeçalho não é legível
 * pelo JS em outra origem. O nome vem do próprio payload, que já o carrega.
 */
export function nomeDoArquivo(documento: Documento): string {
  const original = documento.arquivo_nome_original?.trim()
  if (original) return original
  const extensao = documento.arquivo_mime === 'application/pdf' ? '.pdf'
    : documento.arquivo_mime === 'image/png' ? '.png'
    : documento.arquivo_mime === 'image/jpeg' ? '.jpg'
    : ''
  return `documento-${documento.id}${extensao}`
}

export async function baixarArquivo(documento: Documento): Promise<ArquivoBaixado> {
  // Blob autenticado: o token viaja no header do interceptor, nunca na URL.
  const { data } = await api.get<Blob>(`/documentos/${documento.id}/arquivo`, {
    responseType: 'blob',
  })
  return { blob: data, nomeArquivo: nomeDoArquivo(documento) }
}

/**
 * Entrega o blob ao usuário e libera o ObjectURL.
 *
 * A revogação é adiada um tique: em parte dos navegadores revogar de forma
 * síncrona logo após o `click()` aborta o download que acabou de começar.
 * Adiar mantém a garantia de liberação sem correr esse risco.
 */
export function salvarArquivo(blob: Blob, nomeArquivo: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = nomeArquivo
  link.rel = 'noopener'
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

/**
 * Em `responseType: 'blob'` o corpo de ERRO também chega como Blob, e
 * `mensagemDeErro` — que procura `detail` num objeto — cairia sempre no texto
 * padrão. Aqui o blob é lido como texto e devolvido ao normalizador oficial,
 * que segue sendo o único ponto a converter erro de API em texto de tela.
 */
export async function mensagemDeErroDeBlob(e: unknown, padrao: string): Promise<string> {
  const resposta = (e as { response?: { data?: unknown } })?.response
  const corpo = resposta?.data
  if (corpo instanceof Blob) {
    try {
      const json = JSON.parse(await corpo.text())
      return mensagemDeErro({ response: { data: json } }, padrao)
    } catch {
      return padrao
    }
  }
  return mensagemDeErro(e, padrao)
}

// ---- Formulário: estado, conversão e validação espelhada ----

export interface FormularioDocumento {
  tipo: string
  numero: string
  /** Valor cru do input `type="date"`, já no formato `YYYY-MM-DD` que a API espera. */
  validade: string
  obrigatorio: boolean
  responsavelEnvio: string
}

export function formularioVazio(): FormularioDocumento {
  return { tipo: '', numero: '', validade: '', obrigatorio: false, responsavelEnvio: '' }
}

export interface ResultadoPayload {
  erro: string | null
  payload: DocumentoPayload | null
}

export function montarPayload(
  residenteId: string,
  form: FormularioDocumento,
): ResultadoPayload {
  if (!residenteId) return { erro: 'Selecione o residente.', payload: null }

  const tipo = form.tipo.trim()
  // Espelha `tipo: str` obrigatório e a coluna String(100) (models.py:121).
  if (!tipo) return { erro: 'Informe o tipo do documento.', payload: null }
  if (tipo.length > 100) return { erro: 'O tipo deve ter no máximo 100 caracteres.', payload: null }

  const numero = form.numero.trim()
  if (numero.length > 100) return { erro: 'O número deve ter no máximo 100 caracteres.', payload: null }

  const payload: DocumentoPayload = { residente_id: residenteId, tipo }
  if (numero) payload.numero = numero
  if (form.validade) payload.validade = form.validade
  // Só viaja quando marcado: o backend já assume `false` (models.py:133).
  if (form.obrigatorio) payload.obrigatorio = true
  const responsavel = form.responsavelEnvio.trim()
  if (responsavel) payload.responsavel_envio = responsavel

  return { erro: null, payload }
}

/** Rótulo curto de tamanho, para o cartão e para o modal de anexo. */
export function formatarTamanho(bytes?: number | null): string {
  if (bytes == null) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1).replace('.', ',')} MB`
}

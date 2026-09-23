import { useState } from 'react'
import type { Instituicao, InstituicaoPayload } from '../../types/platform'
import { montarPayload } from '../../services/platform'
import { UF_VALIDAS, cnpjEhValido } from '../../types/platform'

/**
 * Serve criação e edição. Só campos que InstituicaoCreate/InstituicaoUpdate
 * aceitam — `situacao` não aparece: nasce no servidor e só muda por
 * ativar/inativar.
 *
 * A validação aqui é a mínima para evitar ida inútil ao servidor. O backend
 * continua sendo a fonte de verdade: o payload vai como digitado e qualquer 422
 * dele é exibido pela página que hospeda este formulário.
 *
 * PH-01: CNPJ e UF continuam OPCIONAIS na criação — é o contrato de
 * `InstituicaoCreate` (schemas.py:96,99) e não é afrouxado nem endurecido aqui.
 * O que mudou é que a tela deixou de permitir dois valores que o servidor
 * rejeitaria de qualquer forma (UF fora das 27 siglas; CNPJ com dígito
 * verificador errado) e passou a avisar que ambos são exigidos na ATIVAÇÃO,
 * validada por `_validate_activation_fields` (fase3a.py:649) — dois passos
 * depois e em outra tela.
 */

type Campo = { nome: keyof InstituicaoPayload; rotulo: string; tipo?: 'text' | 'email' | 'uf' }

const CAMPOS_TEXTO: Campo[] = [
  { nome: 'nome_fantasia', rotulo: 'Nome fantasia' },
  { nome: 'cnpj', rotulo: 'CNPJ' },
  { nome: 'municipio', rotulo: 'Município' },
  { nome: 'uf', rotulo: 'UF', tipo: 'uf' },
  { nome: 'telefone', rotulo: 'Telefone' },
  { nome: 'email', rotulo: 'E-mail', tipo: 'email' },
  { nome: 'responsavel_legal', rotulo: 'Responsável legal' },
  { nome: 'responsavel_tecnico', rotulo: 'Responsável técnico' },
  { nome: 'endereco', rotulo: 'Endereço' },
  { nome: 'finalidade', rotulo: 'Finalidade' },
]

function estadoInicial(instituicao?: Instituicao | null): Record<string, string> {
  const base: Record<string, string> = {
    razao_social: '',
    capacidade: '',
  }
  for (const campo of CAMPOS_TEXTO) base[campo.nome as string] = ''
  if (!instituicao) return base
  for (const chave of Object.keys(base)) {
    const valor = (instituicao as unknown as Record<string, unknown>)[chave]
    base[chave] = valor === null || valor === undefined ? '' : String(valor)
  }
  return base
}

/** Erros por campo. Objeto vazio = formulário liberado para envio. */
function validar(form: Record<string, string>): Record<string, string> {
  const erros: Record<string, string> = {}
  if (form.razao_social.trim().length < 2) {
    erros.razao_social = 'Informe a razão social (mínimo 2 caracteres).'
  }
  // O backend recusa capacidade ausente ou <= 0 na criação (CAPACIDADE_REQUIRED).
  const capacidade = Number(form.capacidade)
  if (!form.capacidade.trim() || Number.isNaN(capacidade) || capacidade <= 0) {
    erros.capacidade = 'Informe uma capacidade maior que zero.'
  }
  // Opcional: só validamos o que foi preenchido. Vazio segue como ausência,
  // que `InstituicaoCreate` aceita.
  if (form.cnpj.trim() && !cnpjEhValido(form.cnpj)) {
    erros.cnpj = 'CNPJ inválido. Confira os 14 dígitos — o dígito verificador não confere.'
  }
  return erros
}

export function InstituicaoForm({
  instituicao,
  onSubmit,
  submitLabel,
  disabled,
}: {
  instituicao?: Instituicao | null
  onSubmit: (payload: InstituicaoPayload) => Promise<void>
  submitLabel: string
  disabled?: boolean
}) {
  const [form, setForm] = useState(() => estadoInicial(instituicao))
  const [erros, setErros] = useState<Record<string, string>>({})
  const [enviando, setEnviando] = useState(false)

  function set(chave: string, valor: string) {
    setForm(atual => ({ ...atual, [chave]: valor }))
    // Corrigir um campo apaga o erro dele, não o dos outros.
    setErros(atual => {
      if (!atual[chave]) return atual
      const proximo = { ...atual }
      delete proximo[chave]
      return proximo
    })
  }

  async function handle(e: React.FormEvent) {
    e.preventDefault()
    const encontrados = validar(form)
    setErros(encontrados)
    if (Object.keys(encontrados).length > 0) return
    setEnviando(true)
    try {
      await onSubmit(montarPayload(form))
    } finally {
      setEnviando(false)
    }
  }

  const ocupado = enviando || disabled

  /** Liga o campo à sua mensagem para leitor de tela. */
  function aria(nome: string) {
    return erros[nome]
      ? { 'aria-invalid': true as const, 'aria-describedby': 'erro_' + nome }
      : {}
  }

  function Erro({ nome }: { nome: string }) {
    if (!erros[nome]) return null
    return (
      <p id={'erro_' + nome} role="alert" className="mt-1 text-xs text-danger">
        {erros[nome]}
      </p>
    )
  }

  return (
    <form onSubmit={handle} noValidate className="card space-y-4">
      <div>
        <label htmlFor="razao_social" className="block text-sm font-medium mb-1">
          Razão social <span aria-hidden="true">*</span>
        </label>
        <input
          id="razao_social"
          className="input"
          value={form.razao_social}
          onChange={e => set('razao_social', e.target.value)}
          {...aria('razao_social')}
        />
        <Erro nome="razao_social" />
      </div>

      <div>
        <label htmlFor="capacidade" className="block text-sm font-medium mb-1">
          Capacidade <span aria-hidden="true">*</span>
        </label>
        <input
          id="capacidade"
          className="input"
          type="number"
          min={1}
          value={form.capacidade}
          onChange={e => set('capacidade', e.target.value)}
          {...aria('capacidade')}
        />
        <Erro nome="capacidade" />
      </div>

      {/* A exigência não é da criação, é da ativação. Dizer isso aqui evita que
          o operador só descubra ao clicar em "Ativar", duas telas adiante. */}
      <p className="text-sm p-3 rounded-xl bg-primaryLight/50 border border-primaryLight text-primaryDeep">
        <strong>CNPJ</strong> e <strong>UF</strong> são opcionais para criar a instituição, mas
        <strong> obrigatórios para ativá-la</strong>. Sem eles a ILPI permanece em configuração e a
        equipe não consegue operar.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {CAMPOS_TEXTO.map(campo => {
          const nome = campo.nome as string
          return (
            <div key={nome}>
              <label htmlFor={nome} className="block text-sm font-medium mb-1">
                {campo.rotulo}
              </label>
              {campo.tipo === 'uf' ? (
                <select
                  id={nome}
                  className="input"
                  value={form[nome]}
                  onChange={e => set(nome, e.target.value)}
                  {...aria(nome)}
                >
                  <option value="">Selecione…</option>
                  {UF_VALIDAS.map(sigla => (
                    <option key={sigla} value={sigla}>{sigla}</option>
                  ))}
                </select>
              ) : (
                <input
                  id={nome}
                  className="input"
                  type={campo.tipo || 'text'}
                  inputMode={nome === 'cnpj' ? 'numeric' : undefined}
                  value={form[nome]}
                  onChange={e => set(nome, e.target.value)}
                  {...aria(nome)}
                />
              )}
              <Erro nome={nome} />
            </div>
          )
        })}
      </div>

      <button disabled={ocupado} className="btn-primary w-full disabled:opacity-60 min-h-[44px]">
        {enviando ? 'Salvando...' : submitLabel}
      </button>
    </form>
  )
}

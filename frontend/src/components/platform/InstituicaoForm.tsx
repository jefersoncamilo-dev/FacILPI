import { useState } from 'react'
import type { Instituicao, InstituicaoPayload } from '../../types/platform'
import { montarPayload } from '../../services/platform'

/**
 * Serve criação e edição. Só campos que InstituicaoCreate/InstituicaoUpdate
 * aceitam — `situacao` não aparece: nasce no servidor e só muda por
 * ativar/inativar.
 *
 * A validação aqui é a mínima para evitar ida inútil ao servidor. CNPJ, UF e
 * demais regras continuam sendo decididas pelo backend, que é a fonte de
 * verdade; a tela apenas exibe o que ele responder.
 */

const CAMPOS_TEXTO: Array<{ nome: keyof InstituicaoPayload; rotulo: string; tipo?: string }> = [
  { nome: 'nome_fantasia', rotulo: 'Nome fantasia' },
  { nome: 'cnpj', rotulo: 'CNPJ' },
  { nome: 'municipio', rotulo: 'Município' },
  { nome: 'uf', rotulo: 'UF' },
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
  const [erro, setErro] = useState('')
  const [enviando, setEnviando] = useState(false)

  function set(chave: string, valor: string) {
    setForm(atual => ({ ...atual, [chave]: valor }))
  }

  async function handle(e: React.FormEvent) {
    e.preventDefault()
    setErro('')
    if (form.razao_social.trim().length < 2) {
      setErro('Informe a razão social.')
      return
    }
    // O backend recusa capacidade ausente ou <= 0 na criação (CAPACIDADE_REQUIRED).
    const capacidade = Number(form.capacidade)
    if (!form.capacidade.trim() || Number.isNaN(capacidade) || capacidade <= 0) {
      setErro('Informe uma capacidade maior que zero.')
      return
    }
    setEnviando(true)
    try {
      await onSubmit(montarPayload(form))
    } finally {
      setEnviando(false)
    }
  }

  const ocupado = enviando || disabled

  return (
    <form onSubmit={handle} className="card space-y-4">
      <div>
        <label htmlFor="razao_social" className="block text-sm font-medium mb-1">
          Razão social <span aria-hidden="true">*</span>
        </label>
        <input
          id="razao_social"
          className="input"
          value={form.razao_social}
          onChange={e => set('razao_social', e.target.value)}
          required
        />
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
          required
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {CAMPOS_TEXTO.map(campo => (
          <div key={campo.nome as string}>
            <label htmlFor={campo.nome as string} className="block text-sm font-medium mb-1">
              {campo.rotulo}
            </label>
            <input
              id={campo.nome as string}
              className="input"
              type={campo.tipo || 'text'}
              value={form[campo.nome as string]}
              onChange={e => set(campo.nome as string, e.target.value)}
            />
          </div>
        ))}
      </div>

      {erro && (
        <div role="alert" className="text-sm p-3 rounded-xl bg-amber-50 text-amber-800 border border-amber-200">
          {erro}
        </div>
      )}

      <button disabled={ocupado} className="btn-primary w-full disabled:opacity-60 min-h-[44px]">
        {enviando ? 'Salvando...' : submitLabel}
      </button>
    </form>
  )
}

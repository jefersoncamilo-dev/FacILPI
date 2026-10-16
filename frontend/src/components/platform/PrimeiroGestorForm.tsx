import { useState } from 'react'
import type { PrimeiroGestorPayload } from '../../types/platform'

/**
 * Cadastro do primeiro gestor da ILPI — sempre um TERCEIRO. O operador da
 * plataforma não vira administrador institucional: quem decide isso é o
 * backend, que cria usuário, funcionário e vínculo apontando para esta pessoa.
 *
 * Só os campos que PlatformPrimeiroGestorCreate aceita. `perfil_id` não existe
 * aqui de propósito: o perfil é sempre o clone local de `ilpi_admin` da própria
 * ILPI, escolhido pelo servidor.
 */
export function PrimeiroGestorForm({
  onSubmit,
  disabled,
}: {
  onSubmit: (payload: PrimeiroGestorPayload) => Promise<void>
  disabled?: boolean
}) {
  const [nome, setNome] = useState('')
  const [email, setEmail] = useState('')
  const [cpf, setCpf] = useState('')
  const [telefone, setTelefone] = useState('')
  const [cargo, setCargo] = useState('')
  const [erro, setErro] = useState('')
  const [enviando, setEnviando] = useState(false)

  async function handle(e: React.FormEvent) {
    e.preventDefault()
    setErro('')
    if (nome.trim().length < 2) {
      setErro('Informe o nome do gestor.')
      return
    }
    if (!email.trim()) {
      setErro('Informe o e-mail do gestor.')
      return
    }
    setEnviando(true)
    try {
      const payload: PrimeiroGestorPayload = { nome: nome.trim(), email: email.trim() }
      if (cpf.trim()) payload.cpf = cpf.trim()
      if (telefone.trim()) payload.telefone = telefone.trim()
      if (cargo.trim()) payload.cargo = cargo.trim()
      await onSubmit(payload)
      setNome('')
      setEmail('')
      setCpf('')
      setTelefone('')
      setCargo('')
    } finally {
      setEnviando(false)
    }
  }

  return (
    <form onSubmit={handle} className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label htmlFor="gestor_nome" className="block text-sm font-medium mb-1">
            Nome <span aria-hidden="true">*</span>
          </label>
          <input id="gestor_nome" className="input" value={nome} onChange={e => setNome(e.target.value)} required />
        </div>
        <div>
          <label htmlFor="gestor_email" className="block text-sm font-medium mb-1">
            E-mail <span aria-hidden="true">*</span>
          </label>
          <input id="gestor_email" className="input" type="email" value={email} onChange={e => setEmail(e.target.value)} required />
        </div>
        <div>
          <label htmlFor="gestor_cpf" className="block text-sm font-medium mb-1">CPF</label>
          <input id="gestor_cpf" className="input" value={cpf} onChange={e => setCpf(e.target.value)} />
        </div>
        <div>
          <label htmlFor="gestor_telefone" className="block text-sm font-medium mb-1">Telefone</label>
          <input id="gestor_telefone" className="input" value={telefone} onChange={e => setTelefone(e.target.value)} />
        </div>
        <div className="sm:col-span-2">
          <label htmlFor="gestor_cargo" className="block text-sm font-medium mb-1">Cargo</label>
          <input
            id="gestor_cargo"
            className="input"
            placeholder="Administrador da ILPI"
            value={cargo}
            onChange={e => setCargo(e.target.value)}
          />
        </div>
      </div>

      <p className="text-xs text-textMuted">
        O gestor receberá uma senha temporária e será obrigado a trocá-la no primeiro acesso.
      </p>

      {erro && (
        <div role="alert" className="text-sm p-3 rounded-xl bg-orange-50 text-orange-800 border border-orange-200">
          {erro}
        </div>
      )}

      <button disabled={enviando || disabled} className="btn-primary w-full disabled:opacity-60 min-h-[44px]">
        {enviando ? 'Cadastrando...' : 'Cadastrar primeiro gestor'}
      </button>
    </form>
  )
}

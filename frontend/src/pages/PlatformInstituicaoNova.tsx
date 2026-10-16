import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { InstituicaoForm } from '../components/platform/InstituicaoForm'
import { criarInstituicao } from '../services/platform'
import { mensagemDeErro } from '../services/api'
import type { InstituicaoPayload } from '../types/platform'

export function PlatformInstituicaoNova() {
  const [erro, setErro] = useState('')
  const navigate = useNavigate()

  async function handle(payload: InstituicaoPayload) {
    setErro('')
    try {
      const criada = await criarInstituicao(payload)
      // Segue direto para o detalhe: é lá que o provisionamento continua, com o
      // cadastro do primeiro gestor e a ativação.
      navigate(`/platform/instituicoes/${criada.id}`)
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível criar a instituição.'))
    }
  }

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">Nova ILPI</h1>
        <Link to="/platform/instituicoes" className="ml-auto text-sm text-primary hover:underline">
          Voltar
        </Link>
      </div>

      <p className="text-sm text-textMuted">
        A instituição nasce em configuração. Depois de cadastrar o primeiro gestor, ela poderá ser
        ativada.
      </p>

      {erro && (
        <div role="alert" className="text-sm p-3 rounded-xl bg-orange-50 text-orange-800 border border-orange-200">
          {erro}
        </div>
      )}

      <InstituicaoForm onSubmit={handle} submitLabel="Criar instituição" />
    </div>
  )
}

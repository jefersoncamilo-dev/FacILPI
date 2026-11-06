import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api, formatDate } from '../../services/api'
import { Alert } from '../ui/feedback'

export interface TransicaoClinica {
  afeta_esta_sessao: boolean
  prazo?: string | null
  em_carencia: boolean
  perfil_clinico_atribuido: boolean
  escritas_retiradas: string[]
}

/**
 * #15 (D3 = opção B): o administrador da ILPI deixa de registrar fatos clínicos.
 * Durante os 30 dias de transição ainda registra; depois, só lê. O aviso pede
 * para atribuir um perfil clínico (Enfermagem, RT, Cuidador…) a alguém da equipe.
 * Só informa: quem decide o acesso é o backend.
 */
export function AvisoTransicaoClinica({ podeAtribuir }: { podeAtribuir: boolean }) {
  const [dados, setDados] = useState<TransicaoClinica | null>(null)

  useEffect(() => {
    let vigente = true
    void (async () => {
      try {
        const { data } = await api.get<TransicaoClinica>('/transicao-clinica/')
        if (vigente) setDados(data)
      } catch {
        // Aviso auxiliar: sem resposta, nada a mostrar.
      }
    })()
    return () => { vigente = false }
  }, [])

  if (!dados?.afeta_esta_sessao) return null
  if (dados.perfil_clinico_atribuido && !dados.em_carencia) return null

  const prazo = dados.prazo ? formatDate(dados.prazo) : null
  const acao = podeAtribuir && (
    <Link to="/equipe" className="font-medium underline">Atribuir perfil na Equipe</Link>
  )

  if (dados.em_carencia) {
    return (
      <Alert variant="warning" title="O administrador vai deixar de registrar dados clínicos">
        {prazo ? `Até ${prazo}` : 'Por enquanto'}, este perfil ainda registra cuidados, sinais vitais, avaliações,
        intercorrências e PAIS. Depois, continua vendo tudo, mas o registro fica com os perfis clínicos.{' '}
        {dados.perfil_clinico_atribuido
          ? 'A equipe já tem perfil clínico atribuído.'
          : 'Atribua um perfil clínico (Enfermagem, Responsável Técnico ou Cuidador) a alguém da equipe.'}{' '}
        {acao}
      </Alert>
    )
  }
  return (
    <Alert variant="warning" title="Registro clínico bloqueado para o administrador">
      Este perfil continua vendo residentes, prontuário, Dashboard e Alertas, mas não registra dados clínicos.
      Ninguém na ILPI tem perfil clínico: atribua Enfermagem, Responsável Técnico ou Cuidador a alguém da equipe.{' '}
      {acao}
    </Alert>
  )
}

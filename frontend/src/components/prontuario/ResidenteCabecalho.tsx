import { formatDate } from '../../services/api'

// GET /api/residentes/{id} (backend/src/application/schemas.py:424-431) não
// retorna quarto/leito — omitido aqui de propósito, sem buscar outro endpoint.
export interface ResidenteResumo {
  id: string
  nome: string
  situacao?: string | null
  data_nascimento?: string | null
  sexo?: string | null
}

export function ResidenteCabecalho({ residente }: { residente: ResidenteResumo | null }) {
  if (!residente) {
    return <div className="card p-4 lg:p-6 h-24 animate-pulse" aria-hidden="true" />
  }
  return (
    <div className="card p-4 lg:p-6 lg:sticky lg:top-4">
      <div className="flex items-center gap-3 lg:flex-col lg:items-start lg:gap-2">
        <div className="w-12 h-12 rounded-full bg-primaryLight flex items-center justify-center font-bold text-primary text-lg shrink-0">
          {residente.nome.charAt(0).toUpperCase()}
        </div>
        <div className="min-w-0">
          <h1 className="text-lg lg:text-xl font-bold text-textMain truncate">{residente.nome}</h1>
          <p className="text-sm text-textMuted">
            {residente.situacao || '—'} · {formatDate(residente.data_nascimento)} · {residente.sexo || '—'}
          </p>
        </div>
      </div>
    </div>
  )
}

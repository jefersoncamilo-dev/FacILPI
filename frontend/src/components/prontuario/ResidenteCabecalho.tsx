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
        {/* Inicial é decorativa: repete a primeira letra do nome logo ao lado. */}
        <div
          aria-hidden="true"
          className="w-12 h-12 rounded-full bg-primaryLight flex items-center justify-center font-bold text-primary text-lg shrink-0"
        >
          {residente.nome.charAt(0).toUpperCase()}
        </div>
        {/* lg:self-stretch: em lg o container vira flex-col com items-start, e sem isso este
            filho dimensiona pelo conteúdo — o min-w-0 não constrange, o h1 cresce e transborda
            o card em vez de truncar. */}
        <div className="min-w-0 lg:self-stretch">
          {/* Trunca só a partir de lg, onde a coluna lateral é fixa em 280px; abaixo disso o
              cabeçalho ocupa a largura toda e o nome pode quebrar em quantas linhas forem
              necessárias. O title
              cobre o caso truncado, já que em desktop existe hover. */}
          <h1 className="text-lg lg:text-xl font-bold text-textMain lg:truncate" title={residente.nome}>{residente.nome}</h1>
          <p className="text-sm text-textMuted">
            {residente.situacao || '—'} · {formatDate(residente.data_nascimento)} · {residente.sexo || '—'}
          </p>
        </div>
      </div>
    </div>
  )
}

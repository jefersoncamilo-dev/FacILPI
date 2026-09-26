import { TriangleAlert } from 'lucide-react'
import { formatDate } from '../../services/api'
import { idade, type ContextoResidente } from '../../hooks/useContextoResidente'
import { Badge } from '../ui/feedback'

// GET /api/residentes/{id} não traz leito, ausência nem grau oficial: esses vêm
// de useContextoResidente (cada um da sua fonte, só com permissão). O campo
// `grau_dependencia` do residente é legado congelado e não é exibido aqui.
export interface ResidenteResumo {
  id: string
  nome: string
  nome_social?: string | null
  situacao?: string | null
  data_nascimento?: string | null
  data_admissao?: string | null
  sexo?: string | null
  alergias?: string | null
  restricoes?: string | null
  necessidades_especiais?: string | null
}

const SEM_CONTEXTO: ContextoResidente = { leito: undefined, ausencia: undefined, grau: undefined }

export function ResidenteCabecalho({
  residente,
  contexto = SEM_CONTEXTO,
}: {
  residente: ResidenteResumo | null
  contexto?: ContextoResidente
}) {
  if (!residente) {
    return <div className="card h-24 animate-pulse p-4 lg:p-6" aria-hidden="true" />
  }
  const anos = idade(residente.data_nascimento)
  const alertas = [
    ['Alergias', residente.alergias],
    ['Restrições', residente.restricoes],
    ['Necessidades especiais', residente.necessidades_especiais],
  ].filter(([, valor]) => valor && String(valor).trim()) as [string, string][]

  return (
    <div className="card space-y-4 p-4 lg:sticky lg:top-20 lg:p-6">
      <div className="flex items-center gap-3 lg:flex-col lg:items-start lg:gap-2">
        {/* Inicial é decorativa: repete a primeira letra do nome logo ao lado. */}
        <div
          aria-hidden="true"
          className="flex size-12 shrink-0 items-center justify-center rounded-full bg-brand-soft text-lg font-bold text-primary"
        >
          {residente.nome.charAt(0).toUpperCase()}
        </div>
        {/* lg:self-stretch: em lg o container vira flex-col com items-start, e sem isso este
            filho dimensiona pelo conteúdo — o min-w-0 não constrange, o h1 cresce e transborda
            o card em vez de truncar. */}
        <div className="min-w-0 lg:self-stretch">
          {/* Trunca só a partir de lg, onde a coluna lateral é fixa em 280px; abaixo disso o
              cabeçalho ocupa a largura toda e o nome pode quebrar em quantas linhas forem
              necessárias. O title cobre o caso truncado, já que em desktop existe hover. */}
          <h1 className="text-lg font-bold text-foreground lg:truncate lg:text-xl" title={residente.nome}>{residente.nome}</h1>
          {residente.nome_social && <p className="text-sm text-muted-foreground">Nome social: {residente.nome_social}</p>}
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <Badge variant={residente.situacao === 'Ativo' ? 'success' : 'brand'}>{residente.situacao || 'Sem situação'}</Badge>
            {contexto.ausencia && (
              <Badge variant="warning">
                {contexto.ausencia.tipo === 'hospitalizacao' ? 'Hospitalizado(a)' : 'Saída temporária'} desde {formatDate(contexto.ausencia.desde)}
              </Badge>
            )}
          </div>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm lg:grid-cols-1">
        <div>
          <dt className="text-xs text-muted-foreground">Idade</dt>
          <dd className="font-medium text-foreground">
            {anos !== null ? `${anos} anos` : '—'} <span className="font-normal text-muted-foreground">· {formatDate(residente.data_nascimento)}</span>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Admissão</dt>
          <dd className="font-medium text-foreground">{residente.data_admissao ? formatDate(residente.data_admissao) : 'Em andamento'}</dd>
        </div>
        {contexto.leito !== undefined && (
          <div>
            <dt className="text-xs text-muted-foreground">Leito</dt>
            <dd className="font-medium text-foreground">{contexto.leito ?? 'Sem leito atribuído'}</dd>
          </div>
        )}
        {contexto.grau !== undefined && (
          <div>
            <dt className="text-xs text-muted-foreground">Grau de dependência</dt>
            <dd className="font-medium text-foreground">{contexto.grau?.classificacao ?? 'Não definido'}</dd>
          </div>
        )}
        <div>
          <dt className="text-xs text-muted-foreground">Sexo</dt>
          <dd className="font-medium text-foreground">{residente.sexo || '—'}</dd>
        </div>
      </dl>

      {alertas.length > 0 && (
        <div className="space-y-2 rounded-lg border border-red-100 bg-red-50 p-3">
          {alertas.map(([rotulo, valor]) => (
            <p key={rotulo} className="flex gap-2 text-sm text-red-800">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <span><strong className="font-semibold">{rotulo}:</strong> {valor}</span>
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

import type { ReactNode } from 'react'
import { BedDouble, CalendarDays, Gauge, TriangleAlert, UserRound } from 'lucide-react'
import { formatDate } from '../../services/api'
import { idade, type ContextoResidente } from '../../hooks/useContextoResidente'
import { Badge } from '../ui/feedback'
import { AvatarResidente } from '../residente/AvatarResidente'
import { rotuloSituacaoResidente } from '../../lib/rotulos'
import { cn } from '../../lib/utils'
import { SELO_GRAU, SELO_SEM_GRAU, ehGrau, grauDaApi } from '../../lib/grau'

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
  foto?: string | null
}

const SEM_CONTEXTO: ContextoResidente = { leito: undefined, ausencia: undefined, grau: undefined }

/**
 * UX-NAV-3: cabeçalho da ficha em faixa no topo (protótipo, board 3).
 * Foto grande; identificação; grau de dependência em destaque; acomodação e
 * datas em blocos curtos; cuidados de atenção (alergias, restrições,
 * necessidades) numa faixa própria. A ação "Registrar" vem do chamador.
 */
export function ResidenteCabecalho({
  residente,
  contexto = SEM_CONTEXTO,
  acoes,
}: {
  residente: ResidenteResumo | null
  contexto?: ContextoResidente
  acoes?: ReactNode
}) {
  if (!residente) {
    return <div className="card h-40 animate-pulse p-4 lg:p-6" aria-hidden="true" />
  }
  const anos = idade(residente.data_nascimento)
  const alertas = [
    ['Alergias', residente.alergias],
    ['Restrições', residente.restricoes],
    ['Necessidades especiais', residente.necessidades_especiais],
  ].filter(([, valor]) => valor && String(valor).trim()) as [string, string][]
  const grau = contexto.grau
  // UX-GRAU: undefined = sem permissão/consulta (sem círculo); null = sem grau ativo.
  const grauTela = grau === undefined ? undefined : grauDaApi(grau?.classificacao ?? null)

  return (
    <section aria-label="Identificação do residente" className="card min-w-0 space-y-4 p-4 lg:p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        {/* Foto (ou iniciais) grande: ajuda a reconhecer a pessoa. Decorativa, o nome está ao lado. */}
        <AvatarResidente nome={residente.nome} foto={residente.foto} grau={grauTela} className="size-24 text-3xl sm:size-28" />

        <div className="min-w-0 flex-1 space-y-3">
          <div className="min-w-0">
            <h1 className="font-display text-titulo-tela text-brand-ink wrap-break-word" title={residente.nome}>{residente.nome}</h1>
            {residente.nome_social && <p className="text-sm text-muted-foreground">Nome social: {residente.nome_social}</p>}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {/* Grau de dependência em destaque: é a prioridade de atenção da equipe. */}
              {grau !== undefined && (
                <span className={cn('inline-flex min-h-[36px] items-center gap-2 rounded-full border px-3 text-sm font-semibold', ehGrau(grauTela) ? SELO_GRAU[grauTela] : SELO_SEM_GRAU)}>
                  <Gauge className="size-4" aria-hidden="true" />
                  <span>Grau de dependência: {grau?.classificacao ?? 'Não definido'}</span>
                  {grau?.validade && <span className="font-normal">· válido até {formatDate(grau.validade)}</span>}
                </span>
              )}
              <Badge variant={residente.situacao === 'Ativo' ? 'success' : 'brand'}>{residente.situacao ? rotuloSituacaoResidente(residente.situacao) : 'Sem situação'}</Badge>
              {contexto.ausencia && (
                <Badge variant="warning">
                  {contexto.ausencia.tipo === 'hospitalizacao' ? 'Hospitalizado(a)' : 'Saída temporária'} desde {formatDate(contexto.ausencia.desde)}
                </Badge>
              )}
            </div>
          </div>

          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm md:grid-cols-4">
            <Info icone={UserRound} rotulo="Idade">
              {anos !== null ? `${anos} anos` : '—'} <span className="font-normal text-muted-foreground">· {formatDate(residente.data_nascimento)}</span>
            </Info>
            {contexto.leito !== undefined && (
              <Info icone={BedDouble} rotulo="Leito">{contexto.leito ?? 'Sem leito atribuído'}</Info>
            )}
            <Info icone={CalendarDays} rotulo="Admissão">{residente.data_admissao ? formatDate(residente.data_admissao) : 'Em andamento'}</Info>
            <Info icone={UserRound} rotulo="Sexo">{residente.sexo || '—'}</Info>
          </dl>
        </div>

        {acoes && <div className="flex shrink-0 flex-col gap-2 sm:items-end">{acoes}</div>}
      </div>

      {alertas.length > 0 && (
        <div className="grid gap-2 rounded-lg border border-critico/20 bg-critico-soft p-3 md:grid-cols-3">
          {alertas.map(([rotulo, valor]) => (
            <p key={rotulo} className="flex gap-2 text-sm text-critico-texto">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <span><strong className="font-semibold">{rotulo}:</strong> {valor}</span>
            </p>
          ))}
        </div>
      )}
    </section>
  )
}

function Info({ icone: Icone, rotulo, children }: { icone: typeof UserRound; rotulo: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1.5 text-xs text-muted-foreground"><Icone className="size-3.5" aria-hidden="true" />{rotulo}</dt>
      <dd className="font-medium text-foreground">{children}</dd>
    </div>
  )
}

import { AlarmClock, Check, TriangleAlert } from 'lucide-react'
import { cn } from '../../lib/utils'
import { rotuloDoItem, type PlantaoItem } from '../../services/plantao'
import { estaAtrasado, tempoDeAtraso } from './visoes'
import { AvatarResidente } from '../residente/AvatarResidente'
import { SeloGrau } from '../residente/SeloGrau'
import { grauDaApi } from '../../lib/grau'

const HORA = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' })
const DIA = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit' })

function mesmoDia(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

/** UX-GRAU G3b: no botão, o verbo; o nome acessível continua completo ("Registrar administração"). */
function rotuloVisivel(rotulo: string) {
  return rotulo.startsWith('Registrar') ? 'Registrar' : rotulo
}

/**
 * Card da fila do plantão (UX-GRAU G3b):
 *   hora  o que fazer (linha inteira, sem disputar espaço com o botão)
 *   foto  residente                            | Registrar
 *   (o)   [Grau] atrasado há … · quarto/leito  |
 * A foto leva o círculo na cor do grau; o atraso aparece em texto, com ícone
 * (não só cor), em laranja, para não se confundir com o vermelho do Grau III.
 */
export function ItemPlantao({
  item,
  nomeResidente,
  fotoResidente,
  agora,
  acao,
  selecao,
}: {
  item: PlantaoItem
  nomeResidente?: string
  fotoResidente?: string | null
  agora: number
  acao?: { rotulo: string; onClick: () => void }
  /** UX-01B: em modo seleção o card troca o Registrar por uma caixa de marcação. */
  selecao?: { selecionado: boolean; onAlternar: () => void }
}) {
  const atrasado = estaAtrasado(item, agora)
  const previsto = item.previsto_em ? new Date(item.previsto_em) : null
  const residente = nomeResidente || item.residente_id
  const cuidado = rotuloDoItem(item)
  const quando = previsto ? `${DIA.format(previsto)} ${HORA.format(previsto)}` : 'sem horário'
  const grau = grauDaApi(item.grau)
  const visivel = acao ? rotuloVisivel(acao.rotulo) : ''

  return (
    <div
      className={cn(
        'glass rounded-card px-3 py-2.5',
        selecao?.selecionado ? 'border-primary ring-2 ring-primary/30' : atrasado && 'border-l-4 border-l-alerta',
      )}
    >
      {/* Linha 1: quando e o que fazer. */}
      <div className="flex min-w-0 items-baseline gap-2">
        {previsto ? (
          <span className={cn('shrink-0 text-base font-semibold tabular-nums', atrasado ? 'text-alerta-forte' : 'text-foreground')}>
            {HORA.format(previsto)}
            {!mesmoDia(previsto, new Date(agora)) && <span className="ml-1 text-xs font-normal text-muted-foreground">{DIA.format(previsto)}</span>}
          </span>
        ) : (
          <span className="inline-flex shrink-0 self-center text-alerta-forte">
            <TriangleAlert className="size-4" aria-hidden="true" /><span className="sr-only">Sem horário</span>
          </span>
        )}
        <span className="line-clamp-2 min-w-0 font-semibold leading-snug text-foreground">{cuidado}</span>
      </div>

      {/* Linha 2: quem, grau, onde/atraso e a ação. */}
      <div className="mt-1.5 flex items-center gap-2.5">
        {selecao && (
          <button
            type="button"
            role="checkbox"
            aria-checked={selecao.selecionado}
            aria-label={`${cuidado} — ${residente}, ${quando}`}
            onClick={selecao.onAlternar}
            data-selecao-plantao={`${item.origem}:${item.registro_id}`}
            className="-m-1 flex size-11 shrink-0 items-center justify-center rounded-lg"
          >
            <span className={cn(
              'flex size-6 items-center justify-center rounded-md border-2',
              selecao.selecionado ? 'border-primary bg-primary text-primary-foreground' : 'border-input bg-card',
            )}>
              {selecao.selecionado && <Check className="size-4" aria-hidden="true" />}
            </span>
          </button>
        )}
        <AvatarResidente nome={residente} foto={fotoResidente} grau={grau} className="m-1 size-10 text-sm" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-foreground">{residente}</div>
          <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
            <SeloGrau classificacao={grau} semGrau />
            <span className="min-w-0 truncate">
            {atrasado && (
              <span className="mr-1 inline-flex items-center gap-0.5 font-semibold text-alerta-forte">
                <AlarmClock className="size-3" aria-hidden="true" />
                atrasado {tempoDeAtraso(item.previsto_em!, agora)}
                {item.local && <span aria-hidden="true"> ·</span>}
              </span>
            )}
            {item.local}
            </span>
          </div>
        </div>

        {acao && !selecao && (
          <button
            data-acao-plantao={`${item.origem}:${item.registro_id}`}
            onClick={acao.onClick}
            aria-label={visivel !== acao.rotulo ? acao.rotulo : undefined}
            className="btn-primary min-h-[48px] shrink-0 px-4 text-sm"
          >
            {visivel}
          </button>
        )}
      </div>
    </div>
  )
}

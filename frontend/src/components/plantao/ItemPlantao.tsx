import { Check, Clock, MapPin, TriangleAlert } from 'lucide-react'
import { cn } from '../../lib/utils'
import { rotuloDoItem, type PlantaoItem } from '../../services/plantao'
import { estaAtrasado, tempoDeAtraso } from './visoes'

const HORA = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' })
const DIA = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit' })

function mesmoDia(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

/**
 * UX-01A.2 — card da fila: horário · cuidado · residente · quarto/leito ·
 * situação · Registrar. A situação é texto + ícone (não só cor). `destaque`
 * escolhe a linha principal: o cuidado (padrão) ou o residente — no
 * agrupamento por cuidado o título do grupo já diz o cuidado.
 */
export function ItemPlantao({
  item,
  nomeResidente,
  agora,
  destaque = 'cuidado',
  acao,
  selecao,
}: {
  item: PlantaoItem
  nomeResidente?: string
  agora: number
  destaque?: 'cuidado' | 'residente'
  acao?: { rotulo: string; onClick: () => void }
  /** UX-01B: em modo seleção o card troca o Registrar por uma caixa de marcação. */
  selecao?: { selecionado: boolean; onAlternar: () => void }
}) {
  const atrasado = estaAtrasado(item, agora)
  const previsto = item.previsto_em ? new Date(item.previsto_em) : null
  const residente = nomeResidente || item.residente_id
  const cuidado = rotuloDoItem(item)
  const [principal, secundario] = destaque === 'residente' ? [residente, cuidado] : [cuidado, residente]

  const quando = previsto ? `${DIA.format(previsto)} ${HORA.format(previsto)}` : 'sem horário'

  return (
    <div
      className={cn(
        'flex items-center gap-3 rounded-card border bg-card p-3 shadow-sm sm:gap-4 sm:p-4',
        selecao?.selecionado ? 'border-primary ring-2 ring-primary/30' : atrasado ? 'border-orange-300' : 'border-border',
      )}
    >
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
            selecao.selecionado ? 'border-primary bg-primary text-primary-foreground' : 'border-slate-400 bg-card',
          )}>
            {selecao.selecionado && <Check className="size-4" aria-hidden="true" />}
          </span>
        </button>
      )}
      <div className="w-14 shrink-0 text-center" aria-hidden={!previsto}>
        {previsto ? (
          <>
            <div className={cn('text-lg font-bold tabular-nums leading-tight', atrasado ? 'text-orange-800' : 'text-foreground')}>
              {HORA.format(previsto)}
            </div>
            {!mesmoDia(previsto, new Date(agora)) && <div className="text-xs text-muted-foreground">{DIA.format(previsto)}</div>}
          </>
        ) : (
          <TriangleAlert className="mx-auto size-6 text-orange-700" />
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="line-clamp-2 font-semibold leading-snug text-foreground">{principal}</div>
        <div className="mt-0.5 truncate text-sm text-muted-foreground">{secundario}</div>
        {item.local && (
          <div className="mt-0.5 flex items-start gap-1 text-sm leading-snug text-muted-foreground">
            <MapPin className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" /> <span className="min-w-0 break-words">{item.local}</span>
          </div>
        )}
        <div className="mt-1.5">
          {atrasado ? (
            <span className="badge-warning inline-flex whitespace-nowrap"><Clock className="size-3" aria-hidden="true" /> Atrasado {tempoDeAtraso(item.previsto_em!, agora)}</span>
          ) : previsto ? (
            <span className="text-xs font-medium text-muted-foreground">Pendente</span>
          ) : (
            <span className="text-xs font-medium text-orange-800">Aberta, sem horário</span>
          )}
        </div>
      </div>

      {acao && !selecao && (
        <button
          data-acao-plantao={`${item.origem}:${item.registro_id}`}
          onClick={acao.onClick}
          className="btn-primary min-h-[48px] shrink-0 px-4 text-sm"
        >
          {acao.rotulo}
        </button>
      )}
    </div>
  )
}

import { Check, Clock, MapPin, TriangleAlert } from 'lucide-react'
import { cn } from '../../lib/utils'
import { rotuloDoItem, type PlantaoItem } from '../../services/plantao'
import { estaAtrasado, tempoDeAtraso } from './visoes'
import { AvatarResidente } from '../residente/AvatarResidente'

const HORA = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' })
const DIA = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit' })

function mesmoDia(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

/**
 * UX-01A.2/C — card compacto da fila: foto (ou iniciais) · cuidado · residente ·
 * quarto/leito · horário e situação · Registrar. A situação é texto + ícone
 * (não só cor); o horário é secundário, mas sempre visível. `destaque`
 * escolhe a linha principal: o cuidado (padrão) ou o residente — no
 * agrupamento por cuidado o título do grupo já diz o cuidado.
 */
export function ItemPlantao({
  item,
  nomeResidente,
  fotoResidente,
  agora,
  destaque = 'cuidado',
  acao,
  selecao,
}: {
  item: PlantaoItem
  nomeResidente?: string
  fotoResidente?: string | null
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
        'flex items-center gap-2.5 rounded-card border bg-card px-3 py-2.5 shadow-sm',
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
      <AvatarResidente nome={residente} foto={fotoResidente} className="size-9 text-xs" />

      <div className="min-w-0 flex-1">
        <div className="line-clamp-2 font-semibold leading-snug text-foreground">{principal}</div>
        <div className="line-clamp-2 text-sm leading-snug text-muted-foreground">
          {secundario}
          {item.local && <> · <MapPin className="inline size-3.5 -translate-y-px" aria-hidden="true" /> {item.local}</>}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm">
          {previsto ? (
            <span className={cn('inline-flex items-center gap-1 tabular-nums', atrasado ? 'font-semibold text-orange-800' : 'text-muted-foreground')}>
              {/* Atrasado: o selo ao lado já diz; sem o ícone, horário + selo cabem numa linha em 360px. */}
              {!atrasado && <Clock className="size-3.5" aria-hidden="true" />}
              {HORA.format(previsto)}{!mesmoDia(previsto, new Date(agora)) && ` · ${DIA.format(previsto)}`}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 font-medium text-orange-800">
              <TriangleAlert className="size-3.5" aria-hidden="true" /> Aberta, sem horário
            </span>
          )}
          {atrasado && (
            <span className="badge-warning inline-flex whitespace-nowrap">Atrasado {tempoDeAtraso(item.previsto_em!, agora)}</span>
          )}
        </div>
      </div>

      {acao && !selecao && (
        <button
          data-acao-plantao={`${item.origem}:${item.registro_id}`}
          onClick={acao.onClick}
          className="btn-primary min-h-[48px] shrink-0 px-3 text-sm sm:px-4"
        >
          {acao.rotulo}
        </button>
      )}
    </div>
  )
}

import { AlarmClock, Check, TriangleAlert } from 'lucide-react'
import { cn } from '../../lib/utils'
import { rotuloDoItem, type PlantaoItem } from '../../services/plantao'
import { estaAtrasado, tempoDeAtraso } from './visoes'
import { AvatarResidente } from '../residente/AvatarResidente'
import { SeloGrau } from '../residente/SeloGrau'

const HORA = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' })
const DIA = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit' })

function mesmoDia(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

/**
 * Card compacto da fila do plantão (UX-01A.2/C):
 *   foto (ou iniciais) | residente                     | Registrar
 *                      | quarto/leito (bem pequeno)    |
 *                      | hora programada  cuidado      |
 * A hora é pequena e secundária; atraso = hora em laranja + ícone de alarme
 * (não só cor). Registrar continua o CTA principal (48px).
 */
export function ItemPlantao({
  item,
  nomeResidente,
  fotoResidente,
  grau,
  agora,
  acao,
  selecao,
}: {
  item: PlantaoItem
  nomeResidente?: string
  fotoResidente?: string | null
  /** Grau de dependência ativo ('Grau I' | 'Grau II' | 'Grau III'); só vem para quem pode lê-lo. */
  grau?: string | null
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

  return (
    <div
      className={cn(
        'flex items-center gap-2 rounded-card border bg-card px-2.5 py-2.5 shadow-sm',
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
      <AvatarResidente nome={residente} foto={fotoResidente} className="size-11 text-base" />

      {/* Linha 1: residente - leito. Linha 2: hora programada (pequena) - cuidado.
          Atraso = hora em laranja + ícone de alarme (não só cor); o tempo de atraso fica para leitor de tela. */}
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="truncate font-semibold leading-snug text-foreground">{residente}</span>
          <SeloGrau classificacao={grau} />
        </div>
        {item.local && <div className="truncate text-[11px] leading-tight text-muted-foreground">{item.local}</div>}
        <div className="mt-0.5 flex min-w-0 items-baseline gap-1 whitespace-nowrap text-xs leading-snug">
          {previsto ? (
            <span className={cn('inline-flex shrink-0 items-center gap-0.5 text-xs tabular-nums', atrasado ? 'font-semibold text-orange-800' : 'text-muted-foreground')}>
              {atrasado && <AlarmClock className="size-3 self-center" aria-hidden="true" />}
              {HORA.format(previsto)}
              {!mesmoDia(previsto, new Date(agora)) && ` ${DIA.format(previsto)}`}
              {atrasado && <span className="sr-only"> — atrasado {tempoDeAtraso(item.previsto_em!, agora)}</span>}
            </span>
          ) : (
            <span className="inline-flex shrink-0 items-center text-orange-800">
              <TriangleAlert className="size-3.5 self-center" aria-hidden="true" /><span className="sr-only">Sem horário</span>
            </span>
          )}
          <span className="min-w-0 truncate text-muted-foreground">{cuidado}</span>
        </div>
      </div>

      {acao && !selecao && (
        <button
          data-acao-plantao={`${item.origem}:${item.registro_id}`}
          onClick={acao.onClick}
          className="btn-primary min-h-[48px] shrink-0 px-2.5 text-sm sm:px-4"
        >
          {acao.rotulo}
        </button>
      )}
    </div>
  )
}

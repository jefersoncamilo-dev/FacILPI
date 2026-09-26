import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { cn } from '../../lib/utils'
import { Skeleton } from './feedback'

/**
 * Indicador do Dashboard. `valor` é sempre o que a fonte oficial devolveu;
 * indisponível é "—" com texto explicando — nunca zero.
 */
export function MetricCard({
  icon: Icon,
  titulo,
  valor,
  detalhe,
  acao,
  atencao = false,
  carregando = false,
}: {
  icon: LucideIcon
  titulo: string
  valor: ReactNode
  detalhe?: ReactNode
  acao?: ReactNode
  /** Destaque discreto quando há algo a tratar (ex.: intercorrência aberta). */
  atencao?: boolean
  carregando?: boolean
}) {
  return (
    <div
      className={cn(
        'flex flex-col rounded-card border bg-card p-4 shadow-card sm:p-5',
        atencao ? 'border-amber-200 bg-amber-50/40' : 'border-border',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-muted-foreground">{titulo}</p>
        <span
          className={cn(
            'inline-flex size-9 shrink-0 items-center justify-center rounded-lg',
            atencao ? 'bg-amber-100 text-amber-800' : 'bg-brand-soft text-primary',
          )}
        >
          <Icon className="size-[18px]" aria-hidden="true" />
        </span>
      </div>
      {carregando ? (
        <div className="mt-2 space-y-2" aria-hidden="true">
          <Skeleton className="h-8 w-16" />
          <Skeleton className="h-3 w-28" />
        </div>
      ) : (
        <>
          <p className="mt-1 font-display text-3xl font-bold tracking-tight text-foreground">{valor}</p>
          {detalhe && <div className="mt-1 text-xs text-muted-foreground">{detalhe}</div>}
          {acao && <div className="mt-auto pt-3 text-xs font-semibold">{acao}</div>}
        </>
      )}
    </div>
  )
}

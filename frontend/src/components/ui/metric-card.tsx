import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { cn } from '../../lib/utils'
import { Skeleton } from './feedback'

/**
 * Tom do indicador (UX-11 / #101): o cartão é sempre branco; quem carrega o
 * status é o número e o ícone. Verde = normal/cadastros; laranja = há algo a
 * tratar; vermelho = crítico. Os tons de texto passam AA sobre branco.
 */
export type TomIndicador = 'normal' | 'alerta' | 'critico' | 'neutro'

const TONS: Record<TomIndicador, { icone: string; valor: string }> = {
  normal: { icone: 'bg-brand-soft text-brand-strong', valor: 'text-primary' },
  alerta: { icone: 'bg-alerta-soft text-alerta', valor: 'text-alerta-forte' },
  critico: { icone: 'bg-critico-soft text-critico', valor: 'text-critico-texto' },
  neutro: { icone: 'bg-muted text-muted-foreground', valor: 'text-foreground' },
}

const BORDA: Record<TomIndicador, string> = {
  normal: 'border-t-primary',
  alerta: 'border-t-alerta',
  critico: 'border-t-critico',
  neutro: 'border-t-border',
}

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
  visual,
  tom = 'normal',
  carregando = false,
  estado,
  animar = false,
  atraso = 0,
}: {
  icon: LucideIcon
  titulo: string
  valor: ReactNode
  detalhe?: ReactNode
  acao?: ReactNode
  /** Micro-visualização do próprio dado (barra, mini-barras); nunca decorativa. */
  visual?: ReactNode
  tom?: TomIndicador
  carregando?: boolean
  /**
   * UX-DASH-1: estado dito em texto e ícone, com a cor do tom na borda
   * superior — a cor nunca fala sozinha.
   */
  estado?: { texto: string; icone: LucideIcon }
  /** Entrada animada (só na primeira abertura) e o atraso dela na sequência. */
  animar?: boolean
  atraso?: number
}) {
  const cores = TONS[tom]
  const Estado = estado?.icone
  return (
    <div data-tom={tom} style={animar ? { animationDelay: `${atraso}ms` } : undefined}
      className={cn('flex flex-col glass rounded-card p-4 transition duration-150 hover:-translate-y-0.5 hover:shadow-cardHover motion-reduce:transition-none motion-reduce:hover:translate-y-0 sm:p-5',
        estado && cn('border-t-4', BORDA[tom]), animar && 'animar-entrada')}>
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-muted-foreground">{titulo}</p>
        <span className={cn('inline-flex size-9 shrink-0 items-center justify-center rounded-lg', cores.icone)}>
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
          <p className={cn('mt-1 font-display text-3xl font-bold tracking-tight', cores.valor)}>{valor}</p>
          {estado && Estado && (
            <p className={cn('mt-1 inline-flex items-center gap-1 text-xs font-semibold', cores.valor)}>
              <Estado className="size-3.5" aria-hidden="true" />{estado.texto}
            </p>
          )}
          {visual && <div className="mt-3">{visual}</div>}
          {detalhe && <div className="mt-1.5 text-xs text-muted-foreground">{detalhe}</div>}
          {acao && <div className="mt-auto pt-3 text-xs font-semibold">{acao}</div>}
        </>
      )}
    </div>
  )
}

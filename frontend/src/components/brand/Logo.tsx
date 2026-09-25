import { HeartHandshake } from 'lucide-react'
import { cn } from '../../lib/utils'

/** Símbolo FacILPI: cuidado (mãos + coração) sobre o esmeralda da marca. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand to-primary text-white shadow-sm',
        className,
      )}
    >
      <HeartHandshake className="size-[58%]" strokeWidth={2} />
    </span>
  )
}

export function Logo({
  className,
  inverted = false,
  subtitle,
}: {
  className?: string
  inverted?: boolean
  subtitle?: string
}) {
  return (
    <span className={cn('inline-flex items-center gap-3', className)}>
      <LogoMark className={inverted ? 'from-white/25 to-white/10 ring-1 ring-white/30' : undefined} />
      <span className="min-w-0 text-left">
        <span className={cn('block font-display text-lg font-bold leading-none tracking-tight', inverted ? 'text-white' : 'text-foreground')}>
          Fac<span className={inverted ? 'text-emerald-200' : 'text-brand-strong'}>ILPI</span>
        </span>
        {subtitle && (
          <span className={cn('mt-1 block truncate text-xs', inverted ? 'text-emerald-50/80' : 'text-muted-foreground')}>{subtitle}</span>
        )}
      </span>
    </span>
  )
}

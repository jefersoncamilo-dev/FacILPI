import type { HTMLAttributes, ReactNode } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { AlertCircle, CheckCircle2, Info, TriangleAlert, type LucideIcon } from 'lucide-react'
import { cn } from '../../lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold leading-none',
  {
    variants: {
      variant: {
        neutral: 'border-border bg-muted text-muted-foreground',
        brand: 'border-brand/30 bg-brand-soft text-accent-foreground',
        success: 'border-brand/30 bg-accent text-primary',
        warning: 'border-alerta/30 bg-alerta-soft text-alerta-forte',
        danger: 'border-critico/30 bg-critico-soft text-critico-texto',
      },
    },
    defaultVariants: { variant: 'neutral' },
  },
)

export function Badge({
  className,
  variant,
  ...props
}: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

const alertStyles = {
  info: { box: 'border-info/30 bg-info-soft text-info', icon: Info },
  success: { box: 'border-brand/30 bg-accent text-brand-ink', icon: CheckCircle2 },
  warning: { box: 'border-alerta/30 bg-alerta-soft text-alerta-forte', icon: TriangleAlert },
  error: { box: 'border-critico/30 bg-critico-soft text-critico-texto', icon: AlertCircle },
} satisfies Record<string, { box: string; icon: LucideIcon }>

/**
 * Mensagem inline. Erro usa role="alert" (anunciado na hora); os demais usam
 * role="status". O ícone repete o sentido da cor: estado nunca só por cor.
 */
export function Alert({
  variant = 'info',
  title,
  children,
  className,
}: {
  variant?: keyof typeof alertStyles
  title?: string
  children?: ReactNode
  className?: string
}) {
  const { box, icon: Icon } = alertStyles[variant]
  return (
    <div
      role={variant === 'error' ? 'alert' : 'status'}
      className={cn('flex gap-3 rounded-lg border px-4 py-3 text-sm', box, className)}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 space-y-0.5">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div>{children}</div>}
      </div>
    </div>
  )
}

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden="true" className={cn('animate-pulse rounded-md bg-secondary/70', className)} {...props} />
}

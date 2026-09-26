import type { HTMLAttributes, ReactNode } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { AlertCircle, CheckCircle2, Info, TriangleAlert, type LucideIcon } from 'lucide-react'
import { cn } from '../../lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold leading-none',
  {
    variants: {
      variant: {
        neutral: 'border-border bg-muted text-slate-600',
        brand: 'border-emerald-200 bg-brand-soft text-accent-foreground',
        success: 'border-emerald-200 bg-emerald-50 text-emerald-800',
        warning: 'border-orange-200 bg-orange-50 text-orange-800',
        danger: 'border-red-200 bg-red-50 text-red-700',
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
  info: { box: 'border-sky-200 bg-sky-50 text-sky-900', icon: Info },
  success: { box: 'border-emerald-200 bg-emerald-50 text-emerald-900', icon: CheckCircle2 },
  warning: { box: 'border-orange-200 bg-orange-50 text-orange-900', icon: TriangleAlert },
  error: { box: 'border-red-200 bg-red-50 text-red-800', icon: AlertCircle },
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
  return <div aria-hidden="true" className={cn('animate-pulse rounded-md bg-slate-200/70', className)} {...props} />
}

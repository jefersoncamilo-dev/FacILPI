import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle, Loader2, type LucideIcon } from 'lucide-react'
import { Button } from './button'
import { cn } from '../../lib/utils'

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon: LucideIcon
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center rounded-card border border-dashed border-border bg-card px-6 py-14 text-center', className)}>
      <span className="mb-4 inline-flex size-12 items-center justify-center rounded-full bg-brand-soft text-primary">
        <Icon className="size-6" aria-hidden="true" />
      </span>
      <p className="font-display text-base font-semibold text-foreground">{title}</p>
      {description && <div className="mt-2 max-w-md text-sm text-muted-foreground">{description}</div>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  )
}

export function ErrorState({
  title = 'Algo deu errado',
  description = 'Não foi possível exibir esta tela. Tente novamente; se continuar, avise o administrador da ILPI.',
  onRetry,
  retryLabel = 'Tentar novamente',
}: {
  title?: string
  description?: ReactNode
  onRetry?: () => void
  retryLabel?: string
}) {
  return (
    <div role="alert" className="flex flex-col items-center rounded-card border border-red-200 bg-card px-6 py-14 text-center">
      <span className="mb-4 inline-flex size-12 items-center justify-center rounded-full bg-red-50 text-red-700">
        <AlertTriangle className="size-6" aria-hidden="true" />
      </span>
      <p className="font-display text-base font-semibold text-foreground">{title}</p>
      <div className="mt-2 max-w-md text-sm text-muted-foreground">{description}</div>
      {onRetry && (
        <Button variant="outline" className="mt-6" onClick={onRetry}>
          {retryLabel}
        </Button>
      )}
    </div>
  )
}

export function LoadingState({ label = 'Carregando…', className }: { label?: string; className?: string }) {
  return (
    <div role="status" className={cn('flex items-center justify-center gap-3 py-16 text-sm text-muted-foreground', className)}>
      <Loader2 className="size-5 animate-spin text-brand-strong" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

/**
 * Error boundary (Issue #32): um erro de render deixa de desmontar a
 * aplicação inteira. Dentro do AppShell, a navegação continua de pé e só a
 * área de conteúdo mostra o erro. `resetKey` limpa o erro ao trocar de rota.
 */
export class ErrorBoundary extends Component<
  { children: ReactNode; resetKey?: string; fallback?: (reset: () => void) => ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Sem dados de tela no log: só a pilha técnica, para diagnóstico.
    console.error('Erro de renderização capturado', error, info.componentStack)
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null })
    }
  }

  reset = () => this.setState({ error: null })

  render() {
    if (!this.state.error) return this.props.children
    if (this.props.fallback) return this.props.fallback(this.reset)
    return <ErrorState onRetry={this.reset} />
  }
}

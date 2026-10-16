import { Building2, ChevronRight, Globe } from 'lucide-react'
import type { ContextOption } from '../types/context'

/** Seleção explícita de contexto. Opções sempre originadas do backend. */
export function ContextPicker({ options, onPick, disabled }: {
  options: ContextOption[]
  onPick: (opt: ContextOption) => void
  disabled?: boolean
}) {
  return (
    <ul className="space-y-2">
      {options.map(o => {
        const global = o.scope === 'global'
        const Icon = global ? Globe : Building2
        return (
          <li key={o.key}>
            <button
              onClick={() => onPick(o)}
              disabled={disabled}
              className="flex min-h-[56px] w-full items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 text-left transition-colors hover:border-brand/60 hover:bg-accent disabled:opacity-60"
            >
              <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-primary">
                <Icon className="size-5" aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-foreground">{global ? 'Plataforma' : o.label}</span>
                <span className="block truncate text-xs text-muted-foreground">
                  {global ? 'Visão administrativa da plataforma' : o.sublabel}
                </span>
              </span>
              <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            </button>
          </li>
        )
      })}
    </ul>
  )
}

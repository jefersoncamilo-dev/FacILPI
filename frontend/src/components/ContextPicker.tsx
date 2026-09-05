import type { ContextOption } from '../types/context'

/** Seleção explícita de contexto. Opções sempre originadas do backend. */
export function ContextPicker({ options, onPick, disabled }: {
  options: ContextOption[]
  onPick: (opt: ContextOption) => void
  disabled?: boolean
}) {
  return (
    <div className="space-y-2">
      {options.map(o => (
        <button key={o.key} onClick={() => onPick(o)} disabled={disabled}
          className="w-full text-left px-4 py-3 rounded-xl border border-slate-200 hover:bg-slate-50 min-h-[44px] disabled:opacity-60">
          <div className="text-sm font-semibold text-textMain">{o.scope === 'global' ? '🌐 Plataforma' : `🏠 ${o.label}`}</div>
          <div className="text-xs text-textMuted">{o.scope === 'global' ? 'Visão administrativa da plataforma' : o.sublabel}</div>
        </button>
      ))}
    </div>
  )
}

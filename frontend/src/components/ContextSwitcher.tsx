import { useState } from 'react'
import { ArrowLeftRight, Building2, Check, Globe, Lock } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { cn } from '../lib/utils'
import { Modal } from './Modal'

export function contextTitle(ctx: { scope: string; ilpiNome?: string | null } | null): string {
  if (ctx?.scope === 'ilpi') return ctx.ilpiNome || 'ILPI'
  return 'Plataforma'
}

export function contextSubtitle(ctx: { scope: string; perfilNome?: string | null } | null): string {
  if (ctx?.scope === 'ilpi') return ctx.perfilNome || 'Equipe da ILPI'
  return 'Superusuário'
}

/** Seletor visível do contexto ativo. Opções e IDs vêm do backend; nada é fabricado. */
export function ContextSwitcher({ compact = false }: { compact?: boolean }) {
  const { activeContext, availableContexts, switching, switchContext, contextError, clearContextError, requiresPasswordChange } = useAuth()
  const [open, setOpen] = useState(false)
  const [errOpen, setErrOpen] = useState(false)

  // Troca pendente: seletor bloqueado até a definição da nova senha.
  if (requiresPasswordChange) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-orange-200 bg-orange-50 px-3 py-2.5 text-xs text-orange-800">
        <Lock className="size-4 shrink-0" aria-hidden="true" /> Defina sua nova senha para escolher o contexto.
      </div>
    )
  }

  const showPicker = availableContexts.length > 1
  const Icone = activeContext?.scope === 'ilpi' ? Building2 : Globe

  async function pick(key: string) {
    const opt = availableContexts.find(o => o.key === key)
    if (!opt) return
    setOpen(false)
    try {
      await switchContext(opt)
    } catch {
      setErrOpen(true)
    }
  }

  return (
    <div className="min-w-0">
      <button
        onClick={() => showPicker && setOpen(true)}
        disabled={!showPicker || switching}
        aria-label="Contexto atual"
        title={showPicker ? 'Trocar de contexto' : 'Contexto atual'}
        className={cn(
          'flex min-h-[44px] items-center gap-2.5 rounded-lg border border-border bg-card text-left transition-colors enabled:hover:bg-muted disabled:cursor-default',
          compact ? 'max-w-[280px] px-2.5 py-1.5' : 'w-full px-3 py-2.5',
        )}
      >
        <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-md bg-brand-soft text-primary">
          <Icone className="size-4" aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold text-foreground">
            {switching ? 'Trocando...' : contextTitle(activeContext)}
          </span>
          <span className="block truncate text-xs text-muted-foreground">{contextSubtitle(activeContext)}</span>
        </span>
        {showPicker && <ArrowLeftRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />}
      </button>

      <Modal open={open} onClose={() => setOpen(false)} title="Trocar de contexto">
        <div className="space-y-2">
          {availableContexts.map(o => {
            const isActive = (o.scope === 'ilpi') === (activeContext?.scope === 'ilpi') &&
              (o.ilpi_id ?? null) === (activeContext?.ilpi_id ?? null)
            return (
              <button
                key={o.key}
                onClick={() => pick(o.key)}
                disabled={switching || isActive}
                className={cn(
                  'flex min-h-[44px] w-full items-center justify-between gap-3 rounded-lg border px-4 py-3 text-left',
                  isActive ? 'border-brand bg-accent' : 'border-border hover:bg-muted',
                )}
              >
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-foreground">{o.label}</span>
                  <span className="block text-xs text-muted-foreground">{o.sublabel}</span>
                </span>
                {isActive && (
                  <span className="flex items-center gap-1 text-xs font-semibold text-primary">
                    <Check className="size-4" aria-hidden="true" /> Atual
                  </span>
                )}
              </button>
            )
          })}
        </div>
      </Modal>

      <Modal open={errOpen} onClose={() => { setErrOpen(false); clearContextError() }} title="Não foi possível trocar">
        <p className="text-sm text-foreground">{contextError || 'Contexto não autorizado para este usuário.'}</p>
        <button onClick={() => { setErrOpen(false); clearContextError() }} className="btn-primary mt-4 w-full">Fechar</button>
      </Modal>
    </div>
  )
}

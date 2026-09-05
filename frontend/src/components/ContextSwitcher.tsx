import { useState } from 'react'
import { useAuth } from '../context/AuthContext'
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
      <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-800">
        🔒 Defina sua nova senha para escolher o contexto.
      </div>
    )
  }

  const showPicker = availableContexts.length > 1

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
    <div>
      <button
        onClick={() => showPicker && setOpen(true)}
        disabled={!showPicker || switching}
        aria-label="Contexto atual"
        title={showPicker ? 'Trocar de contexto' : 'Contexto atual'}
        className={`${compact ? 'px-3 h-11' : 'w-full px-3 py-2.5'} rounded-xl border border-slate-200 bg-slate-50 hover:bg-slate-100 flex items-center gap-2 text-left min-h-[44px] disabled:opacity-80`}
      >
        <span className="w-8 h-8 rounded-lg bg-primary text-white flex items-center justify-center text-sm shrink-0">
          {activeContext?.scope === 'ilpi' ? '🏠' : '🌐'}
        </span>
        <span className="flex-1 min-w-0">
          <span className="block text-sm font-semibold text-textMain truncate">
            {switching ? 'Trocando...' : contextTitle(activeContext)}
          </span>
          <span className="block text-xs text-textMuted truncate">{contextSubtitle(activeContext)}</span>
        </span>
        {showPicker && <span className="text-textMuted">⇄</span>}
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
                className={`w-full text-left px-4 py-3 rounded-xl border min-h-[44px] ${isActive ? 'border-primary bg-primaryLight/40' : 'border-slate-200 hover:bg-slate-50'}`}
              >
                <div className="text-sm font-semibold text-textMain">{o.label}{isActive ? ' ✓' : ''}</div>
                <div className="text-xs text-textMuted">{o.sublabel}</div>
              </button>
            )
          })}
        </div>
      </Modal>

      <Modal open={errOpen} onClose={() => { setErrOpen(false); clearContextError() }} title="Não foi possível trocar">
        <p className="text-sm text-textMain">{contextError || 'Contexto não autorizado para este usuário.'}</p>
        <button onClick={() => { setErrOpen(false); clearContextError() }} className="btn-primary w-full mt-4">Fechar</button>
      </Modal>
    </div>
  )
}

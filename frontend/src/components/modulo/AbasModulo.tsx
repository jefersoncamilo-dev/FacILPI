import { useRef, type KeyboardEvent } from 'react'
import { cn } from '../../lib/utils'

export interface Aba<T extends string = string> {
  id: T
  rotulo: string
}

/**
 * UX-NAV-0: abas de uma página de módulo (padrão ARIA tablist).
 *
 * Só a aba ativa entra no Tab; setas, Home e End movem o foco e já trocam a
 * aba (ativação automática). O painel é do chamador:
 * `role="tabpanel" id={idPainel(prefixo, aba)} aria-labelledby={idAba(prefixo, aba)}`.
 */
export const idAba = (prefixo: string, aba: string) => `${prefixo}-aba-${aba}`
export const idPainel = (prefixo: string, aba: string) => `${prefixo}-painel-${aba}`

export function AbasModulo<T extends string>({
  abas,
  ativa,
  onTrocar,
  rotulo,
  prefixo,
}: {
  abas: readonly Aba<T>[]
  ativa: T
  onTrocar: (aba: T) => void
  /** Nome do grupo de abas para leitor de tela. */
  rotulo: string
  /** Prefixo único dos ids de aba e painel. */
  prefixo: string
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])

  function teclar(e: KeyboardEvent<HTMLButtonElement>, n: number) {
    const ultimo = abas.length - 1
    const destino =
      e.key === 'ArrowRight' ? (n === ultimo ? 0 : n + 1)
      : e.key === 'ArrowLeft' ? (n === 0 ? ultimo : n - 1)
      : e.key === 'Home' ? 0
      : e.key === 'End' ? ultimo
      : null
    if (destino === null) return
    e.preventDefault()
    refs.current[destino]?.focus()
    onTrocar(abas[destino].id)
  }

  return (
    <div role="tablist" aria-label={rotulo} className="flex gap-1 overflow-x-auto border-b border-border">
      {abas.map((aba, n) => {
        const selecionada = aba.id === ativa
        return (
          <button
            key={aba.id}
            ref={el => { refs.current[n] = el }}
            type="button"
            role="tab"
            id={idAba(prefixo, aba.id)}
            aria-selected={selecionada}
            aria-controls={idPainel(prefixo, aba.id)}
            tabIndex={selecionada ? 0 : -1}
            onClick={() => onTrocar(aba.id)}
            onKeyDown={e => teclar(e, n)}
            className={cn(
              '-mb-px min-h-[44px] shrink-0 rounded-t-lg border-b-2 px-4 text-sm font-medium transition-colors motion-reduce:transition-none',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
              selecionada ? 'border-brand font-semibold text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {aba.rotulo}
          </button>
        )
      })}
    </div>
  )
}

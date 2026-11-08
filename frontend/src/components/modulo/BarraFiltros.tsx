import type { ReactNode } from 'react'
import { X } from 'lucide-react'

export interface ChipFiltro {
  chave: string
  /** Texto do chip, ex.: "Residente: Maria". */
  rotulo: string
  onRemover: () => void
}

/**
 * UX-NAV-0: filtros de uma página de módulo. Os controles vêm do chamador;
 * cada filtro ativo vira um chip removível, e "Limpar filtros" tira todos.
 * O estado mora na URL (`useFiltrosUrl`), não aqui.
 */
export function BarraFiltros({ children, chips, onLimpar }: { children: ReactNode; chips: ChipFiltro[]; onLimpar: () => void }) {
  return (
    <div className="space-y-2">
      <div className="card flex flex-col gap-3 p-3 sm:flex-row sm:items-center">{children}</div>
      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filtros ativos">
          {chips.map(chip => (
            <button
              key={chip.chave}
              type="button"
              onClick={chip.onRemover}
              aria-label={`Remover filtro ${chip.rotulo}`}
              className="inline-flex min-h-[44px] items-center gap-1.5 rounded-full bg-accent px-4 text-sm font-medium text-accent-foreground hover:bg-brand-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {chip.rotulo}
              <X className="size-4" aria-hidden="true" />
            </button>
          ))}
          <button
            type="button"
            onClick={onLimpar}
            className="min-h-[44px] rounded-lg px-2 text-sm font-semibold text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Limpar filtros
          </button>
        </div>
      )}
    </div>
  )
}

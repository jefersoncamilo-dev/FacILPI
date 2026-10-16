import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import type { ItemAtivo } from './navegacao'

/**
 * UX-00C: card de submódulo no hub. O card inteiro é o link — sem botão
 * "Abrir" repetido. Ícone + título + uma linha de descrição + seta.
 */
export function ModuleHubCard({ item }: { item: ItemAtivo }) {
  const Icone = item.icon
  return (
    <Link
      to={item.to}
      className="group flex min-h-[88px] items-center gap-4 rounded-card border border-border bg-card p-5 text-card-foreground shadow-card transition-shadow hover:border-brand/40 hover:shadow-cardHover"
    >
      <span className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-primary" aria-hidden="true">
        <Icone className="size-5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-display text-base font-semibold leading-tight text-foreground">{item.label}</span>
        <span className="mt-1 block text-sm text-muted-foreground">{item.descricao}</span>
      </span>
      <ChevronRight
        className="size-5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-foreground motion-reduce:transition-none"
        aria-hidden="true"
      />
    </Link>
  )
}

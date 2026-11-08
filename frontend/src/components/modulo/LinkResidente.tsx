import { Link } from 'react-router'
import { AvatarResidente } from '../residente/AvatarResidente'
import { cn } from '../../lib/utils'

/**
 * UX-NAV-0: o nome do residente em qualquer lista leva à ficha dele.
 * Sem nome conhecido (lista de residentes indisponível), mostra o
 * identificador — nunca inventa um nome.
 */
export function LinkResidente({
  id,
  nome,
  foto,
  detalhe,
  className,
}: {
  id: string
  nome?: string | null
  foto?: string | null
  /** Linha de apoio, ex.: data do registro. */
  detalhe?: string
  className?: string
}) {
  const texto = nome || id
  return (
    <Link
      to={`/residentes/${id}`}
      className={cn(
        'flex min-h-[44px] min-w-0 items-center gap-3 rounded-lg text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        className,
      )}
    >
      <AvatarResidente nome={texto} foto={foto} className="size-9 shrink-0" />
      <span className="min-w-0">
        <span className="block truncate font-semibold">{texto}</span>
        {detalhe && <span className="block text-xs text-muted-foreground">{detalhe}</span>}
      </span>
    </Link>
  )
}

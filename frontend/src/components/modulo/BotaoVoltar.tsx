import { useNavigate } from 'react-router'
import { ChevronLeft } from 'lucide-react'

/**
 * UX-NAV-0: volta para a tela de onde a pessoa veio. Sem histórico dentro do
 * app (link aberto direto, nova aba), vai para `fallback` — a lista ou o hub
 * do módulo. O BrowserRouter guarda a posição em `history.state.idx`.
 */
export function BotaoVoltar({ fallback, className }: { fallback: string; className?: string }) {
  const navigate = useNavigate()
  function voltar() {
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0
    if (idx > 0) navigate(-1)
    else navigate(fallback)
  }
  return (
    <button
      type="button"
      onClick={voltar}
      className={
        className ??
        'inline-flex min-h-[44px] items-center gap-1 rounded-lg pr-2 text-sm font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
      }
    >
      <ChevronLeft className="size-5" aria-hidden="true" />
      Voltar
    </button>
  )
}

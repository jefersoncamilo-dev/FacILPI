import { cn } from '../../lib/utils'

// Grau de dependência = prioridade de atenção: I verde, II amarelo, III vermelho.
// O texto ("Grau II") vai sempre junto, para não depender só da cor.
const ESTILO: Record<string, string> = {
  'Grau I': 'border-emerald-300 bg-emerald-100 text-emerald-900',
  'Grau II': 'border-yellow-300 bg-yellow-100 text-yellow-900',
  'Grau III': 'border-red-300 bg-red-100 text-red-800',
}

export function SeloGrau({ classificacao, className }: { classificacao?: string | null; className?: string }) {
  if (!classificacao || !ESTILO[classificacao]) return null
  return (
    <span
      className={cn('inline-flex shrink-0 items-center rounded-full border px-1.5 text-[11px] font-semibold leading-4', ESTILO[classificacao], className)}
      aria-label={`Grau de dependência ${classificacao.replace('Grau ', '')}`}
    >
      {classificacao}
    </span>
  )
}

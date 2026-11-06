import { cn } from '../../lib/utils'

// Grau de dependência = prioridade de atenção: I verde, II amarelo, III vermelho.
// O texto ("Grau II") vai sempre junto, para não depender só da cor.
const ESTILO: Record<string, string> = {
  'Grau I': 'border-brand/40 bg-accent text-brand-ink',
  'Grau II': 'border-alerta/40 bg-alerta-soft text-alerta-forte',
  'Grau III': 'border-critico/40 bg-critico-soft text-critico-texto',
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

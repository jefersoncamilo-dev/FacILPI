import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { destinoDoAlerta, haQuantoTempo, ROTULO_GRAVIDADE, type Alerta, type Gravidade } from '../../services/alertas'
import { cn } from '../../lib/utils'

// Classes completas: o Tailwind não enxerga nomes montados em tempo de execução.
export const ESTILO_GRAVIDADE: Record<Gravidade, { faixa: string; ficha: string; ponto: string }> = {
  critico: { faixa: 'bg-critico', ficha: 'border-red-200 bg-red-50 text-red-800', ponto: 'bg-critico' },
  atencao: { faixa: 'bg-alerta', ficha: 'border-orange-200 bg-orange-50 text-orange-800', ponto: 'bg-alerta' },
  aviso: { faixa: 'bg-slate-400', ficha: 'border-border bg-muted text-slate-700', ponto: 'bg-slate-400' },
}

/** Um alerta (#107): faixa de gravidade, o que houve e onde resolver. */
export function ItemAlerta({ alerta: a, compacto = false }: { alerta: Alerta; compacto?: boolean }) {
  const destino = destinoDoAlerta(a)
  const quando = haQuantoTempo(a.desde)
  const meta = [a.residente_nome, compacto ? null : a.detalhe, quando].filter(Boolean).join(' · ')
  return (
    <div className="relative flex items-stretch overflow-hidden rounded-card border border-border bg-card shadow-card">
      <span aria-hidden="true" className={cn('w-1.5 shrink-0', ESTILO_GRAVIDADE[a.gravidade].faixa)} />
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="font-medium text-foreground">
            <span className="sr-only">{ROTULO_GRAVIDADE[a.gravidade]}: </span>{a.titulo}
          </p>
          {meta && <p className="text-xs text-muted-foreground">{meta}</p>}
        </div>
        <Link
          to={destino.to}
          className="inline-flex min-h-[32px] shrink-0 items-center gap-1 text-sm font-semibold text-primary hover:underline"
        >
          Resolver em {destino.rotulo} <ArrowRight className="size-4" aria-hidden="true" />
        </Link>
      </div>
    </div>
  )
}


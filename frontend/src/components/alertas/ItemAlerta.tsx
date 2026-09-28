import { Link } from 'react-router-dom'
import { ArrowRight, MapPin } from 'lucide-react'
import { destinoDoAlerta, quandoDoAlerta, ROTULO_GRAVIDADE, ROTULO_NATUREZA, type Alerta, type Gravidade } from '../../services/alertas'
import { cn } from '../../lib/utils'

// Classes completas: o Tailwind não enxerga nomes montados em tempo de execução.
export const ESTILO_GRAVIDADE: Record<Gravidade, { faixa: string; ficha: string; ponto: string }> = {
  critico: { faixa: 'bg-critico', ficha: 'border-red-200 bg-red-50 text-red-800', ponto: 'bg-critico' },
  atencao: { faixa: 'bg-alerta', ficha: 'border-orange-200 bg-orange-50 text-orange-800', ponto: 'bg-alerta' },
  aviso: { faixa: 'bg-slate-400', ficha: 'border-border bg-muted text-slate-700', ponto: 'bg-slate-400' },
}

/**
 * Cartão de alerta (#107, #117). Responde, nesta ordem: o quê (título), com
 * quem (residente), onde (local), quando (prazo/origem) e o que fazer — a
 * ação leva ao módulo de origem, que é onde o alerta se resolve.
 */
export function ItemAlerta({ alerta: a, compacto = false, agora, fuso }: {
  alerta: Alerta; compacto?: boolean; agora?: Date; fuso?: string
}) {
  const destino = destinoDoAlerta(a)
  const quando = quandoDoAlerta(a, agora ?? new Date(), fuso)
  const meta = [ROTULO_NATUREZA[a.natureza], quando, compacto ? null : a.detalhe].filter(Boolean).join(' · ')
  return (
    <div className="relative flex items-stretch overflow-hidden rounded-card border border-border bg-card shadow-card">
      <span aria-hidden="true" className={cn('w-1.5 shrink-0', ESTILO_GRAVIDADE[a.gravidade].faixa)} />
      <div className="flex min-w-0 flex-1 flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-4">
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="font-medium text-foreground">
            <span className="sr-only">{ROTULO_GRAVIDADE[a.gravidade]}: </span>{a.titulo}
          </p>
          {(a.residente_nome || a.local) && (
            <p className="flex flex-wrap items-center gap-x-2 text-sm text-slate-700">
              {a.residente_nome && <span className="font-medium">{a.residente_nome}</span>}
              {a.local && (
                <span className="inline-flex items-center gap-1 text-muted-foreground">
                  <MapPin className="size-3.5" aria-hidden="true" />
                  <span className="sr-only">Local: </span>{a.local}
                </span>
              )}
            </p>
          )}
          {meta && <p className="text-xs text-muted-foreground">{meta}</p>}
        </div>
        <Link
          to={destino.to}
          aria-label={`${destino.acao} em ${destino.rotulo}`}
          className="inline-flex min-h-[44px] shrink-0 items-center justify-center gap-1 rounded-md bg-brand-soft px-3 text-sm font-semibold text-primary hover:underline sm:min-h-[36px]"
        >
          {destino.acao} <ArrowRight className="size-4" aria-hidden="true" />
        </Link>
      </div>
    </div>
  )
}

import { cn } from '../../lib/utils'

/**
 * Gráficos leves do Início (UX-11 / #101), sem biblioteca: SVG/CSS com os
 * tokens do design system. Regras:
 *  - todo gráfico tem `role="img"` e `aria-label` com os números;
 *  - a legenda visível sempre traz os valores — a cor nunca é a única leitura;
 *  - só dado de fonte oficial; nada de tendência sem histórico.
 */
export type Segmento = {
  rotulo: string
  valor: number
  /** Classe de fundo (barras e amostra da legenda), ex.: 'bg-primary'. */
  fundo: string
  /** Classe de traço para a rosca, ex.: 'stroke-primary'. */
  traco: string
}

const descrever = (segmentos: Segmento[]) => segmentos.map(s => `${s.rotulo}: ${s.valor}`).join(', ')

/** Percentual inteiro seguro (0 quando o total é 0). */
export function percentual(parte: number, total: number): number {
  return total > 0 ? Math.round((parte / total) * 100) : 0
}

/** Rosca (donut) com rótulo central. */
export function Rosca({ segmentos, centro, subcentro, titulo, tamanho = 136 }: {
  segmentos: Segmento[]; centro: string; subcentro?: string; titulo: string; tamanho?: number
}) {
  const total = segmentos.reduce((n, s) => n + s.valor, 0)
  const raio = 42
  const circ = 2 * Math.PI * raio
  let acumulado = 0
  return (
    <div className="relative shrink-0" style={{ width: tamanho, height: tamanho }}>
      <svg viewBox="0 0 100 100" role="img" aria-label={`${titulo}: ${descrever(segmentos)}`} className="size-full -rotate-90">
        <circle cx="50" cy="50" r={raio} fill="none" strokeWidth="12" className="stroke-slate-100" />
        {total > 0 && segmentos.filter(s => s.valor > 0).map(s => {
          const comprimento = (s.valor / total) * circ
          const arco = (
            <circle key={s.rotulo} cx="50" cy="50" r={raio} fill="none" strokeWidth="12" strokeLinecap="butt"
              strokeDasharray={`${comprimento} ${circ - comprimento}`} strokeDashoffset={-acumulado} className={s.traco} />
          )
          acumulado += comprimento
          return arco
        })}
      </svg>
      <div aria-hidden="true" className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-display text-2xl font-bold text-foreground">{centro}</span>
        {subcentro && <span className="text-[11px] text-muted-foreground">{subcentro}</span>}
      </div>
    </div>
  )
}

/** Barra horizontal empilhada. */
export function BarraSegmentada({ segmentos, titulo, className }: { segmentos: Segmento[]; titulo: string; className?: string }) {
  const total = segmentos.reduce((n, s) => n + s.valor, 0)
  return (
    <div role="img" aria-label={`${titulo}: ${descrever(segmentos)}`} className={cn('flex h-2.5 w-full overflow-hidden rounded-full bg-slate-100', className)}>
      {total > 0 && segmentos.filter(s => s.valor > 0).map(s => (
        <span key={s.rotulo} className={cn('h-full first:rounded-l-full last:rounded-r-full', s.fundo)} style={{ width: `${(s.valor / total) * 100}%` }} />
      ))}
    </div>
  )
}

/** Legenda com valores: `dt` (amostra + rótulo) seguido de `dd` (valor). */
export function Legenda({ segmentos, className }: { segmentos: Segmento[]; className?: string }) {
  return (
    <dl className={cn('grid gap-x-4 gap-y-1.5 text-sm', className)}>
      {segmentos.map(s => (
        <div key={s.rotulo} className="flex items-center justify-between gap-3">
          <dt className="flex min-w-0 items-center gap-2 text-muted-foreground">
            <span aria-hidden="true" className={cn('size-2.5 shrink-0 rounded-full', s.fundo)} />{s.rotulo}
          </dt>
          <dd className="font-semibold tabular-nums text-foreground">{s.valor}</dd>
        </div>
      ))}
    </dl>
  )
}

/** Mini-barras verticais (ex.: pendências por hora). */
export function MiniBarras({ valores, rotulos, titulo, destaque }: {
  valores: number[]; rotulos: string[]; titulo: string; destaque?: (valor: number, indice: number) => boolean
}) {
  const max = Math.max(1, ...valores)
  return (
    <div role="img" aria-label={`${titulo}: ${valores.map((v, i) => `${rotulos[i]} ${v}`).join(', ')}`} className="flex h-9 items-end gap-[3px]">
      {valores.map((v, i) => (
        <span key={i} title={`${rotulos[i]}: ${v}`}
          className={cn('min-h-[3px] flex-1 rounded-sm', v === 0 ? 'bg-slate-200' : destaque?.(v, i) ? 'bg-alerta' : 'bg-brand')}
          style={{ height: `${v === 0 ? 8 : Math.max(18, (v / max) * 100)}%` }} />
      ))}
    </div>
  )
}

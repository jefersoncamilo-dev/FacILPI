import { cn } from '../../lib/utils'

/**
 * Gráficos leves do Início (UX-11 / #101), sem biblioteca: SVG/CSS com os
 * tokens do design system. Regras:
 *  - todo gráfico tem `role="img"` e `aria-label` com os números;
 *  - a legenda visível sempre traz os valores — a cor nunca é a única leitura;
 *  - só dado de fonte oficial; tendência só com histórico vindo do backend.
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
        <circle cx="50" cy="50" r={raio} fill="none" strokeWidth="12" className="stroke-border" />
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
    <div role="img" aria-label={`${titulo}: ${descrever(segmentos)}`} className={cn('flex h-2.5 w-full overflow-hidden rounded-full bg-muted', className)}>
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

export type ColunaBarras = {
  /** Texto completo para leitores de tela e dica ao passar o mouse. */
  descricao: string
  /** Rótulo no eixo; vazio para aliviar eixos estreitos. */
  marca: string
  partes: { valor: number; fundo: string }[]
}

/** Barras verticais (#275), empilhadas quando a coluna tem mais de uma parte, com o total sobre cada uma. */
export function BarrasVerticais({ colunas, titulo, animar = false }: { colunas: ColunaBarras[]; titulo: string; animar?: boolean }) {
  const totalDe = (c: ColunaBarras) => c.partes.reduce((n, p) => n + p.valor, 0)
  const max = Math.max(1, ...colunas.map(totalDe))
  return (
    <div role="img" aria-label={`${titulo}: ${colunas.map(c => c.descricao).join('; ')}`} className="flex items-end gap-1">
      {colunas.map(c => {
        const total = totalDe(c)
        return (
          <div key={c.descricao} title={c.descricao} className="flex min-w-0 flex-1 flex-col items-center gap-1">
            <span className="text-[11px] font-semibold tabular-nums text-foreground">{total > 0 ? total : ''}</span>
            <div className="flex h-28 w-full flex-col justify-end gap-0.5 border-b border-border">
              {c.partes.filter(p => p.valor > 0).map(p => (
                <span key={p.fundo} className={cn('block w-full first:rounded-t', p.fundo, animar && 'animar-crescer-y')} style={{ height: `${(p.valor / max) * 100}%` }} />
              ))}
            </div>
            <span className="h-4 whitespace-nowrap text-[11px] tabular-nums text-muted-foreground">{c.marca}</span>
          </div>
        )
      })}
    </div>
  )
}

export type LinhaBarra = { rotulo: string; valor: number; fundo: string }

/**
 * Barras horizontais (UX-DASH-1): rótulo, barra e valor visível em cada linha —
 * a cor nunca é a única leitura. `title` dá a dica ao passar o mouse.
 */
export function BarrasHorizontais({ linhas, titulo, animar = false }: { linhas: LinhaBarra[]; titulo: string; animar?: boolean }) {
  const max = Math.max(1, ...linhas.map(l => l.valor))
  const numero = (n: number) => n.toLocaleString('pt-BR')
  return (
    <ul role="img" aria-label={`${titulo}: ${linhas.map(l => `${l.rotulo} ${numero(l.valor)}`).join(', ')}`} className="space-y-3">
      {linhas.map(l => (
        <li key={l.rotulo} title={`${l.rotulo}: ${numero(l.valor)}`} className="space-y-1">
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 truncate text-muted-foreground">{l.rotulo}</span>
            <span className="font-semibold tabular-nums text-foreground">{numero(l.valor)}</span>
          </div>
          <div className="h-2.5 w-full overflow-hidden rounded-full bg-muted">
            {l.valor > 0 && (
              <span className={cn('block h-full rounded-full', l.fundo, animar && 'animar-crescer-x')} style={{ width: `${(l.valor / max) * 100}%` }} />
            )}
          </div>
        </li>
      ))}
    </ul>
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
          className={cn('min-h-[3px] flex-1 rounded-sm', v === 0 ? 'bg-secondary' : destaque?.(v, i) ? 'bg-alerta' : 'bg-brand')}
          style={{ height: `${v === 0 ? 8 : Math.max(18, (v / max) * 100)}%` }} />
      ))}
    </div>
  )
}

/** Uma série da evolução: pontos já ordenados por data. */
export type SerieEvolucao = {
  rotulo: string
  pontos: { data: Date; valor: number }[]
  /** Classe de traço/preenchimento do token, ex.: 'stroke-brand' + 'fill-brand'. */
  traco: string
  ponto: string
  /** Codificação secundária (além da cor) para a segunda série. */
  tracejado?: boolean
}

const fmtNum = (v: number) => String(Math.round(v * 10) / 10).replace('.', ',')
const fmtData = (d: Date) => d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
const fmtDataHora = (d: Date) => d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })

/**
 * Evolução de uma medida no tempo (linha), um eixo só. Mostra valores e datas;
 * NÃO marca faixa "normal" nem julga o valor — não há referência clínica
 * cadastrada e essa leitura é da equipe. Cada ponto tem dica (title) com data e
 * valor; o rótulo direto fica no último ponto; com 2 séries há legenda.
 */
export function LinhaEvolucao({ titulo, unidade, series }: { titulo: string; unidade: string; series: SerieEvolucao[] }) {
  const L = 320, A = 150, esq = 36, dir = 44, topo = 12, base = 24
  const todos = series.flatMap(s => s.pontos)
  if (todos.length === 0) return null
  const tMin = Math.min(...todos.map(p => p.data.getTime()))
  const tMax = Math.max(...todos.map(p => p.data.getTime()))
  let vMin = Math.min(...todos.map(p => p.valor))
  let vMax = Math.max(...todos.map(p => p.valor))
  const folga = vMax === vMin ? Math.max(1, Math.abs(vMax) * 0.05) : (vMax - vMin) * 0.15
  vMin -= folga
  vMax += folga
  const x = (t: number) => (tMax === tMin ? (esq + L - dir) / 2 : esq + ((t - tMin) / (tMax - tMin)) * (L - esq - dir))
  const y = (v: number) => topo + (1 - (v - vMin) / (vMax - vMin)) * (A - topo - base)
  const grade = [vMin + folga, (vMin + vMax) / 2, vMax - folga]
  const ultimo = (s: SerieEvolucao) => s.pontos[s.pontos.length - 1]
  const resumo = series
    .map(s => `${s.rotulo}: ${s.pontos.length} registros, de ${fmtNum(Math.min(...s.pontos.map(p => p.valor)))} a ${fmtNum(Math.max(...s.pontos.map(p => p.valor)))} ${unidade}; último ${fmtNum(ultimo(s).valor)} ${unidade} em ${fmtDataHora(ultimo(s).data)}`)
    .join('. ')

  return (
    <figure className="min-w-0">
      <svg viewBox={`0 0 ${L} ${A}`} role="img" aria-label={`${titulo}. ${resumo}`} className="h-auto w-full overflow-visible">
        {grade.map(v => (
          <g key={v}>
            <line x1={esq} x2={L - dir} y1={y(v)} y2={y(v)} className="stroke-border" strokeWidth="1" />
            <text x={esq - 6} y={y(v) + 4} textAnchor="end" className="fill-muted-foreground text-[10px]">{fmtNum(v)}</text>
          </g>
        ))}
        <text x={esq} y={A - 6} className="fill-muted-foreground text-[10px]">{fmtData(new Date(tMin))}</text>
        {tMax !== tMin && <text x={L - dir} y={A - 6} textAnchor="end" className="fill-muted-foreground text-[10px]">{fmtData(new Date(tMax))}</text>}
        {series.map(s => (
          <g key={s.rotulo}>
            {s.pontos.length > 1 && (
              <polyline
                fill="none"
                strokeWidth="2"
                strokeLinejoin="round"
                strokeLinecap="round"
                strokeDasharray={s.tracejado ? '6 4' : undefined}
                className={s.traco}
                points={s.pontos.map(p => `${x(p.data.getTime())},${y(p.valor)}`).join(' ')}
              />
            )}
            {s.pontos.map(p => (
              <circle key={p.data.getTime()} cx={x(p.data.getTime())} cy={y(p.valor)} r="4" strokeWidth="2" className={cn('stroke-card', s.ponto)}>
                <title>{`${s.rotulo}: ${fmtNum(p.valor)} ${unidade} — ${fmtDataHora(p.data)}`}</title>
              </circle>
            ))}
            {/* Rótulo direto só no último ponto: o valor mais recente. */}
            <text x={x(ultimo(s).data.getTime()) + 8} y={y(ultimo(s).valor) + 4} className="fill-foreground text-[11px] font-semibold">
              {fmtNum(ultimo(s).valor)}
            </text>
          </g>
        ))}
      </svg>
      {series.length > 1 && (
        <figcaption className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {series.map(s => (
            <span key={s.rotulo} className="inline-flex items-center gap-1.5">
              <svg width="18" height="6" aria-hidden="true"><line x1="0" x2="18" y1="3" y2="3" strokeWidth="2" strokeDasharray={s.tracejado ? '4 3' : undefined} className={s.traco} /></svg>
              {s.rotulo}
            </span>
          ))}
        </figcaption>
      )}
    </figure>
  )
}

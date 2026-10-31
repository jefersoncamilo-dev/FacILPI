/**
 * Onda 5 (#213): contraste WCAG AA dos tokens de cor, lido direto do
 * index.css, nos temas claro e escuro. Texto normal >= 4.5:1; ícone/faixa
 * (componente gráfico) >= 3:1.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(resolve(__dirname, '../index.css'), 'utf-8')

function bloco(seletor: string): Record<string, string> {
  const ini = css.indexOf(seletor)
  if (ini < 0) throw new Error(`seletor ausente: ${seletor}`)
  const abre = css.indexOf('{', ini)
  const fecha = css.indexOf('}', abre)
  const vars: Record<string, string> = {}
  for (const m of css.slice(abre + 1, fecha).matchAll(/--([\w-]+):\s*([\d.]+ [\d.]+% [\d.]+%);/g)) {
    vars[m[1]] = m[2]
  }
  return vars
}

function luminancia(hsl: string): number {
  const [h, s, l] = hsl.split(' ').map(parseFloat)
  const sat = s / 100
  const lum = l / 100
  const a = sat * Math.min(lum, 1 - lum)
  const f = (n: number) => {
    const k = (n + h / 30) % 12
    return lum - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))
  }
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  return 0.2126 * lin(f(0)) + 0.7152 * lin(f(8)) + 0.0722 * lin(f(4))
}

function contraste(a: string, b: string): number {
  const [l1, l2] = [luminancia(a), luminancia(b)].sort((x, y) => y - x)
  return (l1 + 0.05) / (l2 + 0.05)
}

const claro = bloco(':root {')
const escuro = { ...claro, ...bloco(':root[data-theme="dark"] {') }
const automaticoEscuro = { ...claro, ...bloco(':root:not([data-theme="light"]) {') }

// [texto, fundo, mínimo]
const PARES: [string, string, number][] = [
  ['foreground', 'background', 4.5],
  ['foreground', 'background-desktop', 4.5],
  ['card-foreground', 'card', 4.5],
  ['muted-foreground', 'card', 4.5],
  ['muted-foreground', 'background-desktop', 4.5],
  ['primary-foreground', 'primary', 4.5],
  ['primary', 'card', 4.5],
  ['secondary-foreground', 'secondary', 4.5],
  ['accent-foreground', 'accent', 4.5],
  ['brand-ink', 'background', 4.5],
  ['brand-ink', 'card', 4.5],
  ['destructive-foreground', 'destructive', 4.5],
  // Botão de atenção preenchido (btn-alerta, Button variant alerta).
  ['primary-foreground', 'alerta-forte', 4.5],
  ['critico-texto', 'card', 4.5],
  ['critico-texto', 'critico-soft', 4.5],
  ['alerta-forte', 'card', 4.5],
  ['alerta-forte', 'alerta-soft', 4.5],
  ['info', 'card', 4.5],
  ['info', 'info-soft', 4.5],
  ['avatar-foreground', 'avatar', 4.5],
  // Laranja e vermelho de faixa/ícone: componente gráfico.
  ['alerta', 'card', 3],
  ['critico', 'card', 3],
]

describe.each([
  ['claro', claro],
  ['escuro', escuro],
])('contraste AA no tema %s', (_nome, tema) => {
  it.each(PARES)('%s sobre %s', (texto, fundo, minimo) => {
    expect(tema[texto], texto).toBeDefined()
    expect(tema[fundo], fundo).toBeDefined()
    expect(contraste(tema[texto], tema[fundo])).toBeGreaterThanOrEqual(minimo)
  })
})

it('tema automático escuro usa os mesmos valores do escuro explícito', () => {
  expect(automaticoEscuro).toEqual(escuro)
})

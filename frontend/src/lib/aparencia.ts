/**
 * Onda 5 (#213): preferências de aparência guardadas no aparelho.
 *
 * - Tema: "claro" | "escuro" | "automatico". Automático não grava atributo e
 *   deixa o `prefers-color-scheme` decidir (ver index.css).
 * - Visual: "completo" | "simples" | "automatico". Simples liga
 *   `data-visual="simples"` no <html>: vidro vira superfície sólida e a aurora
 *   some. Automático liga o simples em aparelho fraco.
 *
 * Nada aqui é dado clínico nem vai para o servidor.
 */
export type Tema = 'claro' | 'escuro' | 'automatico'
export type Visual = 'completo' | 'simples' | 'automatico'

const TEMA_KEY = 'facilpi.tema'
const VISUAL_KEY = 'facilpi.visual'

function ler(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function gravar(key: string, valor: string) {
  try {
    localStorage.setItem(key, valor)
  } catch {
    // Armazenamento bloqueado: a escolha vale só nesta visita.
  }
}

export function lerTema(): Tema {
  const v = ler(TEMA_KEY)
  return v === 'claro' || v === 'escuro' ? v : 'automatico'
}

export function lerVisual(): Visual {
  const v = ler(VISUAL_KEY)
  return v === 'completo' || v === 'simples' ? v : 'automatico'
}

/** Aparelho de entrada: poucos núcleos ou pouca memória. */
export function aparelhoFraco(nav: Navigator = navigator): boolean {
  const nucleos = nav.hardwareConcurrency
  const memoria = (nav as Navigator & { deviceMemory?: number }).deviceMemory
  return (typeof nucleos === 'number' && nucleos <= 4) || (typeof memoria === 'number' && memoria <= 2)
}

export function aplicarAparencia(
  raiz: HTMLElement = document.documentElement,
  nav: Navigator = navigator,
) {
  const tema = lerTema()
  if (tema === 'claro') raiz.setAttribute('data-theme', 'light')
  else if (tema === 'escuro') raiz.setAttribute('data-theme', 'dark')
  else raiz.removeAttribute('data-theme')

  const visual = lerVisual()
  const simples = visual === 'simples' || (visual === 'automatico' && aparelhoFraco(nav))
  if (simples) raiz.setAttribute('data-visual', 'simples')
  else raiz.removeAttribute('data-visual')
}

export function definirTema(tema: Tema) {
  gravar(TEMA_KEY, tema)
  aplicarAparencia()
}

export function definirVisual(visual: Visual) {
  gravar(VISUAL_KEY, visual)
  aplicarAparencia()
}

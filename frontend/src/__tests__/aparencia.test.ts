import { afterEach, describe, expect, it } from 'vitest'
import { aparelhoFraco, aplicarAparencia, definirTema, definirVisual, lerTema, lerVisual } from '../lib/aparencia'

const nav = (hardwareConcurrency: number, deviceMemory?: number) =>
  ({ hardwareConcurrency, deviceMemory }) as unknown as Navigator

afterEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.removeAttribute('data-visual')
})

describe('aparência', () => {
  it('sem preferência: tema automático, sem atributo', () => {
    expect(lerTema()).toBe('automatico')
    aplicarAparencia(document.documentElement, nav(8, 8))
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
    expect(document.documentElement.hasAttribute('data-visual')).toBe(false)
  })

  it('guarda o tema escolhido no aparelho e aplica no <html>', () => {
    definirTema('escuro')
    expect(localStorage.getItem('facilpi.tema')).toBe('escuro')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    definirTema('claro')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    definirTema('automatico')
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
  })

  it('valor desconhecido guardado cai para automático', () => {
    localStorage.setItem('facilpi.tema', 'roxo')
    localStorage.setItem('facilpi.visual', 'x')
    expect(lerTema()).toBe('automatico')
    expect(lerVisual()).toBe('automatico')
  })

  it('aparelho fraco liga o visual simples no automático', () => {
    expect(aparelhoFraco(nav(4))).toBe(true)
    expect(aparelhoFraco(nav(8, 2))).toBe(true)
    expect(aparelhoFraco(nav(8, 8))).toBe(false)
    aplicarAparencia(document.documentElement, nav(2))
    expect(document.documentElement.getAttribute('data-visual')).toBe('simples')
  })

  it('preferência do usuário vence o aparelho', () => {
    definirVisual('completo')
    aplicarAparencia(document.documentElement, nav(2))
    expect(document.documentElement.hasAttribute('data-visual')).toBe(false)
    definirVisual('simples')
    aplicarAparencia(document.documentElement, nav(16, 16))
    expect(document.documentElement.getAttribute('data-visual')).toBe('simples')
  })
})

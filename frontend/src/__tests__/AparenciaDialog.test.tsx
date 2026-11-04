import { afterEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AparenciaDialog } from '../components/shell/AparenciaDialog'

afterEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.removeAttribute('data-visual')
})

describe('Aparência (Onda 5)', () => {
  it('tema escolhido vale na hora e fica guardado no aparelho', async () => {
    render(<AparenciaDialog open onOpenChange={() => {}} />)
    expect(screen.getByRole('radio', { name: 'Automático' })).toHaveAttribute('aria-checked', 'true')
    await userEvent.click(screen.getByRole('radio', { name: 'Escuro' }))
    expect(screen.getByRole('radio', { name: 'Escuro' })).toHaveAttribute('aria-checked', 'true')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(localStorage.getItem('facilpi.tema')).toBe('escuro')
  })

  it('visual simples liga e desliga o plano B', async () => {
    render(<AparenciaDialog open onOpenChange={() => {}} />)
    const caixa = screen.getByRole('checkbox', { name: /Visual simples/ })
    await userEvent.click(caixa)
    expect(document.documentElement.getAttribute('data-visual')).toBe('simples')
    expect(localStorage.getItem('facilpi.visual')).toBe('simples')
    await userEvent.click(caixa)
    expect(localStorage.getItem('facilpi.visual')).toBe('automatico')
  })
})

import { describe, it, expect, vi } from 'vitest'
import { useState } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Activity } from 'lucide-react'
import { Modal } from '../components/Modal'
import { MetricCard } from '../components/ui/metric-card'
import { rotuloAcao, rotuloModulo, rotuloSituacaoEvento, rotuloSituacaoResidente } from '../lib/rotulos'
import { rotuloDoItem } from '../services/plantao'

describe('UX-11 — rótulos de exibição (valor de contrato intacto)', () => {
  it('situação do residente e eventos acentuados; texto livre passa como veio', () => {
    expect(rotuloSituacaoResidente('Em admissao')).toBe('Em admissão')
    expect(rotuloSituacaoResidente('Ativo')).toBe('Ativo')
    expect(rotuloSituacaoResidente(null)).toBe('—')
    expect(rotuloSituacaoEvento('em_elaboracao')).toBe('Em elaboração')
    expect(rotuloSituacaoEvento('hospitalizacao')).toBe('Hospitalização')
    expect(rotuloSituacaoEvento('Grau II')).toBe('Grau II')
    expect(rotuloSituacaoEvento(null)).toBe('')
  })

  it('permissões legíveis, com fallback para chave desconhecida', () => {
    expect(rotuloModulo('planos_cuidados')).toBe('Plano de cuidados')
    expect(rotuloModulo('admissoes')).toBe('Admissões')
    expect(rotuloAcao('atribuir_permissao')).toBe('Atribuir permissões')
    expect(rotuloAcao('ler')).toBe('Ver')
    expect(rotuloModulo('modulo_novo')).toBe('modulo novo')
    expect(rotuloAcao('acao_nova')).toBe('acao nova')
  })

  it('itens do plantão sem texto técnico sem acento', () => {
    expect(rotuloDoItem({ origem: 'medicacao', descricao: 'Dose prevista de medicacao' })).toBe('Dose prevista de medicação')
    expect(rotuloDoItem({ origem: 'intercorrencia', descricao: 'Intercorrencia aberta: Queda' })).toBe('Intercorrência aberta: Queda')
    expect(rotuloDoItem({ origem: 'intercorrencia', descricao: '' })).toBe('Intercorrência aberta')
    expect(rotuloDoItem({ origem: 'cuidado', descricao: 'Banho assistido' })).toBe('Banho assistido')
  })
})

describe('UX-11 — Modal único sobre o Radix', () => {
  function Tela({ onClose = vi.fn() }: { onClose?: () => void }) {
    const [aberto, setAberto] = useState(false)
    return (
      <>
        <button type="button" onClick={() => setAberto(true)}>Abrir</button>
        <Modal open={aberto} onClose={() => { onClose(); setAberto(false) }} title="Registrar teste">
          <input aria-label="Campo" />
          <button type="button">Confirmar</button>
        </Modal>
      </>
    )
  }

  it('prende o foco, fecha com Escape e devolve o foco a quem abriu', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<Tela onClose={onClose} />)
    const abrir = screen.getByRole('button', { name: 'Abrir' })
    await user.click(abrir)
    const dialogo = await screen.findByRole('dialog', { name: 'Registrar teste' })
    expect(dialogo.getAttribute('aria-modal')).toBe('true')
    for (let i = 0; i < 5; i++) {
      await user.tab()
      expect(dialogo.contains(document.activeElement)).toBe(true)
    }
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(onClose).toHaveBeenCalled()
    await waitFor(() => expect(document.activeElement).toBe(abrir))
  })
})

describe('UX-11 — indicador (KPI)', () => {
  it('cartão sempre branco; o status vai no número e no ícone', () => {
    const { container, rerender } = render(<MetricCard icon={Activity} titulo="Intercorrências abertas" valor={2} tom="alerta" />)
    const cartao = container.firstElementChild as HTMLElement
    expect(cartao.getAttribute('data-tom')).toBe('alerta')
    expect(cartao.className).toContain('bg-card')
    expect(cartao.className).not.toMatch(/bg-(orange|amber)/)
    expect(screen.getByText('2').className).toContain('text-alerta-forte')
    rerender(<MetricCard icon={Activity} titulo="Residentes" valor={40} tom="normal" />)
    expect(screen.getByText('40').className).toContain('text-primary')
  })
})

import { describe, it, expect, vi } from 'vitest'
import { useState } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Activity } from 'lucide-react'
import { Modal } from '../components/Modal'
import { MetricCard } from '../components/ui/metric-card'
import { rotuloAcao, rotuloModulo, rotuloSituacaoEvento, rotuloSituacaoResidente } from '../lib/rotulos'
import { rotuloDoItem } from '../services/plantao'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { BarraSegmentada, percentual, Rosca, type Segmento } from '../components/ui/charts'
import { acoesDoPerfil } from '../components/shell/acoesRapidas'
import { useAberturaPorParametro } from '../hooks/useAberturaPorParametro'
import { pendenciasPorHora } from '../pages/Dashboard'

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

describe('UX-11 — Início visual: gráficos com dado real', () => {
  const LEITOS: Segmento[] = [
    { rotulo: 'Ocupados', valor: 3, fundo: 'bg-primary', traco: 'stroke-primary' },
    { rotulo: 'Livres', valor: 1, fundo: 'bg-emerald-300', traco: 'stroke-emerald-300' },
    { rotulo: 'Indisponíveis', valor: 0, fundo: 'bg-slate-300', traco: 'stroke-slate-300' },
  ]

  it('rosca e barra expõem os números e respeitam as proporções', () => {
    render(<><Rosca titulo="Leitos" segmentos={LEITOS} centro="75%" /><BarraSegmentada titulo="Leitos (barra)" segmentos={LEITOS} /></>)
    expect(screen.getByRole('img', { name: 'Leitos: Ocupados: 3, Livres: 1, Indisponíveis: 0' })).toBeTruthy()
    const barra = screen.getByRole('img', { name: /^Leitos \(barra\)/ })
    expect([...barra.children].map(c => (c as HTMLElement).style.width)).toEqual(['75%', '25%'])
    expect(percentual(3, 4)).toBe(75)
    expect(percentual(1, 0)).toBe(0)
  })

  it('pendências por hora: atrasadas na primeira hora, intercorrência sem horário fora', () => {
    const agora = Date.parse('2026-09-26T12:00:00Z')
    const item = (previsto_em: string | null) => ({ origem: 'cuidado' as const, registro_id: String(previsto_em), residente_id: 'r', descricao: 'x', previsto_em })
    const { valores, rotulos } = pendenciasPorHora([
      item('2026-09-26T11:00:00Z'), item('2026-09-26T12:30:00Z'), item('2026-09-26T14:10:00Z'), item('2026-09-27T12:00:00Z'), item(null),
    ], agora)
    expect(valores.length).toBe(12)
    expect(valores[0]).toBe(2)
    expect(valores[2]).toBe(1)
    expect(valores.reduce((a, b) => a + b, 0)).toBe(3)
    expect(rotulos[0]).toBe('09h')
  })
})

describe('UX-11 — ações rápidas pelo perfil de acesso', () => {
  it('só as ações permitidas, na ordem do contexto', () => {
    const pode = (c?: string) => ['sinais_vitais:criar', 'admissoes:criar', 'plantao:ler'].includes(c || '')
    expect(acoesDoPerfil(pode, false).map(a => a.id)).toEqual(['sinal', 'plantao', 'passagem', 'admissao'])
    expect(acoesDoPerfil(pode, true).map(a => a.id)).toEqual(['admissao', 'sinal', 'plantao', 'passagem'])
    expect(acoesDoPerfil(() => false, true)).toEqual([])
  })

  function Tela({ permitido }: { permitido: boolean }) {
    const [aberto, setAberto] = useAberturaPorParametro('novo', permitido)
    const local = useLocation()
    return <><p data-testid="estado">{aberto ? 'aberto' : 'fechado'}</p><p data-testid="url">{local.search}</p><button onClick={() => setAberto(false)}>Fechar</button></>
  }

  it('?novo=1 abre só com permissão (mesmo que ela chegue depois) e sai da URL ao fechar', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<MemoryRouter initialEntries={['/admissoes?novo=1']}><Tela permitido={false} /></MemoryRouter>)
    expect(screen.getByTestId('estado').textContent).toBe('fechado')
    expect(screen.getByTestId('url').textContent).toBe('?novo=1')
    rerender(<MemoryRouter initialEntries={['/admissoes?novo=1']}><Tela permitido /></MemoryRouter>)
    await waitFor(() => expect(screen.getByTestId('estado').textContent).toBe('aberto'))
    await user.click(screen.getByRole('button', { name: 'Fechar' }))
    await waitFor(() => expect(screen.getByTestId('url').textContent).toBe(''))
    expect(screen.getByTestId('estado').textContent).toBe('fechado')
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { BuscaGlobal, telasDaBusca } from '../components/shell/BuscaGlobal'
import { getResidentesResumo } from '../services/plantao'
import { normalizar } from '../lib/texto'

// Dados sintéticos: nomes fictícios, nenhum dado real.
vi.mock('../services/plantao', () => ({ getResidentesResumo: vi.fn() }))

let permissoes: string[] = []
vi.mock('../context/PermissoesContext', () => {
  const valor = () => ({ status: 'ok', pode: (chave?: string) => !chave || permissoes.includes(chave) })
  // UX-GRAU: o grau oficial usa usePermissoesOuPadrao; sem grau_dependencia:ler, não consulta.
  return { usePermissoes: valor, usePermissoesOuPadrao: valor }
})

const mockResidentes = vi.mocked(getResidentesResumo)

function renderBusca(onOpenChange = vi.fn()) {
  render(
    <MemoryRouter initialEntries={['/']}>
      <BuscaGlobal open onOpenChange={onOpenChange} />
      <Routes>
        <Route path="/" element={<p>tela início</p>} />
        <Route path="/residentes/:id" element={<p>tela ficha</p>} />
        <Route path="/sinais" element={<p>tela sinais</p>} />
      </Routes>
    </MemoryRouter>,
  )
  return onOpenChange
}

const campo = () => screen.getByRole('combobox', { name: 'Buscar residente ou tela' })

beforeEach(() => {
  permissoes = ['residentes:ler', 'sinais_vitais:ler']
  mockResidentes.mockReset()
  mockResidentes.mockResolvedValue([
    { id: 'r1', nome: 'João Teste Sintético' },
    { id: 'r2', nome: 'Maria Exemplo' },
  ])
})

describe('UX-NAV-1 — normalizar', () => {
  it('ignora acento, maiúscula e espaços extras', () => {
    expect(normalizar('  JOÃO  da   Conceição ')).toBe('joao da conceicao')
  })
})

describe('UX-NAV-1 — busca global', () => {
  it('encontra residente sem acento e abre a ficha com Enter', async () => {
    const user = userEvent.setup()
    const fechar = renderBusca()
    await user.type(campo(), 'joao')
    const lista = within(screen.getByRole('listbox'))
    expect(await lista.findByRole('option', { name: /João Teste Sintético/ })).toBeTruthy()
    expect(lista.queryByRole('option', { name: /Maria/ })).toBeNull()
    await user.keyboard('{Enter}')
    expect(await screen.findByText('tela ficha')).toBeTruthy()
    expect(fechar).toHaveBeenCalledWith(false)
  })

  it('setas mudam a opção ativa', async () => {
    const user = userEvent.setup()
    mockResidentes.mockResolvedValue([{ id: 'r1', nome: 'Sinésio Um' }])
    renderBusca()
    await user.type(campo(), 'sin')
    const opcoes = await screen.findAllByRole('option')
    expect(opcoes.map(o => o.getAttribute('aria-selected'))).toEqual(['true', 'false'])
    await user.keyboard('{ArrowDown}')
    expect(screen.getAllByRole('option').map(o => o.getAttribute('aria-selected'))).toEqual(['false', 'true'])
    expect(campo().getAttribute('aria-activedescendant')).toBe(screen.getAllByRole('option')[1].id)
    await user.keyboard('{Enter}')
    expect(await screen.findByText('tela sinais')).toBeTruthy()
  })

  it('só mostra telas que a sessão pode abrir', async () => {
    const user = userEvent.setup()
    renderBusca()
    await user.type(campo(), 'intercorr')
    expect(await screen.findByText('Nenhum residente ou tela encontrado')).toBeTruthy()
    expect(telasDaBusca(c => !c || permissoes.includes(c)).map(t => t.to)).toEqual(['/', '/residentes', '/sinais', '/relatorios'])
  })

  it('sem residentes:ler não consulta residentes', async () => {
    permissoes = ['sinais_vitais:ler']
    const user = userEvent.setup()
    renderBusca()
    expect(screen.getByText('Digite o nome de uma tela.')).toBeTruthy()
    await user.type(campo(), 'joao')
    expect(await screen.findByText('Nenhum residente ou tela encontrado')).toBeTruthy()
    expect(mockResidentes).not.toHaveBeenCalled()
  })

  it('sem resultado explica o que fazer', async () => {
    const user = userEvent.setup()
    renderBusca()
    await user.type(campo(), 'xyzw')
    const vazio = await screen.findByRole('status')
    expect(vazio.textContent).toContain('Nenhum residente ou tela encontrado')
    expect(vazio.textContent).toContain('Acentos e maiúsculas não importam.')
  })

  it('falha ao buscar residentes não esconde as telas', async () => {
    mockResidentes.mockRejectedValue(new Error('rede'))
    const user = userEvent.setup()
    renderBusca()
    await user.type(campo(), 'sinais')
    expect(await screen.findByRole('option', { name: /Sinais Vitais/ })).toBeTruthy()
    expect(screen.getByRole('alert').textContent).toContain('Não foi possível buscar residentes agora')
  })
})

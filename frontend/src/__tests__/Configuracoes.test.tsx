import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { Configuracoes } from '../pages/Configuracoes'
import { configuracoesApi } from '../services/configuracoes'

vi.mock('../services/configuracoes', () => ({ configuracoesApi: { ler: vi.fn(), salvar: vi.fn() } }))
const BASE = { id: 'i', razao_social: 'Casa Sintética', cnpj: null, situacao: 'ATIVA', telefone: '11', fuso_horario: 'America/Sao_Paulo' } as any

describe('Configuracoes', () => {
  beforeEach(() => vi.clearAllMocks())

  it('carrega e salva sem enviar razão social', async () => {
    vi.mocked(configuracoesApi.ler).mockResolvedValue(BASE)
    vi.mocked(configuracoesApi.salvar).mockResolvedValue(BASE)
    render(<MemoryRouter><Configuracoes /></MemoryRouter>)
    expect(await screen.findByText(/Casa Sintética/)).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: 'Salvar' }))
    await waitFor(() => expect(configuracoesApi.salvar).toHaveBeenCalled())
    expect(vi.mocked(configuracoesApi.salvar).mock.calls[0][0]).not.toHaveProperty('razao_social')
  })

  it('403 mostra sem acesso', async () => {
    vi.mocked(configuracoesApi.ler).mockRejectedValue({ response: { status: 403 } })
    render(<MemoryRouter><Configuracoes /></MemoryRouter>)
    expect(await screen.findByText('Sem acesso às configurações')).toBeTruthy()
  })
})

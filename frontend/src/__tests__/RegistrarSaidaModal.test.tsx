import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { RegistrarSaidaModal } from '../components/residentes/RegistrarSaidaModal'
import * as saida from '../services/saidaResidente'

vi.mock('../services/saidaResidente', async () => {
  const actual = await vi.importActual<typeof import('../services/saidaResidente')>('../services/saidaResidente')
  return { ...actual, getPendenciasSaida: vi.fn(), registrarSaida: vi.fn() }
})

const mockPendencias = vi.mocked(saida.getPendenciasSaida)
const mockRegistrar = vi.mocked(saida.registrarSaida)

const PENDENCIAS = {
  pendencias: [
    { origem: 'pais', registro_id: 'p1', descricao: 'PAIS vigente (v1)', link: '/plano/p1' },
    { origem: 'leito', registro_id: 'l1', descricao: 'Leito ocupado: A · 1 · 1', link: '/quartos' },
  ],
  origens_sem_leitura: [],
}

function abrir(podeLiberarLeito = true) {
  const onRegistrado = vi.fn()
  render(
    <MemoryRouter>
      <RegistrarSaidaModal open onClose={vi.fn()} onRegistrado={onRegistrado}
        residente={{ id: 'r1', nome: 'Maria' }} podeLiberarLeito={podeLiberarLeito} />
    </MemoryRouter>,
  )
  return onRegistrado
}

describe('RegistrarSaidaModal', () => {
  beforeEach(() => {
    mockPendencias.mockReset()
    mockRegistrar.mockReset()
    mockPendencias.mockResolvedValue(PENDENCIAS)
    mockRegistrar.mockResolvedValue({})
  })

  it('lista pendências com link e não libera o leito por padrão', async () => {
    const user = userEvent.setup()
    const onRegistrado = abrir()
    expect(await screen.findByRole('link', { name: 'PAIS vigente (v1)' })).toBeTruthy()
    const leito = screen.getByRole('checkbox', { name: /Liberar o leito agora/ }) as HTMLInputElement
    expect(leito.checked).toBe(false)
    await user.click(screen.getByRole('checkbox', { name: /Confirmo os dados/ }))
    await user.click(screen.getByRole('button', { name: 'Registrar saída' }))
    await waitFor(() => expect(mockRegistrar).toHaveBeenCalledTimes(1))
    const [, payload] = mockRegistrar.mock.calls[0]
    expect(payload).toMatchObject({ tipo: 'obito', local_obito: 'ilpi', liberar_leito: false })
    expect(payload).not.toHaveProperty('registrado_por')
    expect(onRegistrado).toHaveBeenCalled()
  })

  it('exige confirmação antes de enviar', async () => {
    const user = userEvent.setup()
    abrir()
    await screen.findByText('O que continua ativo')
    await user.click(screen.getByRole('button', { name: 'Registrar saída' }))
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(mockRegistrar).not.toHaveBeenCalled()
  })

  it('transferência exige destino e envia só os campos do tipo', async () => {
    const user = userEvent.setup()
    abrir()
    await user.selectOptions(screen.getByLabelText('Tipo de saída'), 'transferencia')
    await user.click(screen.getByRole('checkbox', { name: /Confirmo os dados/ }))
    await user.click(screen.getByRole('button', { name: 'Registrar saída' }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/destino/)
    await user.type(screen.getByLabelText('Nome do destino'), 'Hospital Central')
    await user.selectOptions(screen.getByLabelText('Destino'), 'hospital')
    await user.click(screen.getByRole('button', { name: 'Registrar saída' }))
    await waitFor(() => expect(mockRegistrar).toHaveBeenCalledTimes(1))
    const [, payload] = mockRegistrar.mock.calls[0]
    expect(payload).toMatchObject({ tipo: 'transferencia', destino_tipo: 'hospital', destino_descricao: 'Hospital Central' })
    expect(payload).not.toHaveProperty('local_obito')
  })

  it('sem permissão de leito a opção de liberar não aparece', async () => {
    abrir(false)
    await screen.findByText('O que continua ativo')
    expect(screen.queryByRole('checkbox', { name: /Liberar o leito agora/ })).toBeNull()
  })
})

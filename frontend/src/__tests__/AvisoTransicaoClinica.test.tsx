import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { AvisoTransicaoClinica } from '../components/transicao/AvisoTransicaoClinica'
import { api } from '../services/api'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn() } }
})
const mockGet = vi.mocked(api.get)

function responde(dados: object) {
  mockGet.mockResolvedValue({ data: { escritas_retiradas: ['sinais_vitais:criar'], prazo: '2026-11-28T12:00:00Z', ...dados } } as any)
}

const renderiza = (podeAtribuir = true) =>
  render(<MemoryRouter><AvisoTransicaoClinica podeAtribuir={podeAtribuir} /></MemoryRouter>)

beforeEach(() => vi.clearAllMocks())

describe('#15 — aviso da transição clínica do administrador (D3)', () => {
  it('na carência sem perfil clínico, pede para atribuir e leva à Equipe', async () => {
    responde({ afeta_esta_sessao: true, em_carencia: true, perfil_clinico_atribuido: false })
    renderiza()
    expect(await screen.findByText('O administrador vai deixar de registrar dados clínicos')).toBeTruthy()
    expect(screen.getByText(/Atribua um perfil clínico/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Atribuir perfil na Equipe' }).getAttribute('href')).toBe('/equipe')
  })

  it('depois do prazo, sem perfil clínico: bloqueio só do registro', async () => {
    responde({ afeta_esta_sessao: true, em_carencia: false, perfil_clinico_atribuido: false })
    renderiza(false)
    expect(await screen.findByText('Registro clínico bloqueado para o administrador')).toBeTruthy()
    expect(screen.getByText(/continua vendo residentes, prontuário, Dashboard e Alertas/)).toBeTruthy()
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('não aparece para outros perfis nem quando o corte já foi absorvido', async () => {
    for (const dados of [
      { afeta_esta_sessao: false, em_carencia: true, perfil_clinico_atribuido: false },
      { afeta_esta_sessao: true, em_carencia: false, perfil_clinico_atribuido: true },
    ]) {
      responde(dados)
      const { container, unmount } = renderiza()
      await waitFor(() => expect(mockGet).toHaveBeenCalled())
      expect(container.textContent).toBe('')
      unmount()
      mockGet.mockClear()
    }
  })
})

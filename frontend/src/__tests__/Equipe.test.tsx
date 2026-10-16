import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { FuncionarioCard } from '../components/equipe/FuncionarioCard'
import { RevogarAcessoModal } from '../components/equipe/RevogarAcessoModal'
import { InativarFuncionarioModal } from '../components/equipe/InativarFuncionarioModal'
import type { Funcionario, User } from '../types/equipe'

function renderNoProviders(ui: React.ReactElement) {
  return render(<BrowserRouter>{ui}</BrowserRouter>)
}

const mockFunc: Funcionario = {
  id: 'f1', ilpi_id: 'ilpi1', usuario_id: null,
  nome: 'Maria Silva', cpf: '12345678901', telefone: '11999998888',
  email: 'maria@test.com', cargo: 'Enfermeira', profissao: 'Enfermeiro',
  conselho_profissional: 'COREN', numero_conselho: '12345', uf_conselho: 'SP',
  situacao: 'ativo',
}

const mockFuncComAcesso: Funcionario = { ...mockFunc, id: 'f2', usuario_id: 'u1' }

const mockUsuario: User = {
  id: 'u1', nome: 'Maria Silva', email: 'maria@test.com',
  ativo: true, is_superuser: false, exige_troca_senha: false,
}

const baseCallbacks = {
  onEdit: vi.fn(),
  onConcederAcesso: vi.fn(),
  onVincular: vi.fn(),
  onRevogarAcesso: vi.fn(),
  onInativar: vi.fn(),
}

beforeEach(() => { vi.clearAllMocks() })

describe('FuncionarioCard', () => {
  it('renders employee name and profession', () => {
    renderNoProviders(<FuncionarioCard funcionario={mockFunc} {...baseCallbacks} />)
    expect(screen.getByText('Maria Silva')).toBeInTheDocument()
    expect(screen.getByText('Enfermeiro')).toBeInTheDocument()
  })

  it('shows "Sem acesso ao sistema" when no linked user', () => {
    renderNoProviders(<FuncionarioCard funcionario={mockFunc} {...baseCallbacks} />)
    expect(screen.getByText('Sem acesso ao sistema')).toBeInTheDocument()
  })

  it('hides "Sem acesso" when user is linked', () => {
    renderNoProviders(<FuncionarioCard funcionario={mockFuncComAcesso} {...baseCallbacks} />)
    expect(screen.queryByText('Sem acesso ao sistema')).not.toBeInTheDocument()
  })

  it('shows situacao badge', () => {
    renderNoProviders(<FuncionarioCard funcionario={mockFunc} {...baseCallbacks} />)
    expect(screen.getByText('Ativo')).toBeInTheDocument()
  })

  it('shows inactive badge for inactive employee', () => {
    const inactive = { ...mockFunc, situacao: 'inativo' as const }
    renderNoProviders(<FuncionarioCard funcionario={inactive} {...baseCallbacks} />)
    expect(screen.getByText('Inativo')).toBeInTheDocument()
  })

  it('shows CPF and email details', () => {
    renderNoProviders(<FuncionarioCard funcionario={mockFunc} {...baseCallbacks} />)
    expect(screen.getByText(/CPF: 12345678901/)).toBeInTheDocument()
    expect(screen.getByText(/E-mail: maria@test.com/)).toBeInTheDocument()
  })

  it('shows conselho info', () => {
    renderNoProviders(<FuncionarioCard funcionario={mockFunc} {...baseCallbacks} />)
    expect(screen.getByText(/COREN: 12345\/SP/)).toBeInTheDocument()
  })
})

describe('RevogarAcessoModal', () => {
  it('renders when open with user and funcionario', () => {
    renderNoProviders(
      <RevogarAcessoModal open={true} onClose={vi.fn()} funcionario={mockFuncComAcesso} usuario={mockUsuario} onConfirm={vi.fn()} />
    )
    expect(screen.getAllByText('Revogar acesso').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Maria Silva')).toBeInTheDocument()
  })

  it('does not render when closed', () => {
    renderNoProviders(
      <RevogarAcessoModal open={false} onClose={vi.fn()} funcionario={mockFuncComAcesso} usuario={mockUsuario} onConfirm={vi.fn()} />
    )
    expect(screen.queryByText('Revogar acesso')).not.toBeInTheDocument()
  })

  it('explains record preservation', () => {
    renderNoProviders(
      <RevogarAcessoModal open={true} onClose={vi.fn()} funcionario={mockFuncComAcesso} usuario={mockUsuario} onConfirm={vi.fn()} />
    )
    expect(screen.getByText(/será preservado/i)).toBeInTheDocument()
  })

  it('has Cancelar and Revogar buttons', () => {
    renderNoProviders(
      <RevogarAcessoModal open={true} onClose={vi.fn()} funcionario={mockFuncComAcesso} usuario={mockUsuario} onConfirm={vi.fn()} />
    )
    expect(screen.getByText('Cancelar')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /revogar acesso/i })).toBeInTheDocument()
  })
})

describe('InativarFuncionarioModal', () => {
  it('renders when open', () => {
    renderNoProviders(
      <InativarFuncionarioModal open={true} onClose={vi.fn()} funcionario={mockFunc} onConfirm={vi.fn()} />
    )
    expect(screen.getByText(/inativar o funcionário/i)).toBeInTheDocument()
    expect(screen.getByText('Maria Silva')).toBeInTheDocument()
  })

  it('does not render when closed', () => {
    renderNoProviders(
      <InativarFuncionarioModal open={false} onClose={vi.fn()} funcionario={mockFunc} onConfirm={vi.fn()} />
    )
    expect(screen.queryByText(/inativar o funcionário/i)).not.toBeInTheDocument()
  })

  it('explains history preservation and non-deletion', () => {
    renderNoProviders(
      <InativarFuncionarioModal open={true} onClose={vi.fn()} funcionario={mockFunc} onConfirm={vi.fn()} />
    )
    expect(screen.getByText(/preservado/i)).toBeInTheDocument()
    expect(screen.getByText(/não será excluído fisicamente/i)).toBeInTheDocument()
  })

  it('has Cancelar and Inativar buttons', () => {
    renderNoProviders(
      <InativarFuncionarioModal open={true} onClose={vi.fn()} funcionario={mockFunc} onConfirm={vi.fn()} />
    )
    expect(screen.getByText('Cancelar')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /inativar funcionário/i })).toBeInTheDocument()
  })
})

describe('platform_superuser is not a regulated profession', () => {
  it('REGULATED_PROFESSIONS does not contain platform_superuser', async () => {
    const { REGULATED_PROFESSIONS } = await import('../types/equipe')
    expect(REGULATED_PROFESSIONS).not.toContain('platform_superuser')
  })
})

describe('Regulated professions list', () => {
  it('includes expected professions', async () => {
    const { REGULATED_PROFESSIONS } = await import('../types/equipe')
    for (const prof of ['enfermeiro', 'medico', 'psicologo', 'fisioterapeuta', 'nutricionista']) {
      expect(REGULATED_PROFESSIONS).toContain(prof)
    }
  })

  it('includes accented variants', async () => {
    const { REGULATED_PROFESSIONS } = await import('../types/equipe')
    expect(REGULATED_PROFESSIONS).toContain('médico')
    expect(REGULATED_PROFESSIONS).toContain('psicólogo')
  })
})

describe('UF_VALIDAS', () => {
  it('contains all 27 Brazilian states', async () => {
    const { UF_VALIDAS } = await import('../types/equipe')
    expect(UF_VALIDAS).toHaveLength(27)
    expect(UF_VALIDAS).toContain('SP')
    expect(UF_VALIDAS).toContain('RJ')
    expect(UF_VALIDAS).toContain('MG')
  })
})

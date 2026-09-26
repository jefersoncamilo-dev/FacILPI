import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { Admissoes } from '../pages/Admissoes'
import { AdmissaoDetalhe } from '../pages/AdmissaoDetalhe'
import { api } from '../services/api'
import { contextApi } from '../services/context'
import type { Admissao, VerificacaoPendencias } from '../services/admissoes'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }
})

vi.mock('../services/context', () => ({
  contextApi: {
    selectContext: vi.fn(),
    listInstitutions: vi.fn(async () => ({ data: [] })),
    listPerfis: vi.fn(async () => ({ data: [] })),
    permissoesDaSessao: vi.fn(),
  },
  resolveContextLabels: vi.fn(async (ctx: any) => ctx),
  logoutServidor: vi.fn(),
}))

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)
const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

const TUDO = ['admissoes:ler', 'admissoes:criar', 'admissoes:avancar', 'admissoes:concluir', 'admissoes:cancelar',
  'admissoes:reabrir', 'admissoes:atualizar', 'residentes:ler', 'residentes:criar', 'sinais_vitais:criar']

function admissao(parcial: Partial<Admissao> = {}): Admissao {
  return {
    id: 'adm-1', ilpi_id: 'i1', residente_id: 'res-1', situacao: 'documentacao', autor_id: 'u1',
    responsavel_funcionario_id: null, iniciada_em: '2026-09-20T10:00:00Z', concluida_em: null,
    cancelada_em: null, desistencia_em: null, motivo_cancelamento: null, motivo_desistencia: null,
    contrato_registrado_em: null, contrato_documento_id: null, avaliacoes_requeridas: [], lock_version: 3,
    created_at: '2026-09-20T10:00:00Z', updated_at: '2026-09-20T10:00:00Z', ...parcial,
  }
}

function verificacao(parcial: Partial<VerificacaoPendencias> = {}): VerificacaoPendencias {
  return {
    admissao_id: 'adm-1', lock_version: 3, data_verificacao: '2026-09-25', documentos: [],
    avaliacoes_requeridas: [], quarto_leito_ids: [], pais_ids: [], pendencias: [], requisitos_cumpridos: true, ...parcial,
  }
}

const RESIDENTES = [
  { id: 'res-1', nome: 'Antônia Ribeiro' },
  { id: 'res-2', nome: 'Benedito Carvalho' },
  { id: 'res-3', nome: 'Cecília Moura' },
]

function erro(status: number, detail: unknown) {
  return { response: { status, data: { detail } } }
}

function renderLista(permissoes = TUDO) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes } } as any)
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={['/admissoes']}>
        <PermissoesProvider>
          <Routes>
            <Route path="/admissoes" element={<Admissoes />} />
            <Route path="/admissoes/:id" element={<div>TELA-DETALHE</div>} />
          </Routes>
        </PermissoesProvider>
      </MemoryRouter>
    </AuthProvider>,
  )
}

function renderDetalhe(permissoes = TUDO) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes } } as any)
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={['/admissoes/adm-1']}>
        <PermissoesProvider>
          <Routes>
            <Route path="/admissoes/:id" element={<AdmissaoDetalhe />} />
          </Routes>
        </PermissoesProvider>
      </MemoryRouter>
    </AuthProvider>,
  )
}

/** GET por URL; `estado` permite trocar a resposta entre recarregamentos. */
function respondeDetalhe(estado: { admissao: Admissao; verificacao: VerificacaoPendencias }) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/admissoes/adm-1') return Promise.resolve({ data: estado.admissao } as any)
    if (url === '/admissoes/adm-1/pendencias') return Promise.resolve({ data: estado.verificacao } as any)
    if (url === '/admissoes/adm-1/historico') return Promise.resolve({ data: [] } as any)
    if (url === '/residentes/res-1') return Promise.resolve({ data: { id: 'res-1', nome: 'Antônia Ribeiro' } } as any)
    throw new Error(`URL inesperada: ${url}`)
  })
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('Admissões — lista', () => {
  function respondeLista(admissoes: Admissao[] | object) {
    mockGet.mockImplementation((url: string) => {
      if (url === '/admissoes/') return Array.isArray(admissoes) ? Promise.resolve({ data: admissoes } as any) : Promise.reject(admissoes)
      if (url === '/residentes/') return Promise.resolve({ data: RESIDENTES } as any)
      throw new Error(`URL inesperada: ${url}`)
    })
  }

  it('mostra os processos em andamento com nome e etapa real', async () => {
    respondeLista([
      admissao(),
      admissao({ id: 'adm-2', residente_id: 'res-2', situacao: 'concluida', concluida_em: '2026-09-22T12:00:00Z' }),
    ])
    renderLista()
    const item = (await screen.findByText('Antônia Ribeiro')).closest('a')!
    expect(within(item).getByText('Documentação')).toBeTruthy()
    expect(within(item).getByText('Etapa 3 de 7')).toBeTruthy()
    expect(screen.queryByText('Benedito Carvalho')).toBeNull()
    expect(screen.getByRole('tab', { name: /Concluídas \(1\)/ })).toBeTruthy()
  })

  it('403 diz que não há acesso; erro não vira lista vazia', async () => {
    respondeLista(erro(403, { code: 'PERMISSION_DENIED', message: 'Permissão não autorizada' }))
    const sem = renderLista()
    expect(await screen.findByText('Sem acesso às admissões')).toBeTruthy()
    sem.unmount()

    respondeLista(new Error('rede'))
    renderLista()
    expect(await screen.findByText('Não foi possível carregar as admissões')).toBeTruthy()
    expect(screen.queryByText('Nenhuma admissão em andamento')).toBeNull()
  })

  it('"Nova admissão" só aparece para quem pode criar', async () => {
    respondeLista([])
    const leitor = renderLista(['admissoes:ler', 'residentes:ler'])
    expect(await screen.findByText('Nenhuma admissão em andamento')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Nova admissão/ })).toBeNull()
    leitor.unmount()

    respondeLista([])
    renderLista()
    expect((await screen.findAllByRole('button', { name: /Nova admissão/ })).length).toBeGreaterThan(0)
  })

  it('nova admissão só oferece residentes sem processo aberto ou concluído, e explica o 409', async () => {
    const user = userEvent.setup()
    respondeLista([
      admissao({ residente_id: 'res-1', situacao: 'triagem' }),
      admissao({ id: 'adm-3', residente_id: 'res-3', situacao: 'cancelada', cancelada_em: '2026-09-21T10:00:00Z', motivo_cancelamento: 'x' }),
    ])
    mockPost.mockRejectedValueOnce(erro(409, { code: 'ADMISSAO_CONFLITO', message: 'Processo existente' }))
    renderLista()
    await user.click((await screen.findAllByRole('button', { name: /Nova admissão/ }))[0])
    const select = await screen.findByLabelText('Residente')
    const opcoes = within(select).getAllByRole('option').map(o => o.textContent)
    expect(opcoes).toContain('Benedito Carvalho')
    expect(opcoes).toContain('Cecília Moura')
    expect(opcoes).not.toContain('Antônia Ribeiro')

    await user.selectOptions(select, 'res-2')
    await user.click(screen.getByRole('button', { name: 'Abrir admissão' }))
    expect(mockPost).toHaveBeenCalledWith('/admissoes/', { residente_id: 'res-2' })
    expect(await screen.findByText(/já tem uma admissão aberta ou concluída/)).toBeTruthy()
  })
})

describe('Admissões — detalhe e etapas', () => {
  it('a pendência da etapa bloqueia o avanço e diz onde resolver', async () => {
    respondeDetalhe({
      admissao: admissao(),
      verificacao: verificacao({
        pendencias: [{ codigo: 'documentacao_pendente', origem: 'documentos.obrigatorio', referencia_id: 'doc-1' }],
        requisitos_cumpridos: false,
      }),
    })
    renderDetalhe()
    expect(await screen.findByRole('heading', { name: 'Antônia Ribeiro' })).toBeTruthy()
    const etapas = screen.getByRole('navigation', { name: 'Etapas da admissão' })
    expect(within(etapas).getByText('Documentação').closest('li')!.getAttribute('aria-current')).toBe('step')
    expect(screen.getByRole('button', { name: /Avançar para Avaliações/ })).toBeDisabled()
    const etapaAtual = screen.getByRole('region', { name: 'Etapa atual' })
    expect(within(etapaAtual).getByText('Documento obrigatório ainda não validado')).toBeTruthy()
    expect(within(etapaAtual).getByRole('link', { name: 'Resolver em Documentos' })).toBeTruthy()
  })

  it('avançar envia a próxima etapa e a versão atual, e recarrega', async () => {
    const user = userEvent.setup()
    const estado = { admissao: admissao({ situacao: 'triagem', lock_version: 5 }), verificacao: verificacao() }
    respondeDetalhe(estado)
    mockPost.mockImplementationOnce(async () => {
      estado.admissao = admissao({ situacao: 'documentacao', lock_version: 6 })
      return { data: estado.admissao } as any
    })
    renderDetalhe()
    await user.click(await screen.findByRole('button', { name: /Avançar para Documentação/ }))
    expect(mockPost).toHaveBeenCalledWith('/admissoes/adm-1/avancar', { lock_version: 5, etapa_destino: 'documentacao' })
    expect(await screen.findByText('Admissão avançou para Documentação.')).toBeTruthy()
    await waitFor(() => expect(screen.getByRole('button', { name: /Avançar para Avaliações/ })).toBeTruthy())
  })

  it('422 do backend lista as pendências e mantém o usuário na tela', async () => {
    const user = userEvent.setup()
    respondeDetalhe({ admissao: admissao({ situacao: 'pais' }), verificacao: verificacao() })
    mockPost.mockRejectedValueOnce(erro(422, {
      code: 'ADMISSAO_INVALIDA', message: 'Admissao possui pendencias',
      pendencias: [{ codigo: 'pais_pendente', origem: 'planos_cuidados.situacao=vigente' }],
    }))
    renderDetalhe()
    await user.click(await screen.findByRole('button', { name: /Concluir admissão/ }))
    expect(await screen.findByText('Ainda há pendências que impedem esta ação.')).toBeTruthy()
    expect(screen.getByText('Residente sem PAIS vigente')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Antônia Ribeiro' })).toBeTruthy()
  })

  it('versão obsoleta recarrega os dados e avisa, sem sobrescrever', async () => {
    const user = userEvent.setup()
    const estado = { admissao: admissao({ situacao: 'triagem', lock_version: 5 }), verificacao: verificacao() }
    respondeDetalhe(estado)
    mockPost.mockImplementationOnce(async () => {
      estado.admissao = admissao({ situacao: 'documentacao', lock_version: 7 })
      throw erro(409, { code: 'ADMISSAO_CONFLITO', message: 'Versao obsoleta; recarregue a admissao' })
    })
    renderDetalhe()
    await user.click(await screen.findByRole('button', { name: /Avançar para Documentação/ }))
    expect(await screen.findByText(/alterada por outra pessoa/)).toBeTruthy()
    expect(await screen.findByRole('button', { name: /Avançar para Avaliações/ })).toBeTruthy()
    expect(mockPost).toHaveBeenCalledTimes(1)
  })

  it('concluída mostra a saída para a operação e não oferece reabrir', async () => {
    respondeDetalhe({ admissao: admissao({ situacao: 'concluida', concluida_em: '2026-09-25T15:00:00Z' }), verificacao: verificacao() })
    renderDetalhe()
    const painel = await screen.findByRole('region', { name: 'Admissão concluída' })
    expect(within(painel).getByRole('link', { name: /Abrir prontuário/ }).getAttribute('href')).toBe('/residentes/res-1')
    expect(within(painel).getByRole('link', { name: /Registrar sinais vitais/ })).toBeTruthy()
    expect(within(painel).queryByRole('link', { name: /Registrar intercorrência/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Reabrir/ })).toBeNull()
  })

  it('cancelada pode ser reaberta por quem tem permissão, com motivo', async () => {
    const user = userEvent.setup()
    respondeDetalhe({
      admissao: admissao({ situacao: 'cancelada', cancelada_em: '2026-09-24T10:00:00Z', motivo_cancelamento: 'Família adiou' }),
      verificacao: verificacao(),
    })
    mockPost.mockResolvedValueOnce({ data: admissao({ situacao: 'pre_cadastro' }) } as any)
    renderDetalhe()
    expect(await screen.findByText('Motivo: Família adiou')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: /Reabrir admissão/ }))
    await user.type(await screen.findByLabelText('Motivo'), 'Família confirmou a vinda')
    await user.click(screen.getByRole('button', { name: 'Reabrir' }))
    expect(mockPost).toHaveBeenCalledWith('/admissoes/adm-1/reabrir', { lock_version: 3, motivo: 'Família confirmou a vinda' })
  })

  it('sem permissão de avançar ou encerrar, nenhuma dessas ações aparece', async () => {
    respondeDetalhe({ admissao: admissao({ situacao: 'triagem' }), verificacao: verificacao() })
    renderDetalhe(['admissoes:ler', 'residentes:ler'])
    await screen.findByRole('heading', { name: 'Antônia Ribeiro' })
    await waitFor(() => expect(screen.queryByRole('button', { name: /Avançar/ })).toBeNull())
    expect(screen.queryByRole('button', { name: /Cancelar admissão/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /desistência/ })).toBeNull()
  })
})

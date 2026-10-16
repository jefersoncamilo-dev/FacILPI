import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { PermissoesProvider } from '../context/PermissoesContext'
import { Pais } from '../pages/Pais'
import { PaisDetalhe } from '../pages/PaisDetalhe'
import { api } from '../services/api'
import { contextApi } from '../services/context'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }
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
const mockPatch = vi.mocked(api.patch)
const mockPermissoes = vi.mocked(contextApi.permissoesDaSessao)

const item = (id: string, descricao: string, extra: Record<string, unknown> = {}) => ({ id, descricao, situacao: 'ativa', ...extra })
const plano = (p: Record<string, unknown>) => ({
  residente_id: 'r1', versao: 1, objetivos: null, data_inicial: '2026-09-01', data_final: null, situacao: 'rascunho',
  revisor_funcionario_id: null, aprovador_funcionario_id: null, revisado_em: null, aprovado_em: null,
  motivo_encerramento: null, encerrado_em: null, anterior_id: null, motivo_versao: null, superseded_by: null,
  created_at: '2026-09-01T10:00:00Z', necessidades: [], metas: [], intervencoes: [], ...p,
})
const COMPLETO = {
  necessidades: [item('n1', 'Risco de queda', { categoria: 'Mobilidade', origem: 'manual' })],
  metas: [item('m1', 'Zero quedas no trimestre')],
  intervencoes: [item('i1', 'Acompanhar deambulação', { necessidade_id: 'n1', frequencia: 'Diária' })],
}
const RESIDENTES = [{ id: 'r1', nome: 'Antônia Ribeiro' }, { id: 'r2', nome: 'Benedito Carvalho' }]
const EQUIPE = [{ id: 'f1', nome: 'Enf. Carla Souza', situacao: 'ativo', cargo: 'Enfermeira' }, { id: 'f2', nome: 'Desligado', situacao: 'inativo' }]
const TUDO = ['planos_cuidados:ler', 'planos_cuidados:criar', 'planos_cuidados:atualizar', 'planos_cuidados:revisar',
  'planos_cuidados:aprovar', 'planos_cuidados:encerrar', 'residentes:ler', 'funcionarios:ler']

function responde(planos: Record<string, unknown>[] | { response: unknown } | Error) {
  mockGet.mockImplementation((url: string) => {
    const de = (x: unknown) => (x instanceof Error || (x as any)?.response ? Promise.reject(x) : Promise.resolve({ data: x } as any))
    if (url === '/planos-cuidados/') return de(planos)
    const um = url.match(/^\/planos-cuidados\/(\w+)$/)
    if (um && Array.isArray(planos)) {
      const p = planos.find(x => x.id === um[1])
      return p ? de(p) : de({ response: { status: 404 } })
    }
    if (url === '/residentes/') return de(RESIDENTES)
    if (url.startsWith('/residentes/')) return de(RESIDENTES.find(r => url.endsWith(r.id)))
    if (url === '/funcionarios/') return de(EQUIPE)
    throw new Error(`URL inesperada: ${url}`)
  })
}

function Local() {
  const l = useLocation()
  return <p data-testid="local">{l.pathname}{l.search}</p>
}

function renderEm(rota: string, permissoes = TUDO) {
  mockPermissoes.mockResolvedValue({ data: { scope: 'ilpi', permissoes } } as any)
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[rota]}>
        <PermissoesProvider>
          <Routes>
            <Route path="/plano" element={<Pais />} />
            <Route path="/plano/:id" element={<PaisDetalhe />} />
          </Routes>
          <Local />
        </PermissoesProvider>
      </MemoryRouter>
    </AuthProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('PAIS — lista', () => {
  it('um cartão por residente com o plano vigente (ou a versão mais recente) e filtro por situação', async () => {
    const user = userEvent.setup()
    responde([
      plano({ id: 'p1', situacao: 'substituido', versao: 1 }),
      plano({ id: 'p2', situacao: 'vigente', versao: 2, ...COMPLETO }),
      plano({ id: 'p3', situacao: 'rascunho', versao: 3 }),
      plano({ id: 'p4', residente_id: 'r2', situacao: 'em_elaboracao' }),
    ])
    renderEm('/plano')
    const antonia = (await screen.findByText('Antônia Ribeiro')).closest('a')!
    expect(antonia.getAttribute('href')).toBe('/plano/p2')
    expect(within(antonia).getByText('Vigente')).toBeTruthy()
    expect(within(antonia).getByText(/Versão 2 · 3 versões/)).toBeTruthy()
    expect(within(antonia).getByText(/1 necessidade, 1 meta, 1 intervenção/)).toBeTruthy()

    await user.click(screen.getByRole('button', { name: 'Vigentes' }))
    expect(screen.queryByText('Benedito Carvalho')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Em andamento' }))
    expect(screen.getByText('Benedito Carvalho')).toBeTruthy()
    expect(screen.queryByText('Antônia Ribeiro')).toBeNull()
  })

  it('?residente= restringe ao residente; 403 e falha não viram "nenhum plano"', async () => {
    responde([plano({ id: 'p1' }), plano({ id: 'p4', residente_id: 'r2' })])
    const filtrada = renderEm('/plano?residente=r2')
    expect(await screen.findByText('Benedito Carvalho')).toBeTruthy()
    expect(screen.queryByText('Antônia Ribeiro')).toBeNull()
    filtrada.unmount()

    responde({ response: { status: 403, data: { detail: 'x' } } })
    const sem = renderEm('/plano')
    expect(await screen.findByText('Sem acesso aos planos de cuidados')).toBeTruthy()
    sem.unmount()
    responde(new Error('rede'))
    renderEm('/plano')
    expect(await screen.findByText('Não foi possível carregar os planos')).toBeTruthy()
    expect(screen.queryByText('Nenhum plano de cuidados ainda')).toBeNull()
  })

  it('novo PAIS cria rascunho e abre o detalhe; sem permissão de criar, não há botão', async () => {
    const user = userEvent.setup()
    responde([])
    mockPost.mockResolvedValueOnce({ data: plano({ id: 'novo', residente_id: 'r2' }) } as any)
    const tela = renderEm('/plano')
    await user.click((await screen.findAllByRole('button', { name: /Novo PAIS/ }))[0])
    const dialog = within(await screen.findByRole('dialog'))
    await user.selectOptions(dialog.getByLabelText('Residente'), 'r2')
    await user.clear(dialog.getByLabelText('Início'))
    await user.type(dialog.getByLabelText('Início'), '2026-09-20')
    await user.click(dialog.getByRole('button', { name: 'Criar rascunho' }))
    expect(mockPost).toHaveBeenCalledWith('/planos-cuidados/', { residente_id: 'r2', data_inicial: '2026-09-20' })
    await waitFor(() => expect(screen.getByTestId('local').textContent).toBe('/plano/novo'))
    tela.unmount()

    responde([])
    renderEm('/plano', ['planos_cuidados:ler', 'residentes:ler'])
    expect(await screen.findByText('Nenhum plano de cuidados ainda')).toBeTruthy()
    await waitFor(() => expect(screen.queryByRole('button', { name: /Novo PAIS/ })).toBeNull())
  })
})

describe('PAIS — ciclo no detalhe', () => {
  it('rascunho: adiciona e remove itens e inicia a elaboração', async () => {
    const user = userEvent.setup()
    responde([plano({ id: 'p1', ...COMPLETO })])
    mockPost.mockResolvedValue({ data: {} } as any)
    mockPatch.mockResolvedValue({ data: {} } as any)
    renderEm('/plano/p1')
    const necessidades = within(await screen.findByRole('region', { name: 'Necessidades' }))
    expect(necessidades.getByText('Mobilidade')).toBeTruthy()
    expect(within(screen.getByRole('region', { name: 'Intervenções' })).getByText(/para: Risco de queda/)).toBeTruthy()

    await user.click(necessidades.getByRole('button', { name: /Adicionar/ }))
    const dialog = within(await screen.findByRole('dialog'))
    await user.type(dialog.getByLabelText('Descrição'), '  Desidratação  ')
    await user.type(dialog.getByLabelText('Categoria'), 'Nutrição')
    await user.click(dialog.getByRole('button', { name: 'Adicionar' }))
    expect(mockPost).toHaveBeenCalledWith('/planos-cuidados/p1/necessidades', { descricao: 'Desidratação', categoria: 'Nutrição' })

    await user.click(within(screen.getByRole('region', { name: 'Metas' })).getByRole('button', { name: /Remover meta/ }))
    expect(mockPatch).toHaveBeenCalledWith('/planos-cuidados/p1/metas/m1', { situacao: 'inativa' })

    await user.click(within(screen.getByRole('region', { name: 'Próxima etapa' })).getByRole('button', { name: 'Iniciar elaboração' }))
    expect(mockPatch).toHaveBeenCalledWith('/planos-cuidados/p1', { situacao: 'em_elaboracao' })
    expect(await screen.findByText('Elaboração iniciada.')).toBeTruthy()
  })

  it('revisão exige quem revisou entre os funcionários ativos', async () => {
    const user = userEvent.setup()
    responde([plano({ id: 'p1', situacao: 'em_elaboracao', ...COMPLETO })])
    mockPost.mockResolvedValue({ data: {} } as any)
    renderEm('/plano/p1')
    const etapa = within(await screen.findByRole('region', { name: 'Próxima etapa' }))
    const botao = etapa.getByRole('button', { name: 'Registrar revisão' })
    expect(botao).toHaveProperty('disabled', true)
    await waitFor(() => expect(etapa.getAllByRole('option').map(o => o.textContent)).toEqual(['Selecione um funcionário ativo…', 'Enf. Carla Souza · Enfermeira']))
    await user.selectOptions(etapa.getByLabelText('Revisado por'), 'f1')
    await user.click(botao)
    expect(mockPost).toHaveBeenCalledWith('/planos-cuidados/p1/revisar', { funcionario_id: 'f1' })
  })

  it('aprovação: completude visível e botão bloqueado; erro do backend aparece com a mensagem dele', async () => {
    const user = userEvent.setup()
    responde([plano({ id: 'p1', situacao: 'em_revisao', necessidades: COMPLETO.necessidades, metas: [], intervencoes: [] })])
    const incompleto = renderEm('/plano/p1')
    const etapa = within(await screen.findByRole('region', { name: 'Próxima etapa' }))
    expect(etapa.getByText(/Ao menos uma meta ativa — pendente/)).toBeTruthy()
    await user.selectOptions(await etapa.findByLabelText('Aprovado por'), 'f1')
    expect(etapa.getByRole('button', { name: 'Registrar aprovação' })).toHaveProperty('disabled', true)
    // sem conteúdo editável fora de rascunho/elaboração
    expect(screen.queryByRole('button', { name: /Adicionar/ })).toBeNull()
    incompleto.unmount()

    responde([plano({ id: 'p1', situacao: 'em_revisao', ...COMPLETO })])
    mockPost.mockRejectedValueOnce({ response: { status: 409, data: { detail: 'Somente plano em revisao pode ser aprovado' } } })
    renderEm('/plano/p1')
    const etapa2 = within(await screen.findByRole('region', { name: 'Próxima etapa' }))
    await user.selectOptions(await etapa2.findByLabelText('Aprovado por'), 'f1')
    await user.click(etapa2.getByRole('button', { name: 'Registrar aprovação' }))
    expect(await screen.findByText('Somente plano em revisao pode ser aprovado')).toBeTruthy()
  })

  it('nova versão aprovada não entra em vigência enquanto a anterior estiver vigente', async () => {
    responde([
      plano({ id: 'v1', situacao: 'vigente', ...COMPLETO }),
      plano({ id: 'v2', situacao: 'aprovado', versao: 2, anterior_id: 'v1', motivo_versao: 'Reavaliação', ...COMPLETO }),
    ])
    renderEm('/plano/v2')
    const etapa = within(await screen.findByRole('region', { name: 'Próxima etapa' }))
    expect(await etapa.findByText('A versão anterior ainda está vigente')).toBeTruthy()
    expect(etapa.getByRole('link', { name: 'versão 1' }).getAttribute('href')).toBe('/plano/v1')
    expect(etapa.getByRole('button', { name: 'Colocar em vigência' })).toHaveProperty('disabled', true)
    expect(screen.getByText('Motivo desta versão: Reavaliação')).toBeTruthy()
  })

  it('vigente: encerrar exige motivo e responsável; sem permissão, só leitura', async () => {
    const user = userEvent.setup()
    responde([plano({ id: 'p1', situacao: 'vigente', ...COMPLETO })])
    mockPost.mockResolvedValue({ data: {} } as any)
    const gestao = renderEm('/plano/p1')
    await user.click(await screen.findByRole('button', { name: /Encerrar plano/ }))
    const dialog = within(await screen.findByRole('dialog'))
    await user.selectOptions(await dialog.findByLabelText('Responsável'), 'f1')
    await user.type(dialog.getByLabelText('Motivo do encerramento'), 'Alta da instituição')
    await user.click(dialog.getByRole('button', { name: 'Encerrar plano' }))
    expect(mockPost).toHaveBeenCalledWith('/planos-cuidados/p1/encerrar', { motivo: 'Alta da instituição', funcionario_id: 'f1' })
    gestao.unmount()

    renderEm('/plano/p1', ['planos_cuidados:ler', 'residentes:ler'])
    expect(await screen.findByRole('region', { name: 'Necessidades' })).toBeTruthy()
    await waitFor(() => expect(screen.queryByRole('button', { name: /Encerrar plano|Criar nova versão/ })).toBeNull())
    expect(screen.queryByRole('region', { name: 'Próxima etapa' })).toBeNull()
  })

  it('plano de outra ILPI (404) não vaza existência', async () => {
    responde([])
    renderEm('/plano/xyz')
    expect(await screen.findByText('Plano não encontrado')).toBeTruthy()
  })
})

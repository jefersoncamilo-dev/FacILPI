import { describe, expect, it } from 'vitest'
import {
  MODULOS,
  itensVisiveis,
  moduloDaRota,
  moduloPorSlug,
  modulosVisiveis,
  type ModuloGrupo,
  type Pode,
} from '../components/shell/navegacao'

const com = (...chaves: string[]): Pode => chave => !chave || chaves.includes(chave)
/** Estado `indisponivel` do PermissoesContext: tudo que existe aparece. */
const tudo: Pode = () => true

const grupo = (id: string) => MODULOS.find(m => m.id === id) as ModuloGrupo
const ids = (pode: Pode) => modulosVisiveis(pode).map(m => m.id)

describe('UX-00A — modelo de navegação', () => {
  it('raiz: Início, Central de Alertas e Meu Plantão; grupos na ordem da arquitetura', () => {
    expect(MODULOS.map(m => m.id)).toEqual([
      'inicio', 'alertas', 'plantao', 'residentes', 'assistencial', 'multidisciplinar',
      'farmacia', 'equipe', 'gestao', 'relatorios', 'configuracoes',
    ])
  })

  it('Meu Plantão existe uma única vez, só na raiz', () => {
    const destinos = MODULOS.flatMap(m =>
      m.tipo === 'link' ? [m.to] : m.itens.flatMap(i => (i.status === 'ativo' ? [i.to] : [])),
    )
    expect(destinos.filter(to => to === '/plantao')).toHaveLength(1)
    const rotulos = MODULOS.flatMap(m => (m.tipo === 'grupo' ? m.itens.map(i => i.label) : []))
    expect(rotulos.some(r => /plant[aã]o/i.test(r) && r !== 'Passagem de Plantão')).toBe(false)
  })

  it('nenhuma URL existente muda de endereço', () => {
    const destinos = MODULOS.flatMap(m =>
      m.tipo === 'link' ? [m.to] : m.itens.flatMap(i => (i.status === 'ativo' ? [i.to] : [])),
    )
    expect(destinos.sort()).toEqual([
      '/', '/admissoes', '/alertas', '/avaliacoes', '/documentos', '/equipe', '/escala',
      '/intercorrencias', '/passagem', '/plano', '/plantao', '/quartos', '/residentes', '/sinais',
    ])
  })

  it('itens e módulos futuros nunca aparecem, nem com permissões indisponíveis', () => {
    expect(ids(tudo)).toEqual(['inicio', 'alertas', 'plantao', 'residentes', 'assistencial', 'multidisciplinar', 'equipe'])
    for (const modulo of modulosVisiveis(tudo)) {
      if (modulo.tipo !== 'grupo') continue
      for (const item of itensVisiveis(modulo, tudo)) expect(item.status).toBe('ativo')
    }
    expect(itensVisiveis(grupo('residentes'), tudo).map(i => i.id)).not.toContain('estoque')
    expect(itensVisiveis(grupo('assistencial'), tudo).map(i => i.id)).not.toContain('cuidados')
    expect(itensVisiveis(grupo('farmacia'), tudo)).toEqual([])
  })

  it('só mostra o que a sessão pode abrir e esconde grupo sem item permitido', () => {
    const pode = com('sinais_vitais:ler')
    expect(ids(pode)).toEqual(['inicio', 'assistencial'])
    expect(itensVisiveis(grupo('assistencial'), pode).map(i => i.id)).toEqual(['sinais'])
  })

  it('Avaliações e Plano de Cuidados ficam em Multidisciplinar com as mesmas permissões', () => {
    const itens = itensVisiveis(grupo('multidisciplinar'), com('avaliacoes:ler', 'planos_cuidados:ler'))
    expect(itens.map(i => [i.to, i.permissao])).toEqual([
      ['/avaliacoes', 'avaliacoes:ler'],
      ['/plano', 'planos_cuidados:ler'],
    ])
  })

  it('cada profissão é um domínio próprio, sem chave compartilhada', () => {
    const areas = grupo('multidisciplinar').itens.filter(i => i.status === 'futuro')
    expect(areas.map(i => i.id)).toEqual(['fisioterapia', 'nutricao', 'psicologia', 'servico_social', 'enfermagem'])
    const chaves = areas.map(i => (i.status === 'futuro' ? i.permissaoPlanejada : undefined))
    expect(new Set(chaves).size).toBe(areas.length)
    areas.forEach((area, n) => expect(chaves[n]).toBe(`multidisciplinar.${area.id}:ler`))
  })

  it('Farmácia é domínio futuro separado e Estoque do Residente fica em Residentes', () => {
    expect(grupo('farmacia').status).toBe('futuro')
    expect(grupo('farmacia').itens).toHaveLength(8)
    expect(grupo('residentes').itens.find(i => i.id === 'estoque')?.status).toBe('futuro')
  })

  it('Passagem de Plantão mantém plantao:ler (lacuna documentada, sem mudança no UX-00)', () => {
    const passagem = itensVisiveis(grupo('assistencial'), tudo).find(i => i.id === 'passagem')
    expect(passagem?.permissao).toBe('plantao:ler')
  })
})

describe('UX-00A — rota atual e hubs', () => {
  it('detalhe herda o item pai e o módulo', () => {
    const atual = moduloDaRota('/residentes/abc')
    expect(atual?.modulo.id).toBe('residentes')
    expect(atual?.item?.to).toBe('/residentes')
    expect(moduloDaRota('/plano/xyz')?.modulo.id).toBe('multidisciplinar')
    expect(moduloDaRota('/escala')?.modulo.id).toBe('equipe')
  })

  it('Início só casa com a raiz exata', () => {
    expect(moduloDaRota('/')?.modulo.id).toBe('inicio')
    expect(moduloDaRota('/plantao')?.modulo.id).toBe('plantao')
    expect(moduloDaRota('/residentesx')).toBeNull()
  })

  it('hub de grupo ativo resolve sem item; slug inválido, futuro ou de link não', () => {
    expect(moduloDaRota('/modulos/assistencial')).toMatchObject({ modulo: { id: 'assistencial' }, item: null })
    expect(moduloPorSlug('residentes')?.id).toBe('residentes')
    expect(moduloPorSlug('farmacia')).toBeNull()
    expect(moduloPorSlug('plantao')).toBeNull()
    expect(moduloPorSlug('nao-existe')).toBeNull()
    expect(moduloPorSlug(undefined)).toBeNull()
    expect(moduloDaRota('/modulos/farmacia')).toBeNull()
  })

  it('grupo existente sem permissão continua resolvível (hub mostra "Sem acesso")', () => {
    const modulo = moduloPorSlug('equipe')
    expect(modulo).not.toBeNull()
    expect(itensVisiveis(modulo!, com())).toEqual([])
  })
})

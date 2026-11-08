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
      'inicio', 'alertas', 'plantao', 'residentes', 'cuidado', 'medicamentos', 'equipe', 'instituicao',
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
      '/', '/admissoes', '/agenda', '/alertas', '/auditoria', '/avaliacoes', '/configuracoes', '/cuidados', '/documentos', '/equipe', '/escala', '/estoque', '/financeiro',
      '/intercorrencias', '/medicacao',
      '/multidisciplinar/enfermagem', '/multidisciplinar/fisioterapia', '/multidisciplinar/nutricao', '/multidisciplinar/psicologia', '/multidisciplinar/servico_social',
      '/passagem', '/pia', '/plano', '/plantao', '/quartos', '/relatorios', '/residentes', '/sinais',
    ])
  })

  it('itens e módulos futuros nunca aparecem, nem com permissões indisponíveis', () => {
    expect(ids(tudo)).toEqual(['inicio', 'alertas', 'plantao', 'residentes', 'cuidado', 'medicamentos', 'equipe', 'instituicao'])
    for (const modulo of modulosVisiveis(tudo)) {
      if (modulo.tipo !== 'grupo') continue
      for (const item of itensVisiveis(modulo, tudo)) expect(item.status).toBe('ativo')
    }
    expect(itensVisiveis(grupo('residentes'), tudo).map(i => i.id)).not.toContain('estoque')
    expect(itensVisiveis(grupo('medicamentos'), tudo).map(i => i.id)).toEqual(['medicacao', 'estoque'])
  })

  it('só mostra o que a sessão pode abrir e esconde grupo sem item permitido', () => {
    const pode = com('sinais_vitais:ler')
    expect(ids(pode)).toEqual(['inicio', 'cuidado'])
    expect(itensVisiveis(grupo('cuidado'), pode).map(i => i.id)).toEqual(['sinais'])
  })

  it('Avaliações e Plano de Cuidados ficam em Cuidado › Planejamento com as mesmas permissões', () => {
    const itens = itensVisiveis(grupo('cuidado'), com('avaliacoes:ler', 'planos_cuidados:ler'))
    expect(itens.map(i => [i.to, i.permissao])).toEqual([
      ['/avaliacoes', 'avaliacoes:ler'],
      ['/plano', 'planos_cuidados:ler'],
    ])
  })

  it('cada profissão é um domínio próprio, sem chave compartilhada', () => {
    const areas = grupo('cuidado').itens.filter(i => i.status === 'ativo' && i.to.startsWith('/multidisciplinar/'))
    expect(areas.map(i => i.id)).toEqual(['fisioterapia', 'nutricao', 'psicologia', 'servico_social', 'enfermagem'])
    const chaves = areas.map(i => (i.status === 'ativo' ? i.permissao : undefined))
    expect(new Set(chaves).size).toBe(areas.length)
    areas.forEach((area, n) => expect(chaves[n]).toBe(`multidisciplinar.${area.id}:ler`))
  })

  it('Medicamentos e estoque é seção própria e Estoque do Residente fica em Residentes', () => {
    expect(grupo('medicamentos').status).toBe('ativo')
    expect(itensVisiveis(grupo('medicamentos'), com('prescricoes:ler')).map(i => i.to)).toEqual(['/medicacao'])
    expect(grupo('residentes').itens.find(i => i.id === 'estoque')?.status).toBe('futuro')
  })

  it('G8: Passagem de Plantão usa passagem_plantao:ler, a chave do backend', () => {
    const passagem = itensVisiveis(grupo('cuidado'), tudo).find(i => i.id === 'passagem')
    expect(passagem?.permissao).toBe('passagem_plantao:ler')
  })
})

describe('UX-00A — rota atual e hubs', () => {
  it('detalhe herda o item pai e o módulo', () => {
    const atual = moduloDaRota('/residentes/abc')
    expect(atual?.modulo.id).toBe('residentes')
    expect(atual?.item?.to).toBe('/residentes')
    expect(moduloDaRota('/plano/xyz')?.modulo.id).toBe('cuidado')
    expect(moduloDaRota('/escala')?.modulo.id).toBe('equipe')
  })

  it('Início só casa com a raiz exata', () => {
    expect(moduloDaRota('/')?.modulo.id).toBe('inicio')
    expect(moduloDaRota('/plantao')?.modulo.id).toBe('plantao')
    expect(moduloDaRota('/residentesx')).toBeNull()
  })

  it('hub de grupo ativo resolve sem item; slug inválido, futuro ou de link não', () => {
    expect(moduloDaRota('/modulos/cuidado')).toMatchObject({ modulo: { id: 'cuidado' }, item: null })
    expect(moduloPorSlug('residentes')?.id).toBe('residentes')
        expect(moduloPorSlug('plantao')).toBeNull()
    expect(moduloPorSlug('nao-existe')).toBeNull()
    expect(moduloPorSlug(undefined)).toBeNull()
      })

  it('grupo existente sem permissão continua resolvível (hub mostra "Sem acesso")', () => {
    const modulo = moduloPorSlug('equipe')
    expect(modulo).not.toBeNull()
    expect(itensVisiveis(modulo!, com())).toEqual([])
  })
})

describe('UX-NAV-1 — seções da rotina', () => {
  it('Cuidado separa "No turno" de "Planejamento", nessa ordem', () => {
    const secoes = grupo('cuidado').itens.filter(i => i.status === 'ativo').map(i => i.secao ?? 'Planejamento')
    const primeiroPlanejamento = secoes.indexOf('Planejamento')
    expect(secoes.slice(0, primeiroPlanejamento).every(s => s === 'No turno')).toBe(true)
    expect(secoes.slice(primeiroPlanejamento).every(s => s === 'Planejamento')).toBe(true)
  })

  it('hubs antigos resolvem para a seção nova', () => {
    expect(moduloPorSlug('assistencial')?.id).toBe('cuidado')
    expect(moduloPorSlug('multidisciplinar')?.id).toBe('cuidado')
    expect(moduloPorSlug('farmacia')?.id).toBe('medicamentos')
    expect(moduloPorSlug('gestao')?.id).toBe('instituicao')
    expect(moduloPorSlug('relatorios')?.id).toBe('instituicao')
    expect(moduloPorSlug('configuracoes')?.id).toBe('instituicao')
  })
})

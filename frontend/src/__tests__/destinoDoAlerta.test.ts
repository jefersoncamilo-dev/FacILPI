import { describe, expect, it } from 'vitest'
import { destinoDoAlerta, type Alerta } from '../services/alertas'

// M5 (#177): cada regra leva ao registro certo, com residente e item quando o alerta os traz.
function alerta(regra: string, parcial: Partial<Alerta> = {}): Alerta {
  return {
    id: `${regra}:ref-1`, regra, categoria: 'admissao_documentos', gravidade: 'atencao', natureza: 'pendencia',
    titulo: 't', detalhe: null, residente_id: 'res-1', residente_nome: 'Benedito', referencia_id: 'ref-1',
    unidade: null, quarto: null, leito: null, local: null, desde: null, prazo: null,
    ...parcial,
  }
}

describe('destinoDoAlerta', () => {
  it.each([
    ['admissao_parada', '/admissoes/ref-1', 'Continuar admissão'],
    ['documento_aguardando_validacao', '/documentos?residente=res-1&id=ref-1', 'Validar documento'],
    ['documento_vencido', '/documentos?residente=res-1&id=ref-1', 'Atualizar documento'],
    ['documento_vencendo', '/documentos?residente=res-1&id=ref-1', 'Atualizar documento'],
    ['avaliacao_vencida', '/avaliacoes?residente=res-1&novo=1&id=ref-1', 'Realizar avaliação'],
    ['grau_ausente', '/avaliacoes?residente=res-1', 'Definir grau de dependência'],
    ['grau_vencido', '/avaliacoes?residente=res-1', 'Definir grau de dependência'],
    ['pais_parado', '/plano/ref-1', 'Abrir PAIS'],
    ['pais_vencido', '/plano/ref-1', 'Abrir PAIS'],
    ['pais_ausente', '/plano', 'Elaborar PAIS'],
    ['cuidados_sem_registro', '/plantao', 'Registrar cuidados'],
    ['doses_sem_registro', '/plantao', 'Registrar doses'],
    ['intercorrencia_grave_aberta', '/intercorrencias?residente=res-1&id=ref-1', 'Ver intercorrência'],
    ['intercorrencia_aberta_prolongada', '/intercorrencias?residente=res-1&id=ref-1', 'Ver intercorrência'],
    ['residente_sem_leito', '/quartos', 'Alocar leito'],
    ['ausencia_prolongada', '/quartos', 'Ver ausência'],
    ['acesso_nao_utilizado', '/equipe', 'Ver equipe'],
    ['regra_desconhecida', '/residentes/res-1', 'Abrir prontuário'],
  ])('%s → %s', (regra, to, acao) => {
    expect(destinoDoAlerta(alerta(regra))).toMatchObject({ to, acao })
  })

  it('omite o que o alerta não trouxe', () => {
    expect(destinoDoAlerta(alerta('documento_vencido', { residente_id: null })).to).toBe('/documentos?id=ref-1')
    expect(destinoDoAlerta(alerta('grau_ausente', { residente_id: null })).to).toBe('/avaliacoes')
    expect(destinoDoAlerta(alerta('regra_desconhecida', { residente_id: null })).to).toBe('/')
  })

  it('codifica os ids na query', () => {
    expect(destinoDoAlerta(alerta('intercorrencia_grave_aberta', { residente_id: 'a&b', referencia_id: 'c d' })).to)
      .toBe('/intercorrencias?residente=a%26b&id=c+d')
  })
})

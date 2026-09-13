import { describe, it, expect } from 'vitest'
import { formatDate, formatDateTime } from '../services/api'

// Issue #35. Os dois helpers recebem formas de entrada diferentes e precisam de tratamentos
// opostos: data sem hora nao pode sofrer conversao de fuso; instante completo precisa sofrer.
// Nenhuma assercao aqui depende do fuso da maquina, porque o timeZone e sempre explicito no
// helper — importante, ja que os testes rodam em maquinas diferentes e nao ha CI no projeto.

describe('formatDate — data de calendario (sem hora)', () => {
  // O valor exibido tem de ser o valor cadastrado. Datas espalhadas pelo ano para mostrar que
  // o deslocamento nao era caso de borda: antes da correcao, todas caiam um dia para tras.
  const casos: Array<[string, string]> = [
    ['1938-03-21', '21/03/1938'],
    ['1940-05-01', '01/05/1940'],
    ['1970-06-15', '15/06/1970'],
    ['2026-12-31', '31/12/2026'],
  ]

  it.each(casos)('1. %s e exibida como %s, sem deslocar o dia', (iso, esperado) => {
    expect(formatDate(iso)).toBe(esperado)
  })

  it('2. virada de ano nao retrocede para o ano anterior', () => {
    // Caso mais visivel do defeito: 2020-01-01 aparecia como 31/12/2019.
    expect(formatDate('2020-01-01')).toBe('01/01/2020')
  })

  it('3. 29 de fevereiro em ano bissexto', () => {
    expect(formatDate('2020-02-29')).toBe('29/02/2020')
  })
})

describe('formatDate — instante completo', () => {
  it('4. continua convertendo para America/Sao_Paulo', () => {
    // Dashboard.tsx passa new Date().toISOString(). Instante escolhido de proposito numa hora
    // em que o dia em UTC e o dia em Sao Paulo divergem: se este ramo virasse UTC junto com o
    // ramo de data-so-data, o Dashboard passaria a exibir o dia seguinte toda noite.
    expect(formatDate('2026-09-13T02:00:00.000Z')).toBe('12/09/2026')
  })
})

describe('formatDate — entradas sem valor util', () => {
  it('5. ausencia de valor vira travessao', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate(undefined)).toBe('—')
    expect(formatDate('')).toBe('—')
  })

  it('6. string nao interpretavel volta como veio, sem quebrar a tela', () => {
    // Intl lanca RangeError com Invalid Date; o helper devolve a entrada original.
    expect(formatDate('data-invalida')).toBe('data-invalida')
  })
})

describe('formatDateTime — nao pode regredir', () => {
  it('7. converte o instante para America/Sao_Paulo, com hora', () => {
    // Mesmo instante do caso 4: 02:00 UTC e 23:00 do dia anterior em Sao Paulo. Este teste
    // existe para impedir que a correcao da #35 vaze para o helper que esta correto.
    expect(formatDateTime('2026-09-13T02:00:00.000Z')).toBe('12/09/2026, 23:00')
  })

  it('8. ausencia de valor vira travessao', () => {
    expect(formatDateTime(null)).toBe('—')
  })
})

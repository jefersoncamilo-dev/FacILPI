import { describe, it, expect } from 'vitest'
import { horaAtual, resolverHorario } from '../lib/horarioReal'

// São Paulo é UTC−3 (sem horário de verão desde 2019).
const em = (iso: string) => new Date(iso)

describe('Horário real do cuidado (#136)', () => {
  it('formata a hora atual no fuso da tela', () => {
    expect(horaAtual(em('2026-09-30T12:40:00Z'))).toBe('09:40')
  })

  it('HH:MM de hoje vira o instante UTC correspondente', () => {
    const r = resolverHorario('09:15', em('2026-09-30T12:40:00Z'))
    expect(r).toEqual({ ok: true, iso: '2026-09-30T12:15:00.000Z', ontem: false })
  })

  it('plantão noturno: às 00:30, "23:50" é ontem', () => {
    const r = resolverHorario('23:50', em('2026-10-01T03:30:00Z')) // 00:30 em SP
    expect(r).toEqual({ ok: true, iso: '2026-10-01T02:50:00.000Z', ontem: true })
  })

  it('futuro próximo é recusado em vez de virar o dia anterior', () => {
    expect(resolverHorario('10:00', em('2026-09-30T12:40:00Z'))).toEqual({ ok: false, erro: 'futuro' })
  })

  it('mais de 12 horas atrás é recusado', () => {
    expect(resolverHorario('08:00', em('2026-09-30T23:30:00Z'))).toEqual({ ok: false, erro: 'antigo' }) // 20:30 em SP
  })

  it('formato inválido', () => {
    expect(resolverHorario('', em('2026-09-30T12:40:00Z'))).toEqual({ ok: false, erro: 'invalido' })
    expect(resolverHorario('25:00', em('2026-09-30T12:40:00Z'))).toEqual({ ok: false, erro: 'invalido' })
  })
})

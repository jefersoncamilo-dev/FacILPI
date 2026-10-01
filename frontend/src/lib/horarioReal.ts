/**
 * Horário real do cuidado (#136). A equipe informa só HH:MM, no fuso em que a
 * tela exibe os horários (o mesmo de `formatDateTime`). O backend recebe um
 * instante com fuso (`ocorrido_em`) e rejeita futuro com 422.
 *
 * Regras:
 * - HH:MM é interpretado no dia de hoje do fuso;
 * - se cair no futuro, vale o dia anterior (plantão noturno: às 00:30, "23:50" é ontem);
 * - o resultado precisa estar nas últimas 12 h — fora disso é quase sempre
 *   erro de digitação (ex.: "10:00" às 09:40 viraria ontem às 10:00), e a tela
 *   recusa em vez de gravar um dia errado em silêncio.
 */
export const FUSO_HORARIO_REAL = 'America/Sao_Paulo'
const JANELA_MS = 12 * 60 * 60 * 1000
const TOLERANCIA_MS = 60 * 1000

export type HorarioResolvido =
  | { ok: true; iso: string; ontem: boolean }
  | { ok: false; erro: 'invalido' | 'futuro' | 'antigo' }

function partes(agora: Date, fuso: string) {
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: fuso, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  })
  const p = Object.fromEntries(fmt.formatToParts(agora).map(x => [x.type, x.value]))
  return { ano: Number(p.year), mes: Number(p.month), dia: Number(p.day), hora: Number(p.hour), minuto: Number(p.minute) }
}

/** Diferença (ms) entre o relógio do fuso e o UTC no instante dado. */
function deslocamento(agora: Date, fuso: string): number {
  const p = partes(agora, fuso)
  const comoUtc = Date.UTC(p.ano, p.mes - 1, p.dia, p.hora, p.minuto)
  const agoraMinuto = Math.floor(agora.getTime() / 60000) * 60000
  return comoUtc - agoraMinuto
}

export function horaAtual(agora: Date = new Date(), fuso = FUSO_HORARIO_REAL): string {
  const p = partes(agora, fuso)
  return `${String(p.hora).padStart(2, '0')}:${String(p.minuto).padStart(2, '0')}`
}

export function resolverHorario(hhmm: string, agora: Date = new Date(), fuso = FUSO_HORARIO_REAL): HorarioResolvido {
  const m = /^(\d{2}):(\d{2})$/.exec(hhmm || '')
  if (!m) return { ok: false, erro: 'invalido' }
  const h = Number(m[1]); const min = Number(m[2])
  if (h > 23 || min > 59) return { ok: false, erro: 'invalido' }
  const p = partes(agora, fuso)
  let instante = Date.UTC(p.ano, p.mes - 1, p.dia, h, min) - deslocamento(agora, fuso)
  let ontem = false
  const futuroHoje = instante > agora.getTime() + TOLERANCIA_MS
  if (futuroHoje) { instante -= 24 * 60 * 60 * 1000; ontem = true }
  if (agora.getTime() - instante > JANELA_MS) return { ok: false, erro: futuroHoje ? 'futuro' : 'antigo' }
  return { ok: true, iso: new Date(instante).toISOString(), ontem }
}

export const MENSAGEM_HORARIO: Record<'invalido' | 'futuro' | 'antigo', string> = {
  invalido: 'Informe o horário no formato HH:MM.',
  futuro: 'O horário não pode estar no futuro.',
  antigo: 'Horário com mais de 12 horas: confira o valor.',
}

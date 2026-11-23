import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { ChevronLeft, ChevronRight, Search } from 'lucide-react'
import { PaginaModulo } from '../components/modulo/PaginaModulo'
import { Alert } from '../components/ui/feedback'
import { mensagemDeErro } from '../services/api'
import { getMapaRotina, type MapaItem, type MapaRotina, type SituacaoMapa, type Turno } from '../services/plantao'
import { cn } from '../lib/utils'

// UX-NAV-5 (#302): rotina do turno de todos os residentes. Só leitura: as
// situações vêm dos registros de cuidado e medicação; registrar continua no Meu Plantão.

const TURNOS: { id: Turno; rotulo: string; faixa: string }[] = [
  { id: 'manha', rotulo: 'Manhã', faixa: '7h–13h' },
  { id: 'tarde', rotulo: 'Tarde', faixa: '13h–19h' },
  { id: 'noite', rotulo: 'Noite', faixa: '19h–7h' },
]

export const ROTULO_SITUACAO: Record<SituacaoMapa, string> = {
  concluido: 'Concluído',
  ressalva: 'Com ressalva',
  atrasado: 'Atrasado',
  pendente: 'Pendente',
  nao_se_aplica: 'Não se aplica',
}

const ESTILO: Record<SituacaoMapa, string> = {
  concluido: 'bg-brand-soft text-brand-ink border-primary/30',
  ressalva: 'bg-alerta-soft text-alerta-forte border-alerta/30',
  atrasado: 'bg-critico-soft text-critico-texto border-critico/30',
  pendente: 'bg-card text-muted-foreground border-border',
  nao_se_aplica: 'bg-muted/40 text-muted-foreground border-transparent',
}

const SIMBOLO: Record<SituacaoMapa, string> = {
  concluido: '✓', ressalva: '!', atrasado: '⏱', pendente: '○', nao_se_aplica: '—',
}

// Pior situação primeiro: a célula mostra o que pede atenção.
const PESO: SituacaoMapa[] = ['atrasado', 'ressalva', 'pendente', 'concluido', 'nao_se_aplica']

export function piorSituacao(itens: MapaItem[]): SituacaoMapa {
  if (itens.length === 0) return 'nao_se_aplica'
  return PESO.find(p => itens.some(i => i.situacao === p)) ?? 'nao_se_aplica'
}

export function resumoDoTurno(itens: MapaItem[]) {
  const validos = itens.filter(i => i.situacao !== 'nao_se_aplica')
  const meds = validos.filter(i => i.origem === 'medicacao')
  const pct = (a: number, b: number) => (b === 0 ? null : Math.round((a / b) * 100))
  return {
    concluida: pct(validos.filter(i => i.situacao === 'concluido').length, validos.length),
    medicacao: pct(meds.filter(i => i.situacao === 'concluido').length, meds.length),
    ressalvas: validos.filter(i => i.situacao === 'ressalva').length,
    atrasados: validos.filter(i => i.situacao === 'atrasado').length,
  }
}

function hojeNoFuso(fuso = 'America/Sao_Paulo') {
  return new Intl.DateTimeFormat('en-CA', { timeZone: fuso, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
}

function somarDias(dia: string, n: number) {
  const d = new Date(`${dia}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

function turnoAtual(fuso = 'America/Sao_Paulo'): Turno {
  const h = Number(new Intl.DateTimeFormat('en-GB', { timeZone: fuso, hour: '2-digit', hourCycle: 'h23' }).format(new Date()))
  return h >= 7 && h < 13 ? 'manha' : h >= 13 && h < 19 ? 'tarde' : 'noite'
}

export function RotinaIlpi() {
  const [dia, setDia] = useState(() => {
    const hoje = hojeNoFuso()
    // Madrugada ainda é o turno da noite do dia anterior.
    const h = Number(new Intl.DateTimeFormat('en-GB', { timeZone: 'America/Sao_Paulo', hour: '2-digit', hourCycle: 'h23' }).format(new Date()))
    return h < 7 ? somarDias(hoje, -1) : hoje
  })
  const [turno, setTurno] = useState<Turno>(() => turnoAtual())
  const [mapa, setMapa] = useState<MapaRotina | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(true)
  const [busca, setBusca] = useState('')
  const [ala, setAla] = useState('')

  useEffect(() => {
    let vivo = true
    setCarregando(true)
    setErro(null)
    getMapaRotina({ dia, turno })
      .then(m => { if (vivo) setMapa(m) })
      .catch(e => { if (vivo) { setMapa(null); setErro(mensagemDeErro(e, 'Não foi possível carregar a rotina.')) } })
      .finally(() => { if (vivo) setCarregando(false) })
    return () => { vivo = false }
  }, [dia, turno])

  const fuso = mapa?.fuso ?? 'America/Sao_Paulo'
  const horaDe = useMemo(() => {
    const f = new Intl.DateTimeFormat('pt-BR', { timeZone: fuso, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
    return (iso: string) => `${f.format(new Date(iso)).slice(0, 2)}h`
  }, [fuso])

  const colunas = useMemo(() => {
    if (!mapa) return []
    const vistas: string[] = []
    for (const item of mapa.itens) {
      const h = horaDe(item.previsto_em)
      if (!vistas.includes(h)) vistas.push(h)
    }
    return vistas
  }, [mapa, horaDe])

  const colunaAgora = mapa && mapa.agora >= mapa.inicio && mapa.agora < mapa.fim ? horaDe(mapa.agora) : null
  const alas = useMemo(() => [...new Set((mapa?.residentes ?? []).map(r => r.ala).filter((a): a is string => !!a))].sort(), [mapa])

  const linhas = useMemo(() => {
    if (!mapa) return []
    const termo = busca.trim().toLocaleLowerCase('pt-BR')
    return mapa.residentes
      .filter(r => !ala || r.ala === ala)
      .filter(r => !termo || r.nome.toLocaleLowerCase('pt-BR').includes(termo) || (r.local ?? '').toLocaleLowerCase('pt-BR').includes(termo))
      .map(r => {
        const itens = mapa.itens.filter(i => i.residente_id === r.id)
        return { ...r, itens, resumo: resumoDoTurno(itens) }
      })
  }, [mapa, busca, ala])

  const resumo = resumoDoTurno(linhas.flatMap(l => l.itens))
  const hoje = hojeNoFuso(fuso)
  const rotuloDia = dia === hoje ? 'Hoje' : new Date(`${dia}T12:00:00Z`).toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: '2-digit', timeZone: 'UTC' })

  return (
    <PaginaModulo
      titulo="Rotina da ILPI"
      subtitulo="O que já foi feito, o que tem ressalva e o que está pendente no turno, para todos os residentes."
      voltarPara="/modulos/cuidado"
      verTambem={[{ to: '/plantao', rotulo: 'Meu Plantão' }, { to: '/passagem', rotulo: 'Passagem de plantão' }]}
    >
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1" role="group" aria-label="Dia">
          <button type="button" aria-label="Dia anterior" onClick={() => setDia(d => somarDias(d, -1))}
            className="inline-flex size-11 items-center justify-center rounded-lg border border-border bg-card hover:bg-muted">
            <ChevronLeft className="size-4" aria-hidden="true" />
          </button>
          <button type="button" onClick={() => setDia(hoje)}
            className="min-h-[44px] min-w-[96px] rounded-lg border border-border bg-card px-3 text-sm font-semibold capitalize hover:bg-muted">
            {rotuloDia}
          </button>
          <button type="button" aria-label="Próximo dia" onClick={() => setDia(d => somarDias(d, 1))}
            className="inline-flex size-11 items-center justify-center rounded-lg border border-border bg-card hover:bg-muted">
            <ChevronRight className="size-4" aria-hidden="true" />
          </button>
        </div>
        <div className="flex gap-1 rounded-lg border border-border bg-card p-1" role="tablist" aria-label="Turno">
          {TURNOS.map(t => (
            <button key={t.id} type="button" role="tab" aria-selected={turno === t.id} onClick={() => setTurno(t.id)}
              className={cn('min-h-[40px] rounded-md px-3 text-sm font-medium', turno === t.id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}>
              {t.rotulo} <span className="hidden text-xs opacity-80 sm:inline">{t.faixa}</span>
            </button>
          ))}
        </div>
      </div>

      <section aria-label="Resumo do turno" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          { rotulo: 'Rotina concluída', valor: resumo.concluida === null ? '—' : `${resumo.concluida}%` },
          ...(mapa?.ve_medicacao ? [{ rotulo: 'Medicação no horário', valor: resumo.medicacao === null ? '—' : `${resumo.medicacao}%` }] : []),
          { rotulo: 'Com ressalva', valor: String(resumo.ressalvas) },
          { rotulo: 'Atrasados', valor: String(resumo.atrasados) },
        ].map(c => (
          <div key={c.rotulo} className="rounded-card border border-border bg-card p-3">
            <p className="text-xs font-medium text-muted-foreground">{c.rotulo}</p>
            <p className="mt-1 font-display text-2xl text-brand-ink">{c.valor}</p>
          </div>
        ))}
      </section>

      <div className="flex flex-col gap-2 sm:flex-row">
        <label className="relative flex-1">
          <span className="sr-only">Buscar por nome ou quarto</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <input type="search" value={busca} onChange={e => setBusca(e.target.value)} placeholder="Buscar por nome ou quarto"
            className="min-h-[44px] w-full rounded-lg border border-border bg-card pl-9 pr-3 text-sm" />
        </label>
        <label className="sm:w-56">
          <span className="sr-only">Filtrar por ala</span>
          <select value={ala} onChange={e => setAla(e.target.value)} aria-label="Filtrar por ala"
            className="min-h-[44px] w-full rounded-lg border border-border bg-card px-3 text-sm">
            <option value="">Todas as alas</option>
            {alas.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
      </div>

      {erro && <Alert variant="error">{erro}</Alert>}
      {carregando && !mapa && <p className="text-sm text-muted-foreground">Carregando a rotina…</p>}

      {mapa && (
        linhas.length === 0 ? (
          <p className="rounded-card border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
            Nenhum residente encontrado.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-card border border-border bg-card">
            <table className="w-full min-w-max border-collapse text-sm">
              <caption className="sr-only">Mapa da rotina do turno: uma linha por residente e uma coluna por horário</caption>
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th scope="col" className="sticky left-0 z-10 bg-card px-3 py-2 font-semibold">Residente</th>
                  {colunas.map(h => (
                    <th key={h} scope="col" className={cn('px-2 py-2 text-center font-semibold', h === colunaAgora && 'bg-primary/10 text-primary')}>
                      {h}{h === colunaAgora && <span className="sr-only">{' (agora)'}</span>}
                    </th>
                  ))}
                  <th scope="col" className="px-3 py-2 font-semibold">Progresso</th>
                </tr>
              </thead>
              <tbody>
                {linhas.map(l => (
                  <tr key={l.id} className="border-b border-border last:border-0">
                    <th scope="row" className="sticky left-0 z-10 bg-card px-3 py-2 text-left font-normal">
                      <Link to={`/residentes/${l.id}?aba=monitoramento`} className="font-semibold text-foreground hover:underline">{l.nome}</Link>
                      {l.local && <span className="block text-xs text-muted-foreground">{l.local}</span>}
                    </th>
                    {colunas.map(h => {
                      const doHorario = l.itens.filter(i => horaDe(i.previsto_em) === h)
                      const s = piorSituacao(doHorario)
                      const detalhe = doHorario.map(i => `${i.descricao}: ${ROTULO_SITUACAO[i.situacao]}`).join('; ')
                      return (
                        <td key={h} className={cn('px-1 py-1 text-center', h === colunaAgora && 'bg-primary/5')}>
                          <span
                            title={detalhe || ROTULO_SITUACAO[s]}
                            aria-label={`${h}: ${detalhe || ROTULO_SITUACAO[s]}`}
                            data-situacao={s}
                            className={cn('inline-flex size-9 items-center justify-center rounded-md border text-sm font-semibold', ESTILO[s])}
                          >
                            {SIMBOLO[s]}
                          </span>
                        </td>
                      )
                    })}
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-20 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                          <div className="h-full rounded-full bg-primary" style={{ width: `${l.resumo.concluida ?? 0}%` }} />
                        </div>
                        <span className="text-xs text-muted-foreground">{l.resumo.concluida === null ? 'Sem rotina' : `${l.resumo.concluida}%`}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      <ul aria-label="Legenda" className="flex flex-wrap gap-3 text-xs text-muted-foreground">
        {(['concluido', 'ressalva', 'atrasado', 'pendente', 'nao_se_aplica'] as SituacaoMapa[]).map(s => (
          <li key={s} className="flex items-center gap-1.5">
            <span className={cn('inline-flex size-5 items-center justify-center rounded border text-[11px]', ESTILO[s])}>{SIMBOLO[s]}</span>
            {ROTULO_SITUACAO[s]}
          </li>
        ))}
      </ul>
    </PaginaModulo>
  )
}

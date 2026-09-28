import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { MapPin, Plus, RefreshCw, UserRound } from 'lucide-react'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { api, formatDateTime, mensagemDeErro } from '../services/api'
import {
  escalaApi, ROTULO_ESTADO_ESCALA, ROTULO_TIPO_AREA, rotuloLeitoDaArea,
  type Area, type Escala as EscalaPlanejada, type EscalaAgora, type EscalaDia, type EstadoEscala, type TipoArea, type Turno,
} from '../services/escala'
import { Button } from '../components/ui/button'
import { Alert, Skeleton } from '../components/ui/feedback'
import { EmptyState, ErrorState } from '../components/ui/states'
import { cn } from '../lib/utils'

type Aba = 'agora' | 'dia' | 'areas' | 'turnos'
type Carga<T> = { status: 'carregando' } | { status: 'ok'; dados: T } | { status: 'erro'; mensagem: string }

interface LeitoOpcao { id: string; unidade: string | null; quarto: string; leito: string }

const CAMPO = 'block min-h-[44px] w-full rounded-md border border-border bg-card px-3 text-sm'

function useCarga<T>(buscar: () => Promise<T>) {
  const [carga, setCarga] = useState<Carga<T>>({ status: 'carregando' })
  const recarregar = useCallback(async () => {
    try {
      setCarga({ status: 'ok', dados: await buscar() })
    } catch (e) {
      setCarga({ status: 'erro', mensagem: mensagemDeErro(e, 'Não foi possível carregar.') })
    }
  }, [buscar])
  useEffect(() => { void recarregar() }, [recarregar])
  return [carga, recarregar] as const
}

/**
 * Escala (#120): quem responde por qual área agora, as áreas operacionais e
 * os turnos. Responsabilidade não é permissão — aqui não se concede acesso a
 * nada; isso continua sendo o perfil de cada pessoa.
 */
export function Escala() {
  const { pode } = usePermissoesOuPadrao()
  const gerenciar = pode('escala:gerenciar')
  const [aba, setAba] = useState<Aba>('agora')
  const abas: { id: Aba; rotulo: string }[] = [
    { id: 'agora', rotulo: 'Agora' },
    { id: 'dia', rotulo: 'Dia' },
    { id: 'areas', rotulo: 'Áreas' },
    { id: 'turnos', rotulo: 'Turnos' },
  ]

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">Escala</h1>
        <p className="text-sm text-muted-foreground">Quem responde por cada área agora, a escala do dia (previsto × efetivo), as áreas e os turnos.</p>
      </div>
      <div role="tablist" aria-label="Escala" className="flex gap-1 rounded-lg bg-muted p-1">
        {abas.map(x => (
          <button
            key={x.id}
            role="tab"
            aria-selected={aba === x.id}
            onClick={() => setAba(x.id)}
            className={cn('min-h-[44px] flex-1 rounded-md px-3 text-sm font-medium sm:flex-none',
              aba === x.id ? 'bg-card text-foreground shadow-sm' : 'text-slate-600 hover:text-foreground')}
          >
            {x.rotulo}
          </button>
        ))}
      </div>
      {aba === 'agora' && <Agora gerenciar={gerenciar} />}
      {aba === 'dia' && <Dia gerenciar={gerenciar} podeEquipe={pode('funcionarios:ler')} />}
      {aba === 'areas' && <Areas gerenciar={gerenciar} podeLeitos={pode('quartos_leitos:ler')} />}
      {aba === 'turnos' && <Turnos gerenciar={gerenciar} />}
    </div>
  )
}

function Carregando() {
  return <div className="space-y-3" aria-label="Carregando">{[0, 1].map(i => <Skeleton key={i} className="h-20 w-full" />)}</div>
}

function Agora({ gerenciar }: { gerenciar: boolean }) {
  const [carga, recarregar] = useCarga<EscalaAgora>(escalaApi.agora)
  const [erro, setErro] = useState('')
  if (carga.status === 'carregando') return <Carregando />
  if (carga.status === 'erro') return <ErrorState title="Não foi possível carregar a escala" description={carga.mensagem} onRetry={recarregar} />
  const { areas, plantoes_sem_area } = carga.dados
  const emAndamento = [...plantoes_sem_area, ...areas.flatMap(a => a.responsaveis.map(r => ({ id: r.plantao_id, funcionario_nome: r.funcionario_nome, funcionario_id: r.funcionario_id })))]
  const plantoes = Array.from(new Map(emAndamento.map(p => [p.id, p])).values())

  async function atribuir(areaId: string, paraPlantaoId: string, deFuncionarioId?: string) {
    setErro('')
    try {
      await escalaApi.transferir({ area_id: areaId, para_plantao_id: paraPlantaoId, ...(deFuncionarioId ? { de_funcionario_id: deFuncionarioId } : {}) })
      await recarregar()
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível atribuir a área.'))
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button variant="outline" onClick={recarregar}><RefreshCw aria-hidden="true" /> Atualizar</Button>
      </div>
      {erro && <Alert variant="error">{erro}</Alert>}
      {areas.length === 0 ? (
        <EmptyState icon={MapPin} title="Nenhuma área ativa" description="Cadastre as áreas da ILPI (alas, setores) na aba Áreas." />
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {areas.map(({ area, responsaveis, residentes }) => (
            <li key={area.id} className="rounded-card border border-border bg-card p-4 shadow-card">
              <section aria-label={`Área ${area.nome}`} className="space-y-2">
                <div className="flex items-baseline justify-between gap-2">
                  <h2 className="font-display text-base font-semibold text-foreground">{area.nome}</h2>
                  <span className="text-xs text-muted-foreground">
                    {ROTULO_TIPO_AREA[area.tipo]} · {area.leitos.length} {area.leitos.length === 1 ? 'leito' : 'leitos'}
                    {residentes !== null && ` · ${residentes} ${residentes === 1 ? 'residente' : 'residentes'}`}
                  </span>
                </div>
                {responsaveis.length === 0 ? (
                  <p className="text-sm font-medium text-orange-800">Ninguém responde por esta área agora.</p>
                ) : (
                  <ul className="space-y-1">
                    {responsaveis.map(r => (
                      <li key={r.id} className="flex items-center gap-2 text-sm text-slate-700">
                        <UserRound className="size-4 text-muted-foreground" aria-hidden="true" />
                        <span className="font-medium">{r.funcionario_nome}</span>
                        <span className="text-xs text-muted-foreground">desde {formatDateTime(r.inicio_em)}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {gerenciar && plantoes.length > 0 && (
                  <AtribuirArea
                    plantoes={plantoes.filter(p => !responsaveis.some(r => r.plantao_id === p.id))}
                    responsaveis={responsaveis.map(r => ({ id: r.funcionario_id, nome: r.funcionario_nome }))}
                    onAtribuir={(para, de) => atribuir(area.id, para, de)}
                  />
                )}
              </section>
            </li>
          ))}
        </ul>
      )}
      {plantoes_sem_area.length > 0 && (
        <section aria-label="Em plantão sem área" className="space-y-2">
          <h2 className="font-display text-base font-semibold text-foreground">Em plantão sem área</h2>
          <ul className="space-y-1 text-sm text-slate-700">
            {plantoes_sem_area.map(p => (
              <li key={p.id}>{p.funcionario_nome}{p.turno_nome ? ` · ${p.turno_nome}` : ''} · desde {formatDateTime(p.inicio_em)}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function AtribuirArea({ plantoes, responsaveis, onAtribuir }: {
  plantoes: { id: string; funcionario_nome: string }[]
  responsaveis: { id: string; nome: string }[]
  onAtribuir: (paraPlantaoId: string, deFuncionarioId?: string) => void
}) {
  const [para, setPara] = useState('')
  const [de, setDe] = useState('')
  if (plantoes.length === 0) return null
  return (
    <form
      className="flex flex-col gap-2 border-t border-border pt-2 sm:flex-row sm:items-end"
      onSubmit={e => { e.preventDefault(); if (para) onAtribuir(para, de || undefined) }}
    >
      <label className="flex-1 space-y-1 text-xs">
        <span className="text-muted-foreground">Passa a responder</span>
        <select aria-label="Profissional que passa a responder" value={para} onChange={e => setPara(e.target.value)} className={CAMPO}>
          <option value="">Escolha…</option>
          {plantoes.map(p => <option key={p.id} value={p.id}>{p.funcionario_nome}</option>)}
        </select>
      </label>
      {responsaveis.length > 0 && (
        <label className="flex-1 space-y-1 text-xs">
          <span className="text-muted-foreground">No lugar de</span>
          <select aria-label="Profissional que deixa a área" value={de} onChange={e => setDe(e.target.value)} className={CAMPO}>
            <option value="">Ninguém (reforço)</option>
            {responsaveis.map(r => <option key={r.id} value={r.id}>{r.nome}</option>)}
          </select>
        </label>
      )}
      <Button type="submit" variant="outline" disabled={!para} className="min-h-[44px]">Atribuir</Button>
    </form>
  )
}

function Areas({ gerenciar, podeLeitos }: { gerenciar: boolean; podeLeitos: boolean }) {
  const [carga, recarregar] = useCarga<Area[]>(escalaApi.areas)
  const [leitos, setLeitos] = useState<LeitoOpcao[]>([])
  const [nome, setNome] = useState('')
  const [tipo, setTipo] = useState<TipoArea>('ala')
  const [erro, setErro] = useState('')

  useEffect(() => {
    if (!gerenciar || !podeLeitos) return
    api.get<LeitoOpcao[]>('/quartos_leitos/', { params: { limit: 500 } }).then(r => setLeitos(r.data || [])).catch(() => setLeitos([]))
  }, [gerenciar, podeLeitos])

  async function acao(f: () => Promise<unknown>, falha: string) {
    setErro('')
    try {
      await f()
      await recarregar()
    } catch (e) {
      setErro(mensagemDeErro(e, falha))
    }
  }

  async function criar(e: FormEvent) {
    e.preventDefault()
    if (!nome.trim()) return
    await acao(() => escalaApi.criarArea({ nome: nome.trim(), tipo }), 'Não foi possível criar a área.')
    setNome('')
  }

  if (carga.status === 'carregando') return <Carregando />
  if (carga.status === 'erro') return <ErrorState title="Não foi possível carregar as áreas" description={carga.mensagem} onRetry={recarregar} />
  const vinculados = new Set(carga.dados.flatMap(a => a.leitos.map(l => l.quarto_leito_id)))
  const livres = leitos.filter(l => !vinculados.has(l.id))

  return (
    <div className="space-y-4">
      {erro && <Alert variant="error">{erro}</Alert>}
      {gerenciar && (
        <form onSubmit={criar} aria-label="Nova área" className="flex flex-col gap-2 rounded-card border border-border bg-card p-4 shadow-card sm:flex-row sm:items-end">
          <label className="flex-1 space-y-1 text-sm">
            <span className="font-medium text-foreground">Nome da área</span>
            <input value={nome} onChange={e => setNome(e.target.value)} placeholder="Ex.: Ala B" className={CAMPO} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="font-medium text-foreground">Tipo</span>
            <select value={tipo} onChange={e => setTipo(e.target.value as TipoArea)} className={CAMPO}>
              {(Object.keys(ROTULO_TIPO_AREA) as TipoArea[]).map(t => <option key={t} value={t}>{ROTULO_TIPO_AREA[t]}</option>)}
            </select>
          </label>
          <Button type="submit" className="min-h-[44px]"><Plus aria-hidden="true" /> Criar área</Button>
        </form>
      )}
      {carga.dados.length === 0 ? (
        <EmptyState icon={MapPin} title="Nenhuma área cadastrada" description="Áreas organizam os leitos em alas, setores ou grupos para o plantão." />
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {carga.dados.map(a => (
            <li key={a.id} className="rounded-card border border-border bg-card p-4 shadow-card">
              <section aria-label={`Área ${a.nome}`} className="space-y-2">
                <div className="flex items-baseline justify-between gap-2">
                  <h2 className="font-display text-base font-semibold text-foreground">{a.nome}</h2>
                  <span className="text-xs text-muted-foreground">{ROTULO_TIPO_AREA[a.tipo]}{a.situacao === 'inativa' ? ' · inativa' : ''}</span>
                </div>
                {a.leitos.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Nenhum leito nesta área.</p>
                ) : (
                  <ul className="space-y-1">
                    {a.leitos.map(l => (
                      <li key={l.vinculo_id} className="flex items-center justify-between gap-2 text-sm text-slate-700">
                        <span>{rotuloLeitoDaArea(l)}{l.ocupado ? '' : ' · livre'}</span>
                        {gerenciar && (
                          <button
                            type="button"
                            className="min-h-[36px] text-xs font-medium text-red-700 hover:underline"
                            onClick={() => acao(() => escalaApi.removerLeito(a.id, l.quarto_leito_id), 'Não foi possível remover o leito.')}
                          >
                            Remover
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                {gerenciar && a.situacao === 'ativa' && livres.length > 0 && (
                  <select
                    aria-label={`Adicionar leito à área ${a.nome}`}
                    value=""
                    onChange={e => e.target.value && acao(() => escalaApi.vincularLeito(a.id, e.target.value), 'Não foi possível adicionar o leito.')}
                    className={CAMPO}
                  >
                    <option value="">Adicionar leito…</option>
                    {livres.map(l => <option key={l.id} value={l.id}>{rotuloLeitoDaArea(l)}</option>)}
                  </select>
                )}
                {gerenciar && (
                  <button
                    type="button"
                    className="min-h-[36px] text-xs font-medium text-primary hover:underline"
                    onClick={() => acao(() => escalaApi.atualizarArea(a.id, { situacao: a.situacao === 'ativa' ? 'inativa' : 'ativa' }), 'Não foi possível alterar a área.')}
                  >
                    {a.situacao === 'ativa' ? 'Inativar área' : 'Reativar área'}
                  </button>
                )}
              </section>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Turnos({ gerenciar }: { gerenciar: boolean }) {
  const [carga, recarregar] = useCarga<Turno[]>(escalaApi.turnos)
  const [form, setForm] = useState({ nome: '', hora_inicio: '07:00', hora_fim: '19:00' })
  const [erro, setErro] = useState('')

  async function criar(e: FormEvent) {
    e.preventDefault()
    setErro('')
    try {
      await escalaApi.criarTurno({ ...form, nome: form.nome.trim() })
      setForm({ nome: '', hora_inicio: '07:00', hora_fim: '19:00' })
      await recarregar()
    } catch (err) {
      setErro(mensagemDeErro(err, 'Não foi possível criar o turno.'))
    }
  }

  if (carga.status === 'carregando') return <Carregando />
  if (carga.status === 'erro') return <ErrorState title="Não foi possível carregar os turnos" description={carga.mensagem} onRetry={recarregar} />
  return (
    <div className="space-y-4">
      {erro && <Alert variant="error">{erro}</Alert>}
      {gerenciar && (
        <form onSubmit={criar} aria-label="Novo turno" className="grid gap-2 rounded-card border border-border bg-card p-4 shadow-card sm:grid-cols-[1fr_auto_auto_auto] sm:items-end">
          <label className="space-y-1 text-sm">
            <span className="font-medium text-foreground">Nome do turno</span>
            <input value={form.nome} onChange={e => setForm({ ...form, nome: e.target.value })} placeholder="Ex.: Diurno" className={CAMPO} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="font-medium text-foreground">Início</span>
            <input type="time" value={form.hora_inicio} onChange={e => setForm({ ...form, hora_inicio: e.target.value })} className={CAMPO} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="font-medium text-foreground">Fim</span>
            <input type="time" value={form.hora_fim} onChange={e => setForm({ ...form, hora_fim: e.target.value })} className={CAMPO} />
          </label>
          <Button type="submit" disabled={!form.nome.trim()} className="min-h-[44px]"><Plus aria-hidden="true" /> Criar turno</Button>
        </form>
      )}
      {carga.dados.length === 0 ? (
        <EmptyState icon={MapPin} title="Nenhum turno cadastrado" description="Turnos (ex.: Diurno 07:00–19:00) ajudam a identificar cada plantão." />
      ) : (
        <ul className="space-y-2">
          {carga.dados.map(t => (
            <li key={t.id} className="flex items-center justify-between gap-2 rounded-card border border-border bg-card px-4 py-3 text-sm shadow-card">
              <span>
                <span className="font-medium text-foreground">{t.nome}</span>{' '}
                <span className="text-muted-foreground">{t.hora_inicio}–{t.hora_fim}{t.situacao === 'inativo' ? ' · inativo' : ''}</span>
              </span>
              {gerenciar && (
                <button
                  type="button"
                  className="min-h-[36px] text-xs font-medium text-primary hover:underline"
                  onClick={async () => {
                    setErro('')
                    try {
                      await escalaApi.atualizarTurno(t.id, { situacao: t.situacao === 'ativo' ? 'inativo' : 'ativo' })
                      await recarregar()
                    } catch (err) {
                      setErro(mensagemDeErro(err, 'Não foi possível alterar o turno.'))
                    }
                  }}
                >
                  {t.situacao === 'ativo' ? 'Inativar' : 'Reativar'}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// Classes completas: o Tailwind não enxerga nomes montados em tempo de execução.
const ESTILO_ESTADO: Record<EstadoEscala, string> = {
  prevista: 'border-border bg-muted text-slate-700',
  presente: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  realizada: 'border-border bg-muted text-slate-700',
  nao_iniciada: 'border-orange-200 bg-orange-50 text-orange-800',
  ausente: 'border-red-200 bg-red-50 text-red-800',
  substituida: 'border-sky-200 bg-sky-50 text-sky-800',
  cancelada: 'border-border bg-muted text-slate-500',
}
const HORA_LOCAL = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo' })
const hojeLocal = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Sao_Paulo' }).format(new Date())
const horario = (e: EscalaPlanejada) => `${HORA_LOCAL.format(new Date(e.inicio_previsto))}–${HORA_LOCAL.format(new Date(e.fim_previsto))}`

interface FuncionarioOpcao { id: string; nome: string; situacao: string }
type AcaoEscala = { escalaId: string; tipo: 'ausencia' | 'substituir' | 'cancelar' } | null

/** #122: escala planejada do dia × plantão real, com ausência, substituição simples e cobertura. */
function Dia({ gerenciar, podeEquipe }: { gerenciar: boolean; podeEquipe: boolean }) {
  const [dia, setDia] = useState(hojeLocal())
  const buscar = useCallback(() => escalaApi.dia(dia), [dia])
  const [carga, recarregar] = useCarga<EscalaDia>(buscar)
  const [funcionarios, setFuncionarios] = useState<FuncionarioOpcao[]>([])
  const [turnos, setTurnos] = useState<Turno[]>([])
  const [areas, setAreas] = useState<Area[]>([])
  const [nova, setNova] = useState({ funcionario_id: '', turno_id: '', area_id: '', tipo: 'regular' as 'regular' | 'cobertura' })
  const [acao, setAcao] = useState<AcaoEscala>(null)
  const [motivo, setMotivo] = useState('')
  const [substituto, setSubstituto] = useState('')
  const [erro, setErro] = useState('')

  useEffect(() => {
    if (!gerenciar) return
    escalaApi.turnos().then(t => setTurnos(t.filter(x => x.situacao === 'ativo'))).catch(() => setTurnos([]))
    escalaApi.areas().then(a => setAreas(a.filter(x => x.situacao === 'ativa'))).catch(() => setAreas([]))
    if (podeEquipe) {
      api.get<FuncionarioOpcao[]>('/funcionarios/').then(r => setFuncionarios((r.data || []).filter(f => f.situacao === 'ativo')))
        .catch(() => setFuncionarios([]))
    }
  }, [gerenciar, podeEquipe])

  async function executar(f: () => Promise<unknown>, falha: string) {
    setErro('')
    try {
      await f()
      setAcao(null)
      setMotivo('')
      setSubstituto('')
      await recarregar()
    } catch (e) {
      setErro(mensagemDeErro(e, falha))
    }
  }

  function criar(e: FormEvent) {
    e.preventDefault()
    if (!nova.funcionario_id || !nova.turno_id) return
    void executar(() => escalaApi.criarEscala({
      funcionario_id: nova.funcionario_id, turno_id: nova.turno_id, data: dia, tipo: nova.tipo,
      ...(nova.area_id ? { area_id: nova.area_id } : {}),
    }), 'Não foi possível criar a escala.')
  }

  function confirmar(e: FormEvent, escala: EscalaPlanejada) {
    e.preventDefault()
    if (!acao || motivo.trim().length < 3) return
    if (acao.tipo === 'ausencia') void executar(() => escalaApi.ausencia(escala.id, motivo.trim()), 'Não foi possível registrar a ausência.')
    if (acao.tipo === 'cancelar') void executar(() => escalaApi.cancelar(escala.id, motivo.trim()), 'Não foi possível cancelar a escala.')
    if (acao.tipo === 'substituir' && substituto) {
      void executar(() => escalaApi.substituir(escala.id, substituto, motivo.trim()), 'Não foi possível substituir.')
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <label className="space-y-1 text-sm">
          <span className="font-medium text-foreground">Dia</span>
          <input type="date" value={dia} onChange={e => e.target.value && setDia(e.target.value)} className={CAMPO} />
        </label>
        <Button variant="outline" onClick={recarregar} className="min-h-[44px]"><RefreshCw aria-hidden="true" /> Atualizar</Button>
      </div>
      {erro && <Alert variant="error">{erro}</Alert>}

      {gerenciar && (
        <form onSubmit={criar} aria-label="Nova escala" className="grid gap-2 rounded-card border border-border bg-card p-4 shadow-card sm:grid-cols-2 lg:grid-cols-5 lg:items-end">
          <label className="space-y-1 text-sm">
            <span className="font-medium text-foreground">Profissional</span>
            <select value={nova.funcionario_id} onChange={e => setNova({ ...nova, funcionario_id: e.target.value })} className={CAMPO}>
              <option value="">Escolha…</option>
              {funcionarios.map(f => <option key={f.id} value={f.id}>{f.nome}</option>)}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span className="font-medium text-foreground">Turno</span>
            <select value={nova.turno_id} onChange={e => setNova({ ...nova, turno_id: e.target.value })} className={CAMPO}>
              <option value="">Escolha…</option>
              {turnos.map(t => <option key={t.id} value={t.id}>{t.nome} ({t.hora_inicio}–{t.hora_fim})</option>)}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span className="font-medium text-foreground">Área</span>
            <select value={nova.area_id} onChange={e => setNova({ ...nova, area_id: e.target.value })} className={CAMPO}>
              <option value="">Sem área</option>
              {areas.map(a => <option key={a.id} value={a.id}>{a.nome}</option>)}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span className="font-medium text-foreground">Tipo</span>
            <select value={nova.tipo} onChange={e => setNova({ ...nova, tipo: e.target.value as 'regular' | 'cobertura' })} className={CAMPO}>
              <option value="regular">Regular</option>
              <option value="cobertura">Cobertura (extra)</option>
            </select>
          </label>
          <Button type="submit" disabled={!nova.funcionario_id || !nova.turno_id} className="min-h-[44px]">
            <Plus aria-hidden="true" /> Escalar
          </Button>
        </form>
      )}

      {carga.status === 'carregando' && <Carregando />}
      {carga.status === 'erro' && <ErrorState title="Não foi possível carregar a escala do dia" description={carga.mensagem} onRetry={recarregar} />}
      {carga.status === 'ok' && (
        carga.dados.escalas.length === 0 && carga.dados.coberturas_sem_escala.length === 0 ? (
          <EmptyState icon={UserRound} title="Ninguém escalado neste dia" description="Monte a escala do dia para comparar o previsto com quem de fato trabalhou." />
        ) : (
          <div className="space-y-4">
            <ul className="space-y-2" aria-label="Escala do dia">
              {carga.dados.escalas.map(e => {
                const editavel = gerenciar && e.plantao_id === null && (e.estado === 'prevista' || e.estado === 'nao_iniciada')
                const substituivel = gerenciar && e.plantao_id === null && (editavel || e.estado === 'ausente')
                return (
                  <li key={e.id} className="rounded-card border border-border bg-card p-4 shadow-card">
                    <section aria-label={'Escala de ' + e.funcionario_nome} className="space-y-2">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="font-medium text-foreground">
                          {e.funcionario_nome}
                          {e.tipo !== 'regular' && (
                            <span className="ml-2 text-xs font-normal text-muted-foreground">{e.tipo === 'substituicao' ? 'substituição' : 'cobertura'}</span>
                          )}
                        </p>
                        <span className={cn('rounded-full border px-2.5 py-0.5 text-xs font-semibold', ESTILO_ESTADO[e.estado])}>{ROTULO_ESTADO_ESCALA[e.estado]}</span>
                      </div>
                      <p className="text-sm text-slate-700">{[e.turno_nome, horario(e), e.area_nome].filter(Boolean).join(' · ')}</p>
                      {e.motivo && <p className="text-xs text-muted-foreground">Motivo: {e.motivo}</p>}
                      {e.substituto_nome && <p className="text-xs text-muted-foreground">Substituído(a) por {e.substituto_nome}</p>}
                      {(editavel || substituivel) && acao?.escalaId !== e.id && (
                        <div className="flex flex-wrap gap-3">
                          {editavel && (
                            <button type="button" className="min-h-[36px] text-xs font-medium text-primary hover:underline" onClick={() => setAcao({ escalaId: e.id, tipo: 'ausencia' })}>
                              Registrar ausência
                            </button>
                          )}
                          {substituivel && (
                            <button type="button" className="min-h-[36px] text-xs font-medium text-primary hover:underline" onClick={() => setAcao({ escalaId: e.id, tipo: 'substituir' })}>
                              Substituir
                            </button>
                          )}
                          {editavel && (
                            <button type="button" className="min-h-[36px] text-xs font-medium text-red-700 hover:underline" onClick={() => setAcao({ escalaId: e.id, tipo: 'cancelar' })}>
                              Cancelar escala
                            </button>
                          )}
                        </div>
                      )}
                      {acao?.escalaId === e.id && (
                        <form onSubmit={ev => confirmar(ev, e)} aria-label="Confirmar alteração da escala" className="grid gap-2 border-t border-border pt-2 sm:grid-cols-[1fr_1fr_auto_auto] sm:items-end">
                          {acao.tipo === 'substituir' && (
                            <label className="space-y-1 text-xs">
                              <span className="text-muted-foreground">Substituto</span>
                              <select value={substituto} onChange={ev => setSubstituto(ev.target.value)} className={CAMPO}>
                                <option value="">Escolha…</option>
                                {funcionarios.filter(f => f.id !== e.funcionario_id).map(f => <option key={f.id} value={f.id}>{f.nome}</option>)}
                              </select>
                            </label>
                          )}
                          <label className="space-y-1 text-xs">
                            <span className="text-muted-foreground">Motivo</span>
                            <input value={motivo} onChange={ev => setMotivo(ev.target.value)} placeholder="Ex.: atestado" className={CAMPO} />
                          </label>
                          <Button type="submit" disabled={motivo.trim().length < 3 || (acao.tipo === 'substituir' && !substituto)} className="min-h-[44px]">
                            Confirmar
                          </Button>
                          <Button type="button" variant="outline" onClick={() => setAcao(null)} className="min-h-[44px]">Voltar</Button>
                        </form>
                      )}
                    </section>
                  </li>
                )
              })}
            </ul>
            {carga.dados.coberturas_sem_escala.length > 0 && (
              <section aria-label="Cobertura sem escala" className="space-y-2">
                <h2 className="font-display text-base font-semibold text-foreground">Cobertura sem escala</h2>
                <ul className="space-y-1 text-sm text-slate-700">
                  {carga.dados.coberturas_sem_escala.map(p => (
                    <li key={p.id}>
                      {p.funcionario_nome} · desde {formatDateTime(p.inicio_em)}
                      {p.situacao === 'encerrado' && p.fim_em ? ' até ' + formatDateTime(p.fim_em) : ''}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        )
      )}
    </div>
  )
}

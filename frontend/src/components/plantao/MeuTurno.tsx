import { useCallback, useEffect, useRef, useState } from 'react'
import { Clock, LogIn, LogOut, MapPin } from 'lucide-react'
import { formatDateTime, mensagemDeErro } from '../../services/api'
import { escalaApi, plantoesApi, type Area, type PlantaoAtual, type Turno } from '../../services/escala'
import { Button } from '../ui/button'
import { Alert } from '../ui/feedback'
import { cn } from '../../lib/utils'

type Carga = { status: 'carregando' } | { status: 'ok'; atual: PlantaoAtual } | { status: 'erro'; mensagem: string }

/**
 * Início e fim do PRÓPRIO plantão (#120). O profissional escolhe por quais
 * áreas responde; isso não abre nenhuma tela nova (RBAC continua no backend).
 * Sem `plantao:registrar`, o cartão não aparece.
 */
export function MeuTurno({ onMudou }: { onMudou?: (atual: PlantaoAtual) => void }) {
  const [carga, setCarga] = useState<Carga>({ status: 'carregando' })
  const [areas, setAreas] = useState<Area[]>([])
  const [turnos, setTurnos] = useState<Turno[]>([])
  const [escolhidas, setEscolhidas] = useState<string[]>([])
  const [turnoId, setTurnoId] = useState('')
  const [salvando, setSalvando] = useState(false)
  const [erro, setErro] = useState('')

  // Callback do pai sem entrar nas dependências (evita recarga em laço com função inline).
  const aoMudar = useRef(onMudou)
  aoMudar.current = onMudou

  const carregar = useCallback(async () => {
    try {
      const atual = await plantoesApi.atual()
      setCarga({ status: 'ok', atual })
      aoMudar.current?.(atual)
      if (atual.pode_registrar && !atual.plantao) {
        // Áreas exigem escala:ler; sem ela o plantão começa sem área (o gestor atribui depois).
        const [a, t] = await Promise.all([escalaApi.areas().catch(() => [] as Area[]), escalaApi.turnos().catch(() => [] as Turno[])])
        setAreas(a.filter(x => x.situacao === 'ativa'))
        setTurnos(t.filter(x => x.situacao === 'ativo'))
      }
    } catch (e) {
      setCarga({ status: 'erro', mensagem: mensagemDeErro(e, 'Não foi possível consultar o seu plantão.') })
    }
  }, [])

  useEffect(() => { void carregar() }, [carregar])

  if (carga.status === 'carregando') return null
  // Aviso discreto: falhar em consultar o turno não é falha da lista de pendências abaixo.
  if (carga.status === 'erro') return <Alert variant="warning">{carga.mensagem}</Alert>
  const { atual } = carga
  if (!atual.pode_registrar && !atual.plantao) return null

  async function iniciar(escalaId?: string) {
    setSalvando(true)
    setErro('')
    try {
      // #122: a partir da própria escala, área e turno vêm dela; sem escala é cobertura.
      await plantoesApi.iniciar(escalaId
        ? { area_ids: [], escala_id: escalaId }
        : { area_ids: escolhidas, ...(turnoId ? { turno_id: turnoId } : {}) })
      setEscolhidas([])
      await carregar()
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível iniciar o plantão.'))
    } finally {
      setSalvando(false)
    }
  }

  async function encerrar(id: string) {
    setSalvando(true)
    setErro('')
    try {
      await plantoesApi.encerrar(id)
      await carregar()
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível encerrar o plantão.'))
    } finally {
      setSalvando(false)
    }
  }

  const plantao = atual.plantao
  const semEscolhas = !plantao && (atual.escalas_pendentes ?? []).length === 0 && areas.length === 0 && turnos.length === 0

  return (
    <section aria-label="Meu turno" className={cn('rounded-card border border-border bg-card shadow-card', semEscolhas ? 'px-4 py-3' : 'p-4 sm:p-5')}>
      {plantao ? (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0 space-y-1">
            <p className="font-display text-base font-semibold text-foreground">
              Plantão em andamento{plantao.turno_nome ? ` · ${plantao.turno_nome}` : ''}
            </p>
            <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Clock className="size-4" aria-hidden="true" /> Desde {formatDateTime(plantao.inicio_em)}
            </p>
            <p className="flex items-center gap-1.5 text-sm text-slate-700">
              <MapPin className="size-4 text-muted-foreground" aria-hidden="true" />
              {plantao.responsabilidades.length
                ? `Responsável por: ${plantao.responsabilidades.map(r => r.area_nome).join(', ')}`
                : 'Sem área definida — a coordenação pode atribuir.'}
            </p>
          </div>
          <Button variant="outline" onClick={() => encerrar(plantao.id)} disabled={salvando} className="min-h-[44px]">
            <LogOut aria-hidden="true" /> Encerrar plantão
          </Button>
        </div>
      ) : semEscolhas ? (
        // Nada a escolher (sem escala, área ou turno): uma linha só, texto + ação.
        <div className="flex items-center justify-between gap-3">
          <p className="font-display text-base font-semibold text-foreground">Você não está em plantão</p>
          <Button onClick={() => iniciar()} disabled={salvando} className="min-h-[44px] shrink-0">
            <LogIn aria-hidden="true" /> Iniciar plantão
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="font-display text-base font-semibold text-foreground">Você não está em plantão</p>
          {(atual.escalas_pendentes ?? []).slice(0, 1).map(e => (
            <div key={e.id} className="flex flex-col gap-2 rounded-md border border-border bg-muted/40 p-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-slate-700">
                <span className="font-medium text-foreground">Sua escala:</span>{' '}
                {[e.turno_nome, formatDateTime(e.inicio_previsto) + ' – ' + formatDateTime(e.fim_previsto), e.area_nome].filter(Boolean).join(' · ')}
              </p>
              <Button onClick={() => iniciar(e.id)} disabled={salvando} className="min-h-[44px]">
                <LogIn aria-hidden="true" /> Iniciar minha escala
              </Button>
            </div>
          ))}
          {(atual.escalas_pendentes ?? []).length > 0 && (
            <p className="text-xs text-muted-foreground">Ou inicie um plantão fora da escala (cobertura):</p>
          )}
          {areas.length > 0 && (
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium text-foreground">Por quais áreas você responde?</legend>
              <div className="flex flex-wrap gap-2">
                {areas.map(a => {
                  const marcada = escolhidas.includes(a.id)
                  return (
                    <label key={a.id} className="inline-flex min-h-[44px] cursor-pointer items-center gap-2 rounded-md border border-border px-3 text-sm">
                      <input
                        type="checkbox"
                        checked={marcada}
                        onChange={() => setEscolhidas(atual => (marcada ? atual.filter(x => x !== a.id) : [...atual, a.id]))}
                      />
                      {a.nome}
                    </label>
                  )
                })}
              </div>
            </fieldset>
          )}
          {turnos.length > 0 && (
            <label className="block space-y-1 text-sm">
              <span className="font-medium text-foreground">Turno</span>
              <select
                value={turnoId}
                onChange={e => setTurnoId(e.target.value)}
                className="block min-h-[44px] w-full rounded-md border border-border bg-card px-3 sm:w-64"
              >
                <option value="">Sem turno</option>
                {turnos.map(t => <option key={t.id} value={t.id}>{t.nome} ({t.hora_inicio}–{t.hora_fim})</option>)}
              </select>
            </label>
          )}
          <Button onClick={() => iniciar()} disabled={salvando} className="min-h-[44px]">
            <LogIn aria-hidden="true" /> Iniciar plantão
          </Button>
        </div>
      )}
      {erro && <Alert variant="error" className="mt-3">{erro}</Alert>}
    </section>
  )
}

import { useEffect, useState } from 'react'
import { History } from 'lucide-react'
import { formatDateTime, mensagemDeErro } from '../../services/api'
import { plantoesApi } from '../../services/escala'
import { listarExpirados, type AlertaExpirado } from '../../services/alertas'
import { ROTULO_RESULTADO_CUIDADO, listarRegistrosRecentes, type ExecucaoRegistrada } from '../../services/plantao'
import { usePermissoesOuPadrao } from '../../context/PermissoesContext'
import { cn } from '../../lib/utils'

// Sem plantão em andamento, "o turno" é a janela das últimas 12 h.
const JANELA_SEM_PLANTAO_MS = 12 * 60 * 60 * 1000
type Aba = 'feitos' | 'expirados'

/**
 * G5 (#198) — o que já foi feito e o que expirou no turno. Só leitura: lê as
 * execuções de cuidado e os estados de alerta encerrados como expirados; não
 * registra, corrige nem encerra nada. Carrega só quando aberto.
 */
export function FeitosExpirados({ nomes }: { nomes: Record<string, string> }) {
  const { pode } = usePermissoesOuPadrao()
  const veExpirados = pode('alertas:ler')
  const [aberto, setAberto] = useState(false)
  const [aba, setAba] = useState<Aba>('feitos')
  const [desde, setDesde] = useState<string | null>(null)
  const [feitos, setFeitos] = useState<ExecucaoRegistrada[] | null>(null)
  const [expirados, setExpirados] = useState<AlertaExpirado[] | null>(null)
  const [erro, setErro] = useState('')

  useEffect(() => {
    if (!aberto) return
    let ativo = true
    setErro('')
    ;(async () => {
      try {
        const atual = await plantoesApi.atual().catch(() => null)
        const inicio = atual?.plantao?.inicio_em ?? new Date(Date.now() - JANELA_SEM_PLANTAO_MS).toISOString()
        const [f, e] = await Promise.all([
          listarRegistrosRecentes(inicio),
          veExpirados ? listarExpirados(inicio) : Promise.resolve([] as AlertaExpirado[]),
        ])
        if (!ativo) return
        setDesde(inicio)
        setFeitos(f)
        setExpirados(e)
      } catch (err) {
        if (ativo) setErro(mensagemDeErro(err, 'Não foi possível carregar o histórico do turno.'))
      }
    })()
    return () => { ativo = false }
  }, [aberto, veExpirados])

  const abas: { valor: Aba; rotulo: string; total: number | undefined }[] = [
    { valor: 'feitos', rotulo: 'Feitos', total: feitos?.length },
    ...(veExpirados ? [{ valor: 'expirados' as Aba, rotulo: 'Expirados', total: expirados?.length }] : []),
  ]

  return (
    <section aria-label="Feitos e expirados do turno" className="space-y-2">
      <button
        type="button"
        aria-expanded={aberto}
        onClick={() => setAberto(a => !a)}
        className="inline-flex min-h-[44px] w-full items-center justify-center gap-2 rounded-lg border border-border bg-card px-3 text-sm font-medium text-foreground hover:bg-muted"
      >
        <History className="size-4" aria-hidden="true" />
        {veExpirados ? 'Feitos/Expirados do turno' : 'Feitos do turno'}
      </button>
      {aberto && (
        <div className="card space-y-3 p-4">
          {abas.length > 1 && (
            <div className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1" role="tablist">
              {abas.map(opcao => (
                <button
                  key={opcao.valor}
                  role="tab"
                  aria-selected={aba === opcao.valor}
                  onClick={() => setAba(opcao.valor)}
                  className={cn(
                    'min-h-[44px] rounded-md px-2 text-sm font-medium',
                    aba === opcao.valor ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {opcao.rotulo}{opcao.total !== undefined ? ` (${opcao.total})` : ''}
                </button>
              ))}
            </div>
          )}
          {desde && <p className="text-xs text-muted-foreground">Desde {formatDateTime(desde)}</p>}
          {erro ? (
            <p role="alert" className="text-sm text-critico-texto">{erro}</p>
          ) : feitos === null ? (
            <p className="text-sm text-muted-foreground">Carregando…</p>
          ) : aba === 'feitos' || !veExpirados ? (
            feitos.length === 0 ? <p className="text-sm text-muted-foreground">Nenhum cuidado registrado neste turno</p> : (
              <ul className="divide-y divide-border">
                {feitos.map(r => (
                  <li key={r.id} className={cn('py-2 text-sm', r.estornado_em && 'text-muted-foreground line-through')}>
                    <span className="font-medium">{r.descricao || 'Cuidado'}</span>
                    {' · '}{nomes[r.residente_id] || 'Residente'}
                    {' · '}{ROTULO_RESULTADO_CUIDADO[r.resultado]}
                    <span className="block text-xs text-muted-foreground">
                      {formatDateTime(r.ocorrido_em)}{r.executor_nome ? ` · ${r.executor_nome}` : ''}{r.estornado_em ? ' · corrigido' : ''}
                    </span>
                  </li>
                ))}
              </ul>
            )
          ) : (expirados ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">Nada expirou neste turno</p>
          ) : (
            <ul className="divide-y divide-border">
              {(expirados ?? []).map(e => (
                <li key={e.id} className="py-2 text-sm">
                  <span className="font-medium">{e.regra === 'doses_sem_registro' ? 'Doses sem registro' : 'Cuidados sem registro'}</span>
                  {' · '}{(e.residente_id && nomes[e.residente_id]) || 'Residente'}
                  <span className="block text-xs text-muted-foreground">
                    Expirou {formatDateTime(e.encerrado_em)}{e.por_nome ? ` · assumido por ${e.por_nome}` : ''}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

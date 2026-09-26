import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, Info, RefreshCw } from 'lucide-react'
import { mensagemDeErro } from '../services/api'
import {
  CATEGORIAS, GRAVIDADES, LIMIARES, listarAlertas, ROTULO_CATEGORIA, ROTULO_GRAVIDADE,
  type Categoria, type CentralAlertas,
} from '../services/alertas'
import { ESTILO_GRAVIDADE, ItemAlerta } from '../components/alertas/ItemAlerta'
import { Button } from '../components/ui/button'
import { Skeleton } from '../components/ui/feedback'
import { EmptyState, ErrorState } from '../components/ui/states'
import { cn } from '../lib/utils'

type Carga = { status: 'carregando' } | { status: 'ok'; dados: CentralAlertas } | { status: 'proibido' } | { status: 'erro'; mensagem: string }
type Aba = Categoria | 'todas'

const HORA = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo' })

/**
 * Central de alertas do gestor (#107). Substitui o placeholder de /alertas.
 *
 * Só leitura: cada alerta é calculado agora a partir da fonte oficial e some
 * quando o problema é resolvido lá — por isso a única ação é "Resolver em …".
 */
export function Alertas() {
  const [carga, setCarga] = useState<Carga>({ status: 'carregando' })
  const [aba, setAba] = useState<Aba>('todas')

  const carregar = useCallback(async () => {
    setCarga(atual => (atual.status === 'ok' ? atual : { status: 'carregando' }))
    try {
      setCarga({ status: 'ok', dados: await listarAlertas() })
    } catch (e: any) {
      if (e?.response?.status === 403) setCarga({ status: 'proibido' })
      else setCarga({ status: 'erro', mensagem: mensagemDeErro(e, 'Não foi possível carregar os alertas.') })
    }
  }, [])

  useEffect(() => { carregar() }, [carregar])

  const dados = carga.status === 'ok' ? carga.dados : null
  const visiveis = (dados?.alertas ?? []).filter(a => aba === 'todas' || a.categoria === aba)
  const contagemDa = (id: Aba) => (dados?.alertas ?? []).filter(a => id === 'todas' || a.categoria === id).length

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Alertas</h1>
          <p className="text-sm text-muted-foreground">
            O que precisa da sua atenção agora. Cada alerta some sozinho quando o problema é resolvido na tela de origem.
          </p>
        </div>
        {carga.status === 'ok' && (
          <Button variant="outline" onClick={carregar}>
            <RefreshCw aria-hidden="true" /> Atualizar
          </Button>
        )}
      </div>

      {carga.status === 'carregando' && (
        <div className="space-y-3" aria-label="Carregando alertas">
          {[0, 1, 2].map(i => <Skeleton key={i} className="h-20 w-full" />)}
        </div>
      )}
      {carga.status === 'proibido' && (
        <ErrorState title="Sem acesso aos alertas" description="Os alertas são do Administrador da ILPI. Se precisar, procure a administração." />
      )}
      {carga.status === 'erro' && (
        <ErrorState title="Não foi possível carregar os alertas" description={`${carga.mensagem} Isso não significa que não há pendências.`} onRetry={carregar} />
      )}

      {dados && (
        <>
          <ul aria-label="Resumo por gravidade" className="flex flex-wrap gap-2">
            {GRAVIDADES.map(g => (
              <li key={g} className={cn('inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-semibold', ESTILO_GRAVIDADE[g].ficha)}>
                <span aria-hidden="true" className={cn('size-2 rounded-full', ESTILO_GRAVIDADE[g].ponto)} />
                {ROTULO_GRAVIDADE[g]}: <span className="tabular-nums">{dados.contagem[g]}</span>
              </li>
            ))}
          </ul>

          <div role="tablist" aria-label="Categoria" className="flex flex-wrap gap-1 rounded-lg bg-muted p-1">
            {(['todas', ...CATEGORIAS] as Aba[]).map(id => (
              <button
                key={id}
                role="tab"
                aria-selected={aba === id}
                onClick={() => setAba(id)}
                className={cn(
                  'min-h-[40px] rounded-md px-3 text-sm font-medium transition-colors',
                  aba === id ? 'bg-card text-foreground shadow-sm' : 'text-slate-600 hover:text-foreground',
                )}
              >
                {id === 'todas' ? 'Todas' : ROTULO_CATEGORIA[id]} <span className="text-xs text-muted-foreground">({contagemDa(id)})</span>
              </button>
            ))}
          </div>

          {visiveis.length === 0 ? (
            <EmptyState
              icon={CheckCircle2}
              title={aba === 'todas' ? 'Nada pedindo atenção agora' : 'Nada nesta categoria'}
              description={aba === 'todas' ? 'Quando algo ficar pendente, vencer ou sair do combinado, aparece aqui.' : 'Troque a categoria para ver os outros alertas.'}
            />
          ) : (
            <div className="space-y-6">
              {GRAVIDADES.map(g => {
                const doGrupo = visiveis.filter(a => a.gravidade === g)
                if (doGrupo.length === 0) return null
                return (
                  <section key={g} aria-label={`${ROTULO_GRAVIDADE[g]} (${doGrupo.length})`} className="space-y-2">
                    <h2 className="flex items-center gap-2 font-display text-base font-semibold text-foreground">
                      <span aria-hidden="true" className={cn('size-2.5 rounded-full', ESTILO_GRAVIDADE[g].ponto)} />
                      {ROTULO_GRAVIDADE[g]} <span className="text-sm font-medium text-muted-foreground">({doGrupo.length})</span>
                    </h2>
                    <ul className="space-y-2">
                      {doGrupo.map(a => <li key={a.id}><ItemAlerta alerta={a} /></li>)}
                    </ul>
                  </section>
                )
              })}
            </div>
          )}

          <details className="rounded-card border border-border bg-card px-4 py-3 text-sm shadow-card sm:px-5">
            <summary className="flex min-h-[32px] cursor-pointer items-center gap-2 font-medium text-foreground">
              <Info className="size-4 text-muted-foreground" aria-hidden="true" /> Como os alertas são calculados
            </summary>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
              {LIMIARES.map(l => <li key={l}>{l}</li>)}
              <li>Residente ativo sem grau de dependência, sem PAIS vigente ou sem leito.</li>
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">Atualizado às {HORA.format(new Date(dados.gerado_em))}.</p>
          </details>
        </>
      )}
    </div>
  )
}

import { useEffect, useState } from 'react'
import { CheckCircle2, Info, RefreshCw } from 'lucide-react'
import { recarregarCentralAlertas, useCentralAlertas } from '../hooks/useCentralAlertas'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { LIMIARES, type Alerta } from '../services/alertas'
import { ESTILO_GRAVIDADE, ItemAlerta } from '../components/alertas/ItemAlerta'
import { Button } from '../components/ui/button'
import { Skeleton } from '../components/ui/feedback'
import { EmptyState, ErrorState } from '../components/ui/states'
import { cn } from '../lib/utils'

type Aba = 'todos' | 'criticos' | 'atencao' | 'pendencias'

const ABAS: { id: Aba; rotulo: string; filtro: (a: Alerta) => boolean; vazio: string }[] = [
  { id: 'todos', rotulo: 'Todos', filtro: () => true, vazio: 'Nada pedindo atenção agora' },
  { id: 'criticos', rotulo: 'Críticos', filtro: a => a.gravidade === 'critico', vazio: 'Nenhum item crítico agora' },
  { id: 'atencao', rotulo: 'Atenção', filtro: a => a.gravidade === 'atencao', vazio: 'Nenhum item de atenção agora' },
  // Pendência é natureza, não gravidade (#117).
  { id: 'pendencias', rotulo: 'Pendências', filtro: a => a.natureza === 'pendencia', vazio: 'Nenhuma pendência agora' },
]

const HORA = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo' })

function Lista({ itens, agora, fuso, podeAssumir, onMudou }: {
  itens: Alerta[]; agora: Date; fuso?: string; podeAssumir: boolean; onMudou: () => void
}) {
  return (
    <ul className="space-y-2">
      {itens.map(a => (
        <li key={a.id}><ItemAlerta alerta={a} agora={agora} fuso={fuso} podeAssumir={podeAssumir} onMudou={onMudou} /></li>
      ))}
    </ul>
  )
}

/**
 * Alertas e Pendências (#107, #117).
 *
 * Só leitura: cada item é calculado agora a partir da fonte oficial e some
 * quando o problema é resolvido lá — por isso a ação de cada cartão leva ao
 * módulo de origem. A ordem é a do backend; a tela só filtra e agrupa. Usa o
 * mesmo retrato do sino (useCentralAlertas), então os dois concordam.
 */
export function Alertas() {
  const carga = useCentralAlertas()
  // #123: assumir/atender/liberar; o backend confere de novo em cada ação.
  const podeAssumir = usePermissoesOuPadrao().pode('alertas:assumir')
  const [aba, setAba] = useState<Aba>('todos')

  // Abrir a Central sempre busca o retrato atual (e atualiza o sino junto).
  useEffect(() => { void recarregarCentralAlertas({ forcar: true }) }, [])
  const atualizar = () => { void recarregarCentralAlertas({ forcar: true }) }

  const dados = carga.status === 'ok' || carga.status === 'carregando' ? carga.dados : null
  const agora = new Date()
  const todos = dados?.alertas ?? []
  const atual = ABAS.find(x => x.id === aba)!
  const visiveis = todos.filter(atual.filtro)
  const prioridade = aba === 'todos' ? visiveis.filter(a => a.gravidade === 'critico') : []
  const demais = aba === 'todos' ? visiveis.filter(a => a.gravidade !== 'critico') : visiveis

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Alertas e Pendências</h1>
          <p className="text-sm text-muted-foreground">Situações que precisam da sua atenção, ação ou acompanhamento.</p>
        </div>
        {dados && (
          <Button variant="outline" onClick={atualizar} disabled={carga.status === 'carregando'}>
            <RefreshCw aria-hidden="true" /> Atualizar
          </Button>
        )}
      </div>

      {!dados && (carga.status === 'carregando' || carga.status === 'vazio') && (
        <div className="space-y-3" aria-label="Carregando alertas">
          {[0, 1, 2].map(i => <Skeleton key={i} className="h-20 w-full" />)}
        </div>
      )}
      {carga.status === 'proibido' && (
        <ErrorState
          title="Sem acesso aos alertas"
          description="Seu perfil não inclui a Central de Alertas. Se precisar, procure a administração da ILPI."
        />
      )}
      {carga.status === 'erro' && (
        <ErrorState title="Não foi possível carregar os alertas" description={`${carga.mensagem} Isso não significa que não há pendências.`} onRetry={atualizar} />
      )}

      {dados && (
        <>
          <ul aria-label="Resumo" className="flex flex-wrap gap-2">
            <li className={cn('inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-semibold', ESTILO_GRAVIDADE.critico.ficha)}>
              <span aria-hidden="true" className={cn('size-2 rounded-full', ESTILO_GRAVIDADE.critico.ponto)} />
              Críticos: <span className="tabular-nums">{dados.contagem.critico}</span>
            </li>
            <li className={cn('inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-semibold', ESTILO_GRAVIDADE.atencao.ficha)}>
              <span aria-hidden="true" className={cn('size-2 rounded-full', ESTILO_GRAVIDADE.atencao.ponto)} />
              Atenção: <span className="tabular-nums">{dados.contagem.atencao}</span>
            </li>
            <li className="inline-flex items-center gap-2 rounded-full border border-border bg-muted px-3 py-1.5 text-sm font-semibold text-slate-700">
              Pendências: <span className="tabular-nums">{dados.contagem.pendencia}</span>
            </li>
          </ul>

          <div role="tablist" aria-label="Filtro" className="flex flex-wrap gap-1 rounded-lg bg-muted p-1">
            {ABAS.map(x => (
              <button
                key={x.id}
                role="tab"
                aria-selected={aba === x.id}
                onClick={() => setAba(x.id)}
                className={cn(
                  'min-h-[44px] flex-1 rounded-md px-3 text-sm font-medium transition-colors sm:flex-none',
                  aba === x.id ? 'bg-card text-foreground shadow-sm' : 'text-slate-600 hover:text-foreground',
                )}
              >
                {x.rotulo} <span className="text-xs text-muted-foreground">({todos.filter(x.filtro).length})</span>
              </button>
            ))}
          </div>

          {visiveis.length === 0 ? (
            <EmptyState
              icon={CheckCircle2}
              title={atual.vazio}
              description={aba === 'todos' ? 'Quando algo ficar pendente, vencer ou sair do combinado, aparece aqui.' : 'Veja a aba Todos para os demais itens.'}
            />
          ) : (
            <div className="space-y-6">
              {prioridade.length > 0 && (
                <section aria-label={`Prioridade agora (${prioridade.length})`} className="space-y-2">
                  <h2 className="flex items-center gap-2 font-display text-base font-semibold text-foreground">
                    <span aria-hidden="true" className={cn('size-2.5 rounded-full', ESTILO_GRAVIDADE.critico.ponto)} />
                    Prioridade agora <span className="text-sm font-medium text-muted-foreground">({prioridade.length})</span>
                  </h2>
                  <Lista itens={prioridade} agora={agora} fuso={dados.fuso} podeAssumir={podeAssumir} onMudou={atualizar} />
                </section>
              )}
              {demais.length > 0 && (
                <section aria-label={aba === 'todos' ? `Demais (${demais.length})` : `${atual.rotulo} (${demais.length})`} className="space-y-2">
                  {aba === 'todos' && prioridade.length > 0 && (
                    <h2 className="font-display text-base font-semibold text-foreground">
                      Demais <span className="text-sm font-medium text-muted-foreground">({demais.length})</span>
                    </h2>
                  )}
                  <Lista itens={demais} agora={agora} fuso={dados.fuso} podeAssumir={podeAssumir} onMudou={atualizar} />
                </section>
              )}
            </div>
          )}

          <details className="rounded-card border border-border bg-card px-4 py-3 text-sm shadow-card sm:px-5">
            <summary className="flex min-h-[32px] cursor-pointer items-center gap-2 font-medium text-foreground">
              <Info className="size-4 text-muted-foreground" aria-hidden="true" /> Como os alertas são calculados
            </summary>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
              {LIMIARES.map(l => <li key={l}>{l}</li>)}
              <li>Residente ativo sem grau de dependência, sem PAIS vigente ou sem leito.</li>
              <li>Você só vê itens dos módulos que o seu perfil pode consultar.</li>
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">Atualizado às {HORA.format(new Date(dados.gerado_em))}.</p>
          </details>
        </>
      )}
    </div>
  )
}

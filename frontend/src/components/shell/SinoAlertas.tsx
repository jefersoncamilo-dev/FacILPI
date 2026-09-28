import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ArrowRight, Bell } from 'lucide-react'
import { usePermissoes } from '../../context/PermissoesContext'
import { recarregarCentralAlertas, useCentralAlertas, type EstadoCentral } from '../../hooks/useCentralAlertas'
import { destinoDoAlerta, quandoDoAlerta } from '../../services/alertas'
import { cn } from '../../lib/utils'
import { Button } from '../ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '../ui/dropdown-menu'
import { ESTILO_GRAVIDADE } from '../alertas/ItemAlerta'

export const ITENS_NO_SINO = 5

export type EstadoSino = { permitido: boolean; central: EstadoCentral }

/**
 * Estado do sino (#107, #117): o MESMO retrato de GET /central-alertas/ que a
 * Central usa (useCentralAlertas) — uma consulta por shell, não por cabeçalho.
 *
 * Só consulta com `alertas:ler` confirmado pelo backend: permissões
 * indisponíveis não viram consulta às cegas. Recarrega ao navegar, no máximo
 * uma vez por minuto; falha esconde o número, nunca mostra zero.
 */
export function useSinoAlertas(): EstadoSino {
  const { status, pode } = usePermissoes()
  const { pathname } = useLocation()
  const permitido = status === 'ok' && pode('alertas:ler')
  const central = useCentralAlertas()

  useEffect(() => {
    if (permitido) void recarregarCentralAlertas()
  }, [permitido, pathname])

  return { permitido, central }
}

/** Crítico + atenção: o que pede atenção agora (aviso fica na Central). */
export function totalDoSino(central: EstadoCentral): number | null {
  const dados = central.status === 'ok' || central.status === 'carregando' ? central.dados : null
  return dados ? dados.contagem.critico + dados.contagem.atencao : null
}

/**
 * Sino do topo como triagem rápida (#117): totais, até 5 itens na ordem do
 * backend e o caminho para a Central. Não tem regra própria — só apresenta.
 */
export function SinoAlertas({ permitido, central }: EstadoSino) {
  if (!permitido) return null
  const total = totalDoSino(central)
  const dados = central.status === 'ok' || central.status === 'carregando' ? central.dados : null
  const rotulo = total ? `Alertas: ${total} ${total === 1 ? 'pede' : 'pedem'} atenção` : 'Alertas'
  const agora = new Date()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={rotulo} className="relative shrink-0 text-muted-foreground">
          <Bell className="!size-5" aria-hidden="true" />
          {total ? (
            <span
              aria-hidden="true"
              className="absolute right-0.5 top-0.5 min-w-[18px] rounded-full bg-critico px-1 text-center text-[11px] font-semibold leading-[18px] text-white"
            >
              {total > 99 ? '99+' : total}
            </span>
          ) : null}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-[min(80vh,560px)] w-[min(92vw,380px)] overflow-y-auto p-0">
        <DropdownMenuLabel className="px-4 pb-1 pt-3 text-sm font-semibold text-foreground">Alertas e Pendências</DropdownMenuLabel>
        {dados ? (
          <>
            <div role="group" aria-label="Totais" className="px-4 pb-2 text-xs text-muted-foreground">
              Críticos: <span className="font-semibold tabular-nums text-foreground">{dados.contagem.critico}</span>
              {' · '}Atenção: <span className="font-semibold tabular-nums text-foreground">{dados.contagem.atencao}</span>
              {' · '}Pendências: <span className="font-semibold tabular-nums text-foreground">{dados.contagem.pendencia}</span>
            </div>
            <DropdownMenuSeparator className="mx-0 my-0" />
            {dados.alertas.length === 0 ? (
              <p className="px-4 py-4 text-sm text-muted-foreground">Nada pedindo atenção agora.</p>
            ) : (
              <div className="p-1">
                {dados.alertas.slice(0, ITENS_NO_SINO).map(a => {
                  const destino = destinoDoAlerta(a)
                  const meta = [a.residente_nome, a.local, quandoDoAlerta(a, agora, dados.fuso)].filter(Boolean).join(' · ')
                  return (
                    <DropdownMenuItem key={a.id} asChild className="items-start py-2">
                      <Link to={destino.to}>
                        <span aria-hidden="true" className={cn('mt-1.5 size-2 shrink-0 rounded-full', ESTILO_GRAVIDADE[a.gravidade].ponto)} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium text-foreground">{a.titulo}</span>
                          {meta && <span className="block truncate text-xs font-normal text-muted-foreground">{meta}</span>}
                          <span className="block text-xs font-semibold text-primary">{destino.acao}</span>
                        </span>
                      </Link>
                    </DropdownMenuItem>
                  )
                })}
              </div>
            )}
          </>
        ) : (
          <p className="px-4 py-4 text-sm text-muted-foreground">
            {central.status === 'erro' ? 'Não foi possível carregar os alertas.'
              : central.status === 'proibido' ? 'Sem acesso aos alertas.' : 'Carregando…'}
          </p>
        )}
        <DropdownMenuSeparator className="mx-0 my-0" />
        <div className="p-1">
          <DropdownMenuItem asChild className="justify-center font-semibold text-primary">
            <Link to="/alertas">
              Ver Central de Alertas <ArrowRight aria-hidden="true" />
            </Link>
          </DropdownMenuItem>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Bell } from 'lucide-react'
import { usePermissoes } from '../../context/PermissoesContext'
import { listarAlertas } from '../../services/alertas'
import { Button } from '../ui/button'

const INTERVALO_MINIMO = 60_000

export type EstadoSino = { permitido: boolean; total: number | null }

/**
 * Quantos alertas pedem atenção agora (crítico + atenção; aviso fica só na
 * página) — #107. Uma consulta por shell, não por cabeçalho.
 *
 * Só consulta com `alertas:ler` confirmado pelo backend: permissões
 * indisponíveis não viram consulta às cegas. Recarrega ao navegar, no máximo
 * uma vez por minuto; falha esconde o número, nunca mostra zero.
 */
export function useSinoAlertas(): EstadoSino {
  const { status, pode } = usePermissoes()
  const { pathname } = useLocation()
  const [total, setTotal] = useState<number | null>(null)
  const ultimaConsulta = useRef(0)
  const permitido = status === 'ok' && pode('alertas:ler')

  useEffect(() => {
    if (!permitido) return
    const agora = Date.now()
    if (ultimaConsulta.current && agora - ultimaConsulta.current < INTERVALO_MINIMO) return
    ultimaConsulta.current = agora
    let ativo = true
    listarAlertas()
      .then(d => { if (ativo) setTotal(d.contagem.critico + d.contagem.atencao) })
      .catch(() => { if (ativo) setTotal(null) })
    return () => { ativo = false }
  }, [permitido, pathname])

  return { permitido, total: permitido ? total : null }
}

/** Sino do topo: leva à central de alertas. */
export function SinoAlertas({ permitido, total }: EstadoSino) {
  if (!permitido) return null
  const rotulo = total ? `Alertas: ${total} ${total === 1 ? 'pede' : 'pedem'} atenção` : 'Alertas'
  return (
    <Button asChild variant="ghost" size="icon" className="relative shrink-0 text-muted-foreground">
      <Link to="/alertas" aria-label={rotulo}>
        <Bell className="!size-5" aria-hidden="true" />
        {total ? (
          <span
            aria-hidden="true"
            className="absolute right-0.5 top-0.5 min-w-[18px] rounded-full bg-critico px-1 text-center text-[11px] font-semibold leading-[18px] text-white"
          >
            {total > 99 ? '99+' : total}
          </span>
        ) : null}
      </Link>
    </Button>
  )
}

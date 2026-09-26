import { Link } from 'react-router-dom'
import { Construction } from 'lucide-react'
import { Button } from '../components/ui/button'
import { EmptyState } from '../components/ui/states'

/**
 * Módulo sem tela. UX-01: o texto antigo afirmava "API pronta" e
 * "responsividade validada" para módulos sem implementação — agora diz só o
 * que é verdade: a tela ainda não existe e, quando há jornada, qual Issue a entrega.
 */
export function Placeholder({ title, emConstrucao = false }: { title: string; emConstrucao?: boolean }) {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight text-foreground">{title}</h1>
      <EmptyState
        icon={Construction}
        title={emConstrucao ? 'Tela em construção' : 'Módulo ainda não disponível'}
        description={
          emConstrucao
            ? 'Esta tela faz parte das próximas entregas do FacILPI. Enquanto isso, as demais áreas seguem funcionando normalmente.'
            : 'Este módulo ainda não faz parte desta versão do FacILPI.'
        }
        action={
          <Button asChild variant="outline">
            <Link to="/">Voltar ao início</Link>
          </Button>
        }
      />
    </div>
  )
}

import { Link, Navigate, useParams } from 'react-router'
import { Lock } from 'lucide-react'
import { usePermissoes } from '../context/PermissoesContext'
import { ModuleHubCard } from '../components/shell/ModuleHubCard'
import { itensVisiveis, moduloPorSlug } from '../components/shell/navegacao'
import { Button } from '../components/ui/button'
import { Skeleton } from '../components/ui/feedback'
import { EmptyState } from '../components/ui/states'

/**
 * UX-00C: página-hub de um módulo (`/modulos/:modulo`).
 *
 * - Slug desconhecido, módulo futuro ou módulo-link → volta ao Início.
 * - Módulo ativo sem item permitido → "Sem acesso a este módulo" (rota
 *   válida, sem permissão — diferente de rota inválida).
 * - Só lista telas existentes e permitidas; nada aqui autoriza — cada rota
 *   do backend continua decidindo.
 */
export function ModuleHub() {
  const { modulo: slug } = useParams()
  const { status, pode } = usePermissoes()
  const modulo = moduloPorSlug(slug)

  if (!modulo) return <Navigate to="/" replace />
  // UX-NAV-1: endereço de hub antigo vai para o hub da seção nova.
  if (slug !== modulo.id) return <Navigate to={`/modulos/${modulo.id}`} replace />

  const Icone = modulo.icon
  const itens = itensVisiveis(modulo, pode)

  return (
    <div className="space-y-6">
      <header className="flex items-start gap-3">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-icon bg-brand-soft text-primary shadow-icon" aria-hidden="true">
          <Icone className="size-5" />
        </span>
        <div className="min-w-0">
          <h1 className="font-display text-titulo-tela text-brand-ink">{modulo.label}</h1>
          <p className="mt-1 text-apoio text-muted-foreground">{modulo.descricao}</p>
        </div>
      </header>

      {status === 'carregando' ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Carregando módulo">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-[88px] w-full rounded-card" />
          ))}
        </div>
      ) : itens.length === 0 ? (
        <EmptyState
          icon={Lock}
          title="Sem acesso a este módulo"
          description="Seu perfil não inclui nenhuma tela deste módulo. Se precisar, peça acesso ao administrador da ILPI."
          action={
            <Button asChild variant="outline">
              <Link to="/">Voltar ao início</Link>
            </Button>
          }
        />
      ) : (
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {itens.map(item => (
            <li key={item.id}>
              <ModuleHubCard item={item} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

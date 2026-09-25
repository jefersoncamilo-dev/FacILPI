import { Link, NavLink } from 'react-router-dom'
import { Building2, LogOut, ShieldCheck } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { cn } from '../lib/utils'
import { Logo } from './brand/Logo'
import { Button } from './ui/button'
import { ErrorBoundary } from './ui/states'

/**
 * Casca da Central FACILPI. Deliberadamente distinta do Layout institucional:
 * o operador precisa saber, de relance, que não está dentro de uma ILPI.
 * Sem menu clínico, sem seletor de contexto — só o que a Central opera.
 */
export function PlatformLayout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth()

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-30 border-b border-border bg-card/95 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-4 sm:px-6">
          <Link to="/platform/instituicoes" aria-label="Ir para a Central FacILPI" className="rounded-lg">
            <Logo />
          </Link>
          <span className="hidden items-center gap-1.5 rounded-full border border-border bg-muted px-3 py-1 text-xs font-semibold text-muted-foreground sm:inline-flex">
            <ShieldCheck className="size-3.5" aria-hidden="true" /> Central da plataforma
          </span>

          <div className="ml-auto flex min-w-0 items-center gap-3">
            <div className="hidden min-w-0 text-right md:block">
              <div className="truncate text-sm font-medium text-foreground">{user?.nome || 'Operador'}</div>
              <div className="truncate text-xs text-muted-foreground">{user?.email}</div>
            </div>
            <Button variant="outline" onClick={logout} className="px-3 text-xs">
              <LogOut aria-hidden="true" /> Sair
            </Button>
          </div>
        </div>
        <nav aria-label="Central da plataforma" className="mx-auto flex max-w-6xl gap-1 px-4 sm:px-6">
          <NavLink
            to="/platform/instituicoes"
            className={({ isActive }) =>
              cn(
                'inline-flex min-h-[44px] items-center gap-2 border-b-2 px-2 text-sm font-medium transition-colors',
                isActive ? 'border-brand text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground',
              )
            }
          >
            <Building2 className="size-4" aria-hidden="true" /> Instituições
          </NavLink>
        </nav>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
    </div>
  )
}

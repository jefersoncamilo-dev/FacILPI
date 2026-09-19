import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

/**
 * Casca da Central FACILPI. Deliberadamente distinta do Layout institucional:
 * o operador precisa saber, de relance, que não está dentro de uma ILPI.
 * Sem menu clínico, sem seletor de contexto — só o que a Central opera.
 */
export function PlatformLayout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-bg">
      <header className="bg-white border-b border-slate-100 sticky top-0 z-30">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center gap-3">
          <button
            onClick={() => navigate('/platform/instituicoes')}
            className="flex items-center gap-3 min-w-0"
            aria-label="Ir para a Central FacILPI"
          >
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary to-primaryDeep flex items-center justify-center text-white font-bold shrink-0">
              FL
            </div>
            <div className="text-left min-w-0">
              <div className="font-bold text-primaryDeep leading-none">Central FacILPI</div>
              <div className="text-xs text-textMuted truncate">Administração da plataforma</div>
            </div>
          </button>

          <div className="ml-auto flex items-center gap-2 min-w-0">
            <div className="hidden sm:block text-right min-w-0">
              <div className="text-sm font-medium truncate">{user?.nome || 'Operador'}</div>
              <div className="text-xs text-textMuted truncate">{user?.email}</div>
            </div>
            <button
              onClick={logout}
              className="bg-slate-900 text-white rounded-xl px-4 py-2 text-xs font-medium hover:bg-black min-h-[44px]"
            >
              Sair
            </button>
          </div>
        </div>
        <nav className="max-w-6xl mx-auto px-4 pb-3">
          <Link
            to="/platform/instituicoes"
            className="text-sm font-medium text-primary hover:underline"
          >
            Instituições
          </Link>
        </nav>
      </header>
      <main className="max-w-6xl mx-auto px-4 py-6">{children}</main>
    </div>
  )
}

import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ehOperadorDaPlataforma } from '../types/platform'

/**
 * Guarda de ROTEAMENTO da Central FACILPI. Não é autorização: o backend exige
 * platform_superuser em escopo global em toda rota de /api/platform, e um token
 * institucional recebe 403 lá mesmo que chegue a renderizar algo aqui.
 *
 * A ordem das checagens importa. A troca obrigatória de senha vem ANTES de
 * qualquer lógica de escopo: um gestor em primeiro acesso recebe `scope: None`
 * do backend e `contextFromToken` o apresenta como global, então sem este desvio
 * ele chegaria a testar a condição de plataforma.
 */
export function PlatformRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, requiresPasswordChange, activeContext } = useAuth()
  const { pathname } = useLocation()

  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (requiresPasswordChange && pathname !== '/primeiro-acesso') {
    return <Navigate to="/primeiro-acesso" replace />
  }
  if (!ehOperadorDaPlataforma(activeContext)) return <Navigate to="/" replace />
  return <>{children}</>
}

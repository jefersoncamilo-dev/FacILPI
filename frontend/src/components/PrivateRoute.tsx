import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export function PrivateRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, requiresPasswordChange } = useAuth()
  const { pathname } = useLocation()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  // Troca obrigatória pendente: só a tela de primeiro acesso é acessível.
  if (requiresPasswordChange && pathname !== '/primeiro-acesso') {
    return <Navigate to="/primeiro-acesso" replace />
  }
  return <>{children}</>
}

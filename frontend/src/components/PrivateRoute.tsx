import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ehOperadorDaPlataforma } from '../types/platform'

export function PrivateRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, requiresPasswordChange, activeContext } = useAuth()
  const { pathname } = useLocation()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  // Troca obrigatória pendente: só a tela de primeiro acesso é acessível, e
  // NENHUMA lógica de escopo roda enquanto ela estiver de pé. O superusuário do
  // bootstrap tambem chega aqui com contexto global: sem este `return`, ele seria
  // desviado de /primeiro-acesso para /platform e de volta, em laço.
  if (requiresPasswordChange) {
    return pathname === '/primeiro-acesso' ? <>{children}</> : <Navigate to="/primeiro-acesso" replace />
  }
  // Operador em contexto global não tem o que fazer na aplicação institucional:
  // sem contexto de ILPI, toda chamada dali responde 403. Desviar para a Central
  // é honesto, não cosmético.
  if (ehOperadorDaPlataforma(activeContext)) return <Navigate to="/platform" replace />
  return <>{children}</>
}

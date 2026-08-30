import { createContext, useContext, useEffect, useState, ReactNode } from 'react'
import { api } from '../services/api'

type User = { id: string; nome: string; email: string }

type AuthContextType = {
  user: User | null
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  updatePassword: (nova: string, confirmar: string) => Promise<void>
  loading: boolean
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => {
    try {
      const raw = localStorage.getItem('facilpi_user')
      return raw ? JSON.parse(raw) : null
    } catch { return null }
  })
  const [loading, setLoading] = useState(false)

  const isAuthenticated = !!user && !!localStorage.getItem('facilpi_token')

  async function login(email: string, password: string) {
    setLoading(true)
    try {
      const { data } = await api.post('/auth/token', { email, password })
      localStorage.setItem('facilpi_token', data.access_token)
      // decode payload to get user basics (sub/email) — backend token contains them
      // fetch profile is not yet endpoint, reconstruct from email; fallback to API if needed
      // Try to keep user object minimal; we could fetch via token decode
      const payload = JSON.parse(atob(data.access_token.split('.')[1]))
      const u: User = { id: payload.sub, nome: payload.email.split('@')[0], email: payload.email }
      localStorage.setItem('facilpi_user', JSON.stringify(u))
      setUser(u)
    } finally {
      setLoading(false)
    }
  }

  function logout() {
    localStorage.removeItem('facilpi_token')
    localStorage.removeItem('facilpi_user')
    setUser(null)
    window.location.href = '/login'
  }

  async function updatePassword(nova_senha: string, confirmar_senha: string) {
    await api.put('/auth/password', { nova_senha, confirmar_senha })
  }

  // keep user sync on storage
  useEffect(() => {
    const onStorage = () => {
      const raw = localStorage.getItem('facilpi_user')
      setUser(raw ? JSON.parse(raw) : null)
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  return (
    <AuthContext.Provider value={{ user, isAuthenticated, login, logout, updatePassword, loading }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

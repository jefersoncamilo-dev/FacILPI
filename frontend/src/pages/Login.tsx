import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Modal } from '../components/Modal'

export function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(false)
  const { login, loading } = useAuth()
  const navigate = useNavigate()

  async function handle(e: React.FormEvent) {
    e.preventDefault()
    setErr('')
    try {
      await login(email, password)
      navigate('/')
    } catch (e: any) {
      const msg = e.response?.data?.detail || 'Falha no login. Verifique credenciais.'
      setErr(msg)
      setOpen(true)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-primaryLight via-white to-bg p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary to-primaryDeep mx-auto flex items-center justify-center text-white font-bold text-xl">FL</div>
          <h1 className="mt-4 text-2xl font-bold text-primaryDeep">FáciLPI</h1>
          <p className="text-textMuted text-sm mt-1">Gestão, Cuidados e Conformidade</p>
        </div>
        <form onSubmit={handle} className="card space-y-4">
          <h2 className="font-semibold text-lg">Entrar</h2>
          <input className="input" placeholder="E-mail" type="email" value={email} onChange={e => setEmail(e.target.value)} required />
          <input className="input" placeholder="Senha" type="password" value={password} onChange={e => setPassword(e.target.value)} required />
          <button disabled={loading} className="btn-primary w-full disabled:opacity-60">
            {loading ? 'Entrando...' : 'Entrar'}
          </button>
          <p className="text-sm text-center text-textMuted">Não tem conta? <Link to="/register" className="text-primary font-semibold hover:underline">Cadastre-se</Link></p>
        </form>
      </div>
      <Modal open={open} onClose={() => setOpen(false)} title="Atenção">
        <p className="text-sm text-textMain">{err}</p>
        <button onClick={() => setOpen(false)} className="btn-primary w-full mt-4">Fechar</button>
      </Modal>
    </div>
  )
}

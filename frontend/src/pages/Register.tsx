import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../services/api'
import { Modal } from '../components/Modal'

export function Register() {
  const [nome, setNome] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [msg, setMsg] = useState('')
  const [open, setOpen] = useState(false)
  const [ok, setOk] = useState(false)
  const navigate = useNavigate()

  async function handle(e: React.FormEvent) {
    e.preventDefault()
    try {
      await api.post('/auth/register', { nome, email, password })
      setMsg('Cadastro realizado! Redirecionando para login...')
      setOk(true)
      setOpen(true)
      setTimeout(() => navigate('/login'), 1400)
    } catch (e: any) {
      setOk(false)
      setMsg(e.response?.data?.detail || 'Erro ao cadastrar')
      setOpen(true)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-primaryLight via-white to-bg p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary to-primaryDeep mx-auto flex items-center justify-center text-white font-bold text-xl">FL</div>
          <h1 className="mt-4 text-2xl font-bold text-primaryDeep">Criar conta</h1>
        </div>
        <form onSubmit={handle} className="card space-y-4">
          <input className="input" placeholder="Nome completo" value={nome} onChange={e => setNome(e.target.value)} required />
          <input className="input" placeholder="E-mail" type="email" value={email} onChange={e => setEmail(e.target.value)} required />
          <input className="input" placeholder="Senha (mín. 8, maiúscula, minúscula, número)" type="password" value={password} onChange={e => setPassword(e.target.value)} required />
          <button className="btn-primary w-full">Cadastrar</button>
          <p className="text-sm text-center text-textMuted">Já tem conta? <Link to="/login" className="text-primary font-semibold">Entrar</Link></p>
        </form>
      </div>
      <Modal open={open} onClose={() => setOpen(false)} title={ok ? 'Sucesso' : 'Atenção'}>
        <p className="text-sm">{msg}</p>
        <button onClick={() => setOpen(false)} className="btn-primary w-full mt-4">Fechar</button>
      </Modal>
    </div>
  )
}

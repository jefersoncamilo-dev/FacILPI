import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Modal } from '../components/Modal'
import { ContextPicker } from '../components/ContextPicker'
import type { ContextOption } from '../types/context'

const RULES = [
  'Mínimo de 8 caracteres',
  'Uma letra maiúscula',
  'Uma letra minúscula',
  'Um número',
]

function localCheck(pwd: string): string | null {
  if (pwd.length < 8) return 'A nova senha deve ter no mínimo 8 caracteres'
  if (!/[A-Z]/.test(pwd)) return 'A nova senha deve conter uma letra maiúscula'
  if (!/[a-z]/.test(pwd)) return 'A nova senha deve conter uma letra minúscula'
  if (!/[0-9]/.test(pwd)) return 'A nova senha deve conter um número'
  return null
}

/** Primeiro acesso: troca obrigatória antes de qualquer uso do sistema. */
export function PrimeiroAcesso() {
  const [nova, setNova] = useState('')
  const [confirmar, setConfirmar] = useState('')
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(false)
  const [options, setOptions] = useState<ContextOption[] | null>(null)
  const [picking, setPicking] = useState(false)
  const { completePasswordChange, switchContext, loading } = useAuth()
  const navigate = useNavigate()

  function fail(msg: string) {
    setErr(msg)
    setOpen(true)
  }

  async function handle(e: React.FormEvent) {
    e.preventDefault()
    if (nova !== confirmar) {
      fail('As senhas não conferem. Digite a mesma senha nos dois campos.')
      return
    }
    const rule = localCheck(nova)
    if (rule) {
      fail(rule)
      return
    }
    try {
      const res = await completePasswordChange(nova, confirmar)
      setNova('')
      setConfirmar('')
      if (res.options.length > 1) {
        setOptions(res.options)
      } else {
        navigate('/')
      }
    } catch (e: any) {
      const detail = e.response?.data?.detail
      fail(typeof detail === 'string' ? detail : detail?.message || 'Não foi possível salvar a nova senha')
    }
  }

  async function choose(opt: ContextOption) {
    if (opt.scope === 'global') {
      navigate('/')
      return
    }
    setPicking(true)
    try {
      await switchContext(opt)
      navigate('/')
    } catch (e: any) {
      const detail = e.response?.data?.detail
      fail(typeof detail === 'string' ? detail : detail?.message || 'Contexto não autorizado')
    } finally {
      setPicking(false)
    }
  }

  if (options) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-primaryLight via-white to-bg p-4">
        <div className="w-full max-w-md card space-y-3">
          <h2 className="font-semibold text-lg">Senha atualizada 🎉</h2>
          <p className="text-sm text-textMuted">Agora escolha onde deseja operar.</p>
          <ContextPicker options={options} onPick={choose} disabled={picking} />
        </div>
        <Modal open={open} onClose={() => setOpen(false)} title="Atenção">
          <p className="text-sm text-textMain">{err}</p>
          <button onClick={() => setOpen(false)} className="btn-primary w-full mt-4">Fechar</button>
        </Modal>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-primaryLight via-white to-bg p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary to-primaryDeep mx-auto flex items-center justify-center text-white font-bold text-xl">FL</div>
          <h1 className="mt-4 text-2xl font-bold text-primaryDeep">Defina sua nova senha</h1>
          <p className="text-textMuted text-sm mt-1">Por segurança, você precisa definir uma nova senha antes de continuar.</p>
        </div>
        <form onSubmit={handle} className="card space-y-4">
          <input className="input" type="password" placeholder="Nova senha" value={nova} onChange={e => setNova(e.target.value)} required autoComplete="new-password" />
          <input className="input" type="password" placeholder="Confirmar nova senha" value={confirmar} onChange={e => setConfirmar(e.target.value)} required autoComplete="new-password" />
          <ul className="text-xs text-textMuted space-y-1">
            {RULES.map(r => <li key={r}>• {r}</li>)}
          </ul>
          <button disabled={loading} className="btn-primary w-full disabled:opacity-60">
            {loading ? 'Salvando...' : 'Salvar nova senha'}
          </button>
        </form>
      </div>
      <Modal open={open} onClose={() => setOpen(false)} title="Atenção">
        <p className="text-sm text-textMain">{err}</p>
        <button onClick={() => setOpen(false)} className="btn-primary w-full mt-4">Fechar</button>
      </Modal>
    </div>
  )
}

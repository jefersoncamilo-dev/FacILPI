import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, Circle, Loader2 } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { mensagemDeErro } from '../services/api'
import { ContextPicker } from '../components/ContextPicker'
import { AuthLayout } from '../components/auth/AuthLayout'
import { PasswordInput } from '../components/auth/PasswordInput'
import { Button } from '../components/ui/button'
import { Label } from '../components/ui/input'
import { Alert } from '../components/ui/feedback'
import type { ContextOption } from '../types/context'

const RULES: { label: string; ok: (pwd: string) => boolean }[] = [
  { label: 'Mínimo de 8 caracteres', ok: p => p.length >= 8 },
  { label: 'Uma letra maiúscula', ok: p => /[A-Z]/.test(p) },
  { label: 'Uma letra minúscula', ok: p => /[a-z]/.test(p) },
  { label: 'Um número', ok: p => /[0-9]/.test(p) },
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
  const [atual, setAtual] = useState('')
  const [nova, setNova] = useState('')
  const [confirmar, setConfirmar] = useState('')
  const [err, setErr] = useState('')
  const [options, setOptions] = useState<ContextOption[] | null>(null)
  const [picking, setPicking] = useState(false)
  const { completePasswordChange, switchContext, loading, logout } = useAuth()
  const navigate = useNavigate()

  async function handle(e: React.FormEvent) {
    e.preventDefault()
    setErr('')
    if (nova !== confirmar) {
      setErr('As senhas não conferem. Digite a mesma senha nos dois campos.')
      return
    }
    const rule = localCheck(nova)
    if (rule) {
      setErr(rule)
      return
    }
    try {
      const res = await completePasswordChange(atual, nova, confirmar)
      setAtual('')
      setNova('')
      setConfirmar('')
      if (res.options.length > 1) {
        setOptions(res.options)
      } else {
        navigate('/')
      }
    } catch (e: any) {
      setErr(mensagemDeErro(e, 'Não foi possível salvar a nova senha'))
    }
  }

  async function choose(opt: ContextOption) {
    if (opt.scope === 'global') {
      navigate('/')
      return
    }
    setErr('')
    setPicking(true)
    try {
      await switchContext(opt)
      navigate('/')
    } catch (e: any) {
      setErr(mensagemDeErro(e, 'Contexto não autorizado'))
    } finally {
      setPicking(false)
    }
  }

  if (options) {
    return (
      <AuthLayout>
        <div className="space-y-6">
          <Alert variant="success" title="Senha atualizada">
            Agora escolha onde deseja operar.
          </Alert>
          {err && <Alert variant="error">{err}</Alert>}
          <ContextPicker options={options} onPick={choose} disabled={picking} />
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout>
      <div className="space-y-7">
        <div className="space-y-1.5">
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Defina sua nova senha</h1>
          <p className="text-sm text-muted-foreground">
            Por segurança, você precisa definir uma nova senha antes de continuar.
          </p>
        </div>

        {err && <Alert variant="error">{err}</Alert>}

        <form onSubmit={handle} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="pa-atual">Senha temporária</Label>
            <PasswordInput
              id="pa-atual"
              placeholder="Senha temporária"
              value={atual}
              onChange={e => setAtual(e.target.value)}
              required
              autoComplete="current-password"
              aria-describedby="pa-atual-dica"
            />
            <p id="pa-atual-dica" className="text-xs text-muted-foreground">A mesma senha que você acabou de usar para entrar.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="pa-nova">Nova senha</Label>
            <PasswordInput
              id="pa-nova"
              placeholder="Nova senha"
              value={nova}
              onChange={e => setNova(e.target.value)}
              required
              autoComplete="new-password"
              aria-describedby="pa-regras"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="pa-confirmar">Confirmar nova senha</Label>
            <PasswordInput
              id="pa-confirmar"
              placeholder="Confirmar nova senha"
              value={confirmar}
              onChange={e => setConfirmar(e.target.value)}
              required
              autoComplete="new-password"
            />
          </div>
          <ul id="pa-regras" className="grid gap-1.5 rounded-lg bg-muted px-4 py-3 text-xs sm:grid-cols-2">
            {RULES.map(r => {
              const ok = r.ok(nova)
              return (
                <li key={r.label} className={ok ? 'flex items-center gap-2 text-emerald-800' : 'flex items-center gap-2 text-muted-foreground'}>
                  {ok ? <Check className="size-3.5" aria-hidden="true" /> : <Circle className="size-3.5" aria-hidden="true" />}
                  <span>
                    {r.label}
                    <span className="sr-only">{ok ? ' — atendido' : ' — pendente'}</span>
                  </span>
                </li>
              )
            })}
          </ul>
          <Button type="submit" size="lg" className="w-full" disabled={loading}>
            {loading ? (
              <>
                <Loader2 className="animate-spin" aria-hidden="true" /> Salvando…
              </>
            ) : (
              'Salvar nova senha'
            )}
          </Button>
        </form>

        {/* Sem saída, quem entrou com a conta errada ficava preso aqui. */}
        <div className="border-t border-border pt-5 text-center">
          <Button variant="link" type="button" onClick={logout}>
            Sair e entrar com outra conta
          </Button>
        </div>
      </div>
    </AuthLayout>
  )
}

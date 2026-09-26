import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { mensagemDeErro } from '../services/api'
import { ContextPicker } from '../components/ContextPicker'
import { AuthLayout } from '../components/auth/AuthLayout'
import { PasswordInput } from '../components/auth/PasswordInput'
import { Button } from '../components/ui/button'
import { Input, Label } from '../components/ui/input'
import { Alert } from '../components/ui/feedback'
import { SESSION_ENDED_KEY } from '../types/context'
import type { ContextOption } from '../types/context'

// A marca só é consumida quando a pessoa tenta entrar de novo. Consumir ao
// montar falhava: após um 401 o React já redireciona pela SPA (montando o
// Login) antes do recarregamento completo pedido pelo interceptor, e a página
// recarregada não encontrava mais a marca.
function sessaoFoiEncerrada(): boolean {
  try {
    return sessionStorage.getItem(SESSION_ENDED_KEY) === '1'
  } catch {
    return false
  }
}

function consumirMarcaDeSessaoEncerrada() {
  try {
    sessionStorage.removeItem(SESSION_ENDED_KEY)
  } catch {
    /* sem armazenamento de sessão: nada a consumir */
  }
}

export function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [sessaoEncerrada, setSessaoEncerrada] = useState(sessaoFoiEncerrada)
  const [options, setOptions] = useState<ContextOption[] | null>(null)
  const [picking, setPicking] = useState(false)
  const { login, loading, switchContext } = useAuth()
  const navigate = useNavigate()

  async function handle(e: React.FormEvent) {
    e.preventDefault()
    setErr('')
    setSessaoEncerrada(false)
    consumirMarcaDeSessaoEncerrada()
    try {
      const res = await login(email, password)
      // Troca obrigatória tem prioridade sobre qualquer seleção de contexto.
      if (res.requiresPasswordChange) {
        navigate('/primeiro-acesso')
        return
      }
      if (res.options.length > 1) {
        // Múltiplos contextos: seleção explícita, sem substituir silenciosamente.
        setOptions(res.options)
      } else {
        // Contexto único global é o operador da plataforma: a aplicação
        // institucional responderia 403 em tudo.
        navigate(res.options[0]?.scope === 'global' ? '/platform' : '/')
      }
    } catch (e: any) {
      // Conta com mais de um vínculo institucional: o backend exige escolher o
      // contexto no login, mas não há como listá-los antes da autenticação —
      // decisão de produto/segurança pendente (UX-01 / #83). Até lá, dizer o
      // que está acontecendo em vez de pedir uma escolha que a tela não oferece.
      if (e?.response?.data?.detail?.code === 'PROFILE_SELECTION_REQUIRED') {
        setErr(
          'Sua conta está vinculada a mais de uma instituição, e o acesso com vários vínculos ainda não está disponível. Procure o administrador da ILPI.',
        )
        return
      }
      setErr(mensagemDeErro(e, 'Falha no login. Verifique credenciais.'))
    }
  }

  async function choose(opt: ContextOption) {
    if (opt.scope === 'global') {
      navigate('/platform')
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
          <div className="space-y-1.5">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">Escolha o contexto</h1>
            <p className="text-sm text-muted-foreground">
              Sua conta possui mais de um contexto. Selecione onde deseja operar agora.
            </p>
          </div>
          {err && <Alert variant="error">{err}</Alert>}
          <ContextPicker options={options} onPick={choose} disabled={picking} />
          {picking && (
            <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" /> Abrindo contexto…
            </p>
          )}
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout>
      <div className="space-y-7">
        <div className="space-y-1.5">
          <h1 className="text-2xl font-bold tracking-tight text-foreground sm:text-[1.75rem]">Boas-vindas</h1>
          <p className="text-sm text-muted-foreground">Entre com o seu e-mail e senha para continuar.</p>
        </div>

        {sessaoEncerrada && !err && (
          <Alert variant="info" title="Sua sessão foi encerrada">
            Por segurança, entre novamente para continuar de onde parou.
          </Alert>
        )}
        {err && <Alert variant="error">{err}</Alert>}

        <form onSubmit={handle} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="login-email">E-mail</Label>
            <Input
              id="login-email"
              placeholder="E-mail"
              type="email"
              inputMode="email"
              autoComplete="username"
              autoFocus
              value={email}
              onChange={e => setEmail(e.target.value)}
              aria-invalid={err ? true : undefined}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="login-senha">Senha</Label>
            <PasswordInput
              id="login-senha"
              placeholder="Senha"
              autoComplete="current-password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              aria-invalid={err ? true : undefined}
              required
            />
          </div>
          <Button type="submit" size="lg" className="w-full" disabled={loading}>
            {loading ? (
              <>
                <Loader2 className="animate-spin" aria-hidden="true" /> Entrando…
              </>
            ) : (
              'Entrar'
            )}
          </Button>
        </form>

        {/* PH-01: o acesso ao FacILPI é sempre provisionado — o operador da
            plataforma cria o primeiro gestor e a ILPI cria a própria equipe.
            Não há autocadastro nem recuperação de senha self-service no
            backend; a redefinição é feita pelo administrador da ILPI. */}
        <div className="space-y-1 border-t border-border pt-5 text-center text-sm text-muted-foreground">
          <p>O acesso é criado pela sua instituição. Procure o administrador da ILPI.</p>
          <p>Esqueceu a senha? O administrador da ILPI pode redefini-la para você.</p>
        </div>
      </div>
    </AuthLayout>
  )
}

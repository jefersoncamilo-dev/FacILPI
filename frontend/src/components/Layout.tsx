import { useEffect, useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { ChevronRight, ClipboardList, KeyRound, LayoutDashboard, Loader2, LogOut, Menu, Settings, Users } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { PermissoesProvider, usePermissoes } from '../context/PermissoesContext'
import { mensagemDeErro } from '../services/api'
import { cn } from '../lib/utils'
import { ContextSwitcher, contextTitle } from './ContextSwitcher'
import { Logo } from './brand/Logo'
import { NAVEGACAO, itemDaRota } from './shell/navegacao'
import { SinoAlertas, useSinoAlertas } from './shell/SinoAlertas'
import { PasswordInput } from './auth/PasswordInput'
import { Button } from './ui/button'
import { Label } from './ui/input'
import { Alert, Skeleton } from './ui/feedback'
import { Dialog, DialogContent, Sheet, SheetContent } from './ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from './ui/dropdown-menu'
import { ErrorBoundary } from './ui/states'

/**
 * AppShell da ILPI (UX-01 / #83).
 *
 * Desktop (≥1280px): sidebar fixa agrupada por tarefa + barra superior com a
 * trilha e o contexto institucional. Mobile e tablet (inclusive deitado):
 * cabeçalho com menu em Sheet e navegação inferior com os destinos do dia a
 * dia — padrão de toque, sem sidebar rolando (UX-11 / #101).
 *
 * O menu só mostra o que a sessão pode abrir (GET /auth/permissoes); isso
 * orienta a interface, não autoriza — cada rota do backend decide.
 */
export function Layout({ children }: { children: ReactNode }) {
  return (
    <PermissoesProvider>
      <Shell>{children}</Shell>
    </PermissoesProvider>
  )
}

function Shell({ children }: { children: ReactNode }) {
  const [menuAberto, setMenuAberto] = useState(false)
  const [senhaAberta, setSenhaAberta] = useState(false)
  const { activeContext } = useAuth()
  const { pathname } = useLocation()
  const sino = useSinoAlertas()

  // Navegar fecha o menu mobile (inclusive pelo botão voltar do navegador).
  useEffect(() => setMenuAberto(false), [pathname])

  function abrirSenha() {
    setMenuAberto(false)
    setSenhaAberta(true)
  }

  return (
    <div className="min-h-screen bg-background xl:grid xl:grid-cols-[264px_minmax(0,1fr)]">
      <aside className="sticky top-0 hidden h-screen border-r border-border bg-card xl:block">
        <PainelNavegacao onAlterarSenha={abrirSenha} />
      </aside>

      <div className="flex min-h-screen min-w-0 flex-col">
        {/* Mobile/tablet */}
        <header className="sticky top-0 z-30 flex h-16 items-center gap-2 border-b border-border bg-card/95 px-3 backdrop-blur sm:px-5 xl:hidden">
          <Button variant="ghost" size="icon" aria-label="Abrir menu" onClick={() => setMenuAberto(true)}>
            <Menu className="!size-5" aria-hidden="true" />
          </Button>
          <Logo />
          <span className="ml-auto hidden max-w-[45%] truncate rounded-full bg-muted px-3 py-1 text-xs font-medium text-slate-600 sm:block">
            {contextTitle(activeContext)}
          </span>
          <div className="ml-auto sm:ml-0">
            <SinoAlertas {...sino} />
          </div>
        </header>

        {/* Desktop */}
        <header className="sticky top-0 z-30 hidden h-16 items-center gap-4 border-b border-border bg-background/90 px-8 backdrop-blur xl:flex">
          <Trilha pathname={pathname} />
          <div className="ml-auto flex items-center gap-2">
            <SinoAlertas {...sino} />
            <ContextSwitcher compact />
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 pb-28 pt-6 sm:px-6 lg:px-8 xl:pb-10 xl:pt-8">
          <ErrorBoundary resetKey={pathname}>{children}</ErrorBoundary>
        </main>

        <NavegacaoInferior onMenu={() => setMenuAberto(true)} />
      </div>

      <Sheet open={menuAberto} onOpenChange={setMenuAberto}>
        <SheetContent title="Menu de navegação">
          <PainelNavegacao mobile onAlterarSenha={abrirSenha} />
        </SheetContent>
      </Sheet>

      <AlterarSenhaDialog open={senhaAberta} onOpenChange={setSenhaAberta} />
    </div>
  )
}

function PainelNavegacao({ mobile = false, onAlterarSenha }: { mobile?: boolean; onAlterarSenha: () => void }) {
  const { user, logout } = useAuth()
  const { status, pode } = usePermissoes()
  const inicial = user?.nome?.[0]?.toUpperCase() || 'U'

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-16 shrink-0 items-center border-b border-border px-5">
        <Link to="/" aria-label="FacILPI — ir para o início" className="rounded-lg">
          <Logo />
        </Link>
      </div>

      {mobile && (
        <div className="border-b border-border p-4">
          <ContextSwitcher />
        </div>
      )}

      {/* UX-11: compacto para caber sem rolagem em 1080p (12 itens, 4 grupos). */}
      <nav aria-label="Navegação principal" className="flex-1 space-y-4 overflow-y-auto px-3 py-4">
        {status === 'carregando' ? (
          <div className="space-y-3 px-3" aria-label="Carregando menu">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : (
          NAVEGACAO.map(grupo => {
            const itens = grupo.itens.filter(item => pode(item.permissao))
            if (itens.length === 0) return null
            return (
              <div key={grupo.titulo}>
                <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  {grupo.titulo}
                </p>
                <ul className="space-y-0.5">
                  {itens.map(item => (
                    <li key={item.to}>
                      <NavLink
                        to={item.to}
                        end={item.to === '/'}
                        className={({ isActive }) =>
                          cn(
                            'group relative flex min-h-[40px] items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors',
                            isActive
                              ? 'bg-brand-soft font-semibold text-accent-foreground'
                              : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                          )
                        }
                      >
                        <item.icon className="size-[18px] shrink-0" aria-hidden="true" />
                        <span className="min-w-0 flex-1 py-1">
                          <span className="block truncate">{item.label}</span>
                          {item.emBreve && (
                            <span className="block text-[11px] font-normal leading-tight text-muted-foreground">Em breve</span>
                          )}
                        </span>
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            )
          })
        )}
      </nav>

      <div className="flex shrink-0 items-center gap-3 border-t border-border px-4 py-3">
        {/* PH-01: o avatar é só identificação — nunca botão, nunca logout. */}
        <div
          aria-hidden="true"
          className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-soft font-semibold text-primary"
        >
          {inicial}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">{user?.nome || 'Usuário'}</p>
          <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
        </div>
        {/* UX-11: Alterar senha e Sair num menu da conta, com a barra limpa.
            "Sair" continua explícito (PH-01), agora como item do menu. */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Menu da conta" className="shrink-0 text-muted-foreground">
              <Settings className="!size-5" aria-hidden="true" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="end">
            <DropdownMenuLabel>{user?.nome || 'Sua conta'}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={onAlterarSenha}>
              <KeyRound aria-hidden="true" /> Alterar senha
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => { void logout() }} className="text-red-700 [&_svg]:text-red-700">
              <LogOut aria-hidden="true" /> Sair
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  )
}

function Trilha({ pathname }: { pathname: string }) {
  const atual = itemDaRota(pathname)
  if (!atual) return <span />
  const { grupo, item } = atual
  const emDetalhe = item.to !== '/' && pathname !== item.to
  return (
    <nav aria-label="Trilha de navegação">
      <ol className="flex items-center gap-1.5 text-sm text-muted-foreground">
        {grupo.titulo !== item.label && (
          <>
            <li>{grupo.titulo}</li>
            <ChevronRight className="size-3.5" aria-hidden="true" />
          </>
        )}
        {emDetalhe ? (
          <>
            <li>
              <Link to={item.to} className="rounded hover:text-foreground hover:underline">{item.label}</Link>
            </li>
            <ChevronRight className="size-3.5" aria-hidden="true" />
            <li aria-current="page" className="font-medium text-foreground">Detalhe</li>
          </>
        ) : (
          <li aria-current="page" className="font-medium text-foreground">{item.label}</li>
        )}
      </ol>
    </nav>
  )
}

function NavegacaoInferior({ onMenu }: { onMenu: () => void }) {
  const { pode } = usePermissoes()
  const destinos = [
    { to: '/', label: 'Início', icon: LayoutDashboard },
    { to: '/plantao', label: 'Plantão', icon: ClipboardList, permissao: 'plantao:ler' },
    { to: '/residentes', label: 'Residentes', icon: Users, permissao: 'residentes:ler' },
  ].filter(d => pode(d.permissao))

  const estilo = 'flex min-h-[52px] min-w-[64px] flex-1 flex-col items-center justify-center gap-1 rounded-lg text-[11px] font-medium'
  return (
    <nav
      aria-label="Navegação rápida"
      className="fixed inset-x-0 bottom-0 z-30 flex gap-1 border-t border-border bg-card/95 px-2 pt-1.5 backdrop-blur xl:hidden"
      style={{ paddingBottom: 'max(0.375rem, env(safe-area-inset-bottom))' }}
    >
      {destinos.map(d => (
        <NavLink
          key={d.to}
          to={d.to}
          end={d.to === '/'}
          className={({ isActive }) => cn(estilo, isActive ? 'text-primary' : 'text-muted-foreground hover:text-foreground')}
        >
          {({ isActive }) => (
            <>
              <d.icon className={cn('size-5', isActive && 'stroke-[2.4]')} aria-hidden="true" />
              {d.label}
            </>
          )}
        </NavLink>
      ))}
      <button type="button" onClick={onMenu} className={cn(estilo, 'text-muted-foreground hover:text-foreground')}>
        <Menu className="size-5" aria-hidden="true" />
        Menu
      </button>
    </nav>
  )
}

function AlterarSenhaDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { updatePassword } = useAuth()
  const [atual, setAtual] = useState('')
  const [nova, setNova] = useState('')
  const [confirmar, setConfirmar] = useState('')
  const [erro, setErro] = useState('')
  const [sucesso, setSucesso] = useState(false)
  const [salvando, setSalvando] = useState(false)

  function fechar(aberto: boolean) {
    onOpenChange(aberto)
    if (!aberto) {
      setAtual(''); setNova(''); setConfirmar(''); setErro(''); setSucesso(false)
    }
  }

  async function salvar(e: React.FormEvent) {
    e.preventDefault()
    setErro('')
    if (nova !== confirmar) { setErro('Senhas não conferem'); return }
    setSalvando(true)
    try {
      await updatePassword(atual, nova, confirmar)
      setSucesso(true)
      setTimeout(() => fechar(false), 1200)
    } catch (err) {
      setErro(mensagemDeErro(err, 'Erro ao alterar senha'))
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={fechar}>
      <DialogContent title="Alterar senha" description="As outras sessões abertas com a sua conta serão encerradas.">
        <form onSubmit={salvar} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="as-atual">Senha atual</Label>
            <PasswordInput id="as-atual" placeholder="Senha atual" value={atual} onChange={e => setAtual(e.target.value)} autoComplete="current-password" required />
          </div>
          <div className="space-y-2">
            <Label htmlFor="as-nova">Nova senha</Label>
            <PasswordInput id="as-nova" placeholder="Nova senha" value={nova} onChange={e => setNova(e.target.value)} autoComplete="new-password" aria-describedby="as-nova-dica" required />
            <p id="as-nova-dica" className="text-xs text-muted-foreground">Mínimo de 8 caracteres, com maiúscula, minúscula e número.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="as-confirmar">Confirmar nova senha</Label>
            <PasswordInput id="as-confirmar" placeholder="Confirmar nova senha" value={confirmar} onChange={e => setConfirmar(e.target.value)} autoComplete="new-password" required />
          </div>
          {erro && <Alert variant="error">{erro}</Alert>}
          {sucesso && <Alert variant="success">Senha alterada com sucesso</Alert>}
          <Button type="submit" className="w-full" disabled={salvando || sucesso}>
            {salvando ? (<><Loader2 className="animate-spin" aria-hidden="true" /> Salvando…</>) : 'Salvar nova senha'}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}

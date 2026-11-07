import { useEffect, useState } from 'react'
import { CalendarClock, LogOut, MessageSquareText, Wallet } from 'lucide-react'
import { api, formatDate, formatDateTime, mensagemDeErro } from '../services/api'
import { useAuth } from '../context/AuthContext'
import { Button } from '../components/ui/button'
import { Alert, Badge, Skeleton } from '../components/ui/feedback'

interface Compromisso { motivo: string; inicio_em: string; local: string | null; situacao: string }
interface Recado { id: string; texto: string; autor_nome: string; created_at: string }
interface Mensalidade { competencia: string; valor_centavos: number; vencimento: string; situacao: string; pago_em: string | null }
export interface ResumoPortal {
  residente_nome: string
  familiar_nome: string
  hoje: string
  compromissos_hoje: Compromisso[]
  recados_hoje: number
  agenda: Compromisso[]
  mensalidades: Mensalidade[]
  recados: Recado[]
}

const reais = (c: number) => (c / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })

function Bloco({ icone: Icone, titulo, children }: { icone: typeof Wallet; titulo: string; children: React.ReactNode }) {
  return (
    <section className="rounded-card border border-border bg-card p-4">
      <h2 className="flex items-center gap-2 font-semibold text-foreground"><Icone className="size-5 text-primary" aria-hidden="true" />{titulo}</h2>
      <div className="mt-3 space-y-2">{children}</div>
    </section>
  )
}

const Nada = ({ texto }: { texto: string }) => <p className="text-apoio text-muted-foreground">{texto}</p>

/** Portal da família (#271): só leitura, só o residente vinculado, nada do prontuário. */
export function PortalFamilia() {
  const { logout } = useAuth()
  const [dados, setDados] = useState<ResumoPortal | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  useEffect(() => {
    api.get<ResumoPortal>('/portal/resumo').then(r => setDados(r.data))
      .catch(e => setErro(mensagemDeErro(e, 'Não foi possível abrir o portal. Fale com a instituição.')))
  }, [])

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-4">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-apoio text-muted-foreground">Portal da família</p>
          <h1 className="font-display text-titulo-tela text-brand-ink wrap-break-word">{dados ? dados.residente_nome : 'Carregando…'}</h1>
          {dados && <p className="text-apoio text-muted-foreground">Olá, {dados.familiar_nome}.</p>}
        </div>
        <Button variant="outline" onClick={() => { void logout() }}><LogOut className="size-4" aria-hidden="true" /> Sair</Button>
      </header>
      {erro && <Alert variant="error">{erro}</Alert>}
      {!dados && !erro && <Skeleton className="h-64 w-full rounded-card" />}
      {dados && (
        <>
          <Bloco icone={CalendarClock} titulo={`Hoje, ${formatDate(dados.hoje)}`}>
            {dados.compromissos_hoje.length === 0 && dados.recados_hoje === 0 && <Nada texto="Nenhum compromisso nem recado novo hoje." />}
            {dados.compromissos_hoje.map(c => <p key={c.inicio_em + c.motivo}>{formatDateTime(c.inicio_em)} · {c.motivo}</p>)}
            {dados.recados_hoje > 0 && <p>{dados.recados_hoje === 1 ? '1 recado novo da equipe.' : `${dados.recados_hoje} recados novos da equipe.`}</p>}
          </Bloco>
          <Bloco icone={MessageSquareText} titulo="Recados da equipe">
            {dados.recados.length === 0 ? <Nada texto="Nenhum recado ainda." /> : dados.recados.map(r => (
              <div key={r.id} className="border-b border-border pb-2 last:border-0">
                <p className="wrap-break-word">{r.texto}</p>
                <p className="text-apoio text-muted-foreground">{r.autor_nome} · {formatDateTime(r.created_at)}</p>
              </div>
            ))}
          </Bloco>
          <Bloco icone={CalendarClock} titulo="Próximos compromissos">
            {dados.agenda.length === 0 ? <Nada texto="Nenhum compromisso nos próximos 30 dias." /> : dados.agenda.map(c => (
              <p key={c.inicio_em + c.motivo}>{formatDateTime(c.inicio_em)} · {c.motivo}{c.local ? ` · ${c.local}` : ''}</p>
            ))}
          </Bloco>
          <Bloco icone={Wallet} titulo="Mensalidades">
            {dados.mensalidades.length === 0 ? <Nada texto="Nenhuma mensalidade lançada." /> : dados.mensalidades.map(x => (
              <div key={x.competencia} className="flex flex-wrap items-center justify-between gap-2">
                <span>{x.competencia} · {reais(x.valor_centavos)} · vence {formatDate(x.vencimento)}</span>
                <Badge variant={x.situacao === 'paga' ? 'success' : 'warning'}>{x.situacao === 'paga' ? 'Paga' : 'Em aberto'}</Badge>
              </div>
            ))}
          </Bloco>
          <p className="text-apoio text-muted-foreground">Para falar com a equipe, use os contatos da instituição. Por aqui não é possível enviar mensagens.</p>
        </>
      )}
    </main>
  )
}

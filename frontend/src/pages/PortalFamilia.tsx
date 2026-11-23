import { useEffect, useState } from 'react'
import { CalendarClock, HeartHandshake, LogOut, MessageSquareText, Scale, Wallet } from 'lucide-react'
import { api, formatDate, formatDateTime, mensagemDeErro } from '../services/api'
import { useAuth } from '../context/AuthContext'
import { Button } from '../components/ui/button'
import { Alert, Badge, Skeleton } from '../components/ui/feedback'

interface Compromisso { motivo: string; inicio_em: string; local: string | null; situacao: string }
interface Recado { id: string; texto: string; autor_nome: string; created_at: string }
interface Mensalidade { competencia: string; valor_centavos: number; vencimento: string; situacao: string; pago_em: string | null }
interface Percentual { feitos: number; total: number; percentual: number | null }
export interface ResumoPortal {
  residente_nome: string
  familiar_nome: string
  hoje: string
  portal_liberado: boolean
  categorias: string[]
  medicacao: Percentual | null
  alimentacao: Percentual | null
  atividades: Percentual | null
  peso: { data: string; peso: number }[] | null
  compromissos_hoje: Compromisso[] | null
  recados_hoje: number | null
  agenda: Compromisso[] | null
  mensalidades: Mensalidade[] | null
  recados: Recado[] | null
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

/** Barra que cresce ao abrir (movimento desligado para quem pede menos animação). */
function Barra({ rotulo, valor, apoio }: { rotulo: string; valor: Percentual; apoio: string }) {
  const [largura, setLargura] = useState(0)
  useEffect(() => { const t = setTimeout(() => setLargura(valor.percentual ?? 0), 50); return () => clearTimeout(t) }, [valor.percentual])
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-medium">{rotulo}</span>
        <span className="font-display text-xl text-brand-ink">{valor.percentual === null ? '—' : `${valor.percentual}%`}</span>
      </div>
      <div className="mt-1 h-3 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label={rotulo}
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={valor.percentual ?? undefined}>
        <div className="h-full rounded-full bg-primary transition-[width] duration-700 ease-out motion-reduce:transition-none" style={{ width: `${largura}%` }} />
      </div>
      <p className="mt-1 text-apoio text-muted-foreground">{valor.percentual === null ? 'Ainda sem registros neste período.' : apoio}</p>
    </div>
  )
}

/** Portal da família (#271, #303): só leitura, só o residente vinculado e só o que a equipe liberou. */
export function PortalFamilia() {
  const { logout } = useAuth()
  const [dados, setDados] = useState<ResumoPortal | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  useEffect(() => {
    api.get<ResumoPortal>('/portal/resumo').then(r => setDados(r.data))
      .catch(e => setErro(mensagemDeErro(e, 'Não foi possível abrir o portal. Fale com a instituição.')))
  }, [])

  const resultados = dados && (dados.medicacao || dados.alimentacao || dados.atividades)

  return (
    <main className="mx-auto max-w-xl space-y-4 p-4">
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
      {dados && dados.categorias.length === 0 && (
        <Bloco icone={HeartHandshake} titulo="Em breve">
          <p>A instituição ainda não liberou informações no portal. Quando liberar, elas aparecem aqui.</p>
        </Bloco>
      )}
      {dados && (
        <>
          {resultados && (
            <Bloco icone={HeartHandshake} titulo="Últimos 30 dias">
              {dados.medicacao && <Barra rotulo="Remédios dados" valor={dados.medicacao} apoio={`${dados.medicacao.feitos} de ${dados.medicacao.total} remédios previstos.`} />}
              {dados.alimentacao && <Barra rotulo="Alimentação" valor={dados.alimentacao} apoio="Quanto das refeições foi comido, em média." />}
              {dados.atividades && <Barra rotulo="Atividades e cuidados" valor={dados.atividades} apoio={`${dados.atividades.feitos} de ${dados.atividades.total} feitos.`} />}
            </Bloco>
          )}
          {dados.peso && (
            <Bloco icone={Scale} titulo="Peso">
              {dados.peso.length === 0 ? <Nada texto="Nenhuma pesagem nos últimos 30 dias." /> : (
                <ul className="space-y-1">
                  {dados.peso.map(p => <li key={p.data}>{formatDate(p.data)} · {p.peso.toLocaleString('pt-BR')} kg</li>)}
                </ul>
              )}
            </Bloco>
          )}
          {dados.compromissos_hoje && (
            <Bloco icone={CalendarClock} titulo={`Hoje, ${formatDate(dados.hoje)}`}>
              {dados.compromissos_hoje.length === 0 ? <Nada texto="Nenhum compromisso hoje." />
                : dados.compromissos_hoje.map(c => <p key={c.inicio_em + c.motivo}>{formatDateTime(c.inicio_em)} · {c.motivo}</p>)}
            </Bloco>
          )}
          {dados.recados && (
            <Bloco icone={MessageSquareText} titulo="Recados da equipe">
              {dados.recados.length === 0 ? <Nada texto="Nenhum recado ainda." /> : dados.recados.map(r => (
                <div key={r.id} className="border-b border-border pb-2 last:border-0">
                  <p className="wrap-break-word">{r.texto}</p>
                  <p className="text-apoio text-muted-foreground">{r.autor_nome} · {formatDateTime(r.created_at)}</p>
                </div>
              ))}
            </Bloco>
          )}
          {dados.agenda && (
            <Bloco icone={CalendarClock} titulo="Próximos compromissos">
              {dados.agenda.length === 0 ? <Nada texto="Nenhum compromisso nos próximos 30 dias." /> : dados.agenda.map(c => (
                <p key={c.inicio_em + c.motivo}>{formatDateTime(c.inicio_em)} · {c.motivo}{c.local ? ` · ${c.local}` : ''}</p>
              ))}
            </Bloco>
          )}
          {dados.mensalidades && (
            <Bloco icone={Wallet} titulo="Mensalidades">
              {dados.mensalidades.length === 0 ? <Nada texto="Nenhuma mensalidade lançada." /> : dados.mensalidades.map(x => (
                <div key={x.competencia} className="flex flex-wrap items-center justify-between gap-2">
                  <span>{x.competencia} · {reais(x.valor_centavos)} · vence {formatDate(x.vencimento)}</span>
                  <Badge variant={x.situacao === 'paga' ? 'success' : 'warning'}>{x.situacao === 'paga' ? 'Paga' : 'Em aberto'}</Badge>
                </div>
              ))}
            </Bloco>
          )}
          <p className="text-apoio text-muted-foreground">
            Dúvidas sobre saúde e tratamento são tratadas diretamente com a equipe. Para falar com a equipe, use os contatos da instituição; por aqui não é possível enviar mensagens.
          </p>
        </>
      )}
    </main>
  )
}

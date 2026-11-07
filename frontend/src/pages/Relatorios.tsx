import { useCallback, useEffect, useState } from 'react'
import { Lock } from 'lucide-react'
import { api, mensagemDeErro } from '../services/api'
import { Button } from '../components/ui/button'
import { Input, Label } from '../components/ui/input'
import { Alert, Skeleton } from '../components/ui/feedback'
import { EmptyState } from '../components/ui/states'

interface Contagem { chave: string; total: number }
export interface Resumo {
  residentes_por_situacao: Contagem[] | null
  intercorrencias_por_gravidade: Contagem[] | null
  administracoes_por_resultado: Contagem[] | null
}

function iso(d: Date) { return d.toISOString().slice(0, 10) }

function Secao({ titulo, itens }: { titulo: string; itens: Contagem[] | null }) {
  if (!itens) return null
  return (
    <section className="rounded-card border border-border bg-card p-4">
      <h2 className="font-semibold text-foreground">{titulo}</h2>
      {itens.length === 0
        ? <p className="mt-2 text-apoio text-muted-foreground">Nenhum registro.</p>
        : <dl className="mt-2 space-y-1">{itens.map(i => (
          <div key={i.chave} className="flex justify-between gap-4"><dt className="capitalize">{i.chave.replace(/_/g, ' ')}</dt><dd className="font-semibold">{i.total}</dd></div>
        ))}</dl>}
    </section>
  )
}

/** Resumo da instituição; cada seção só vem se a sessão lê a fonte dela. */
export function Relatorios() {
  const hoje = new Date()
  const [de, setDe] = useState(iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)))
  const [ate, setAte] = useState(iso(hoje))
  const [dados, setDados] = useState<Resumo | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [proibido, setProibido] = useState(false)

  const buscar = useCallback(async () => {
    setErro(null)
    try {
      setDados((await api.get<Resumo>('/relatorios/resumo', { params: { de, ate } })).data)
    } catch (e: any) {
      if (e?.response?.status === 403) setProibido(true)
      else setErro(mensagemDeErro(e, 'Não foi possível gerar o relatório.'))
    }
  }, [de, ate])

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { buscar() }, [])

  if (proibido) return <EmptyState icon={Lock} title="Sem acesso a relatórios" description="Peça acesso ao administrador da instituição." />

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-titulo-tela text-brand-ink">Relatórios</h1>
        <p className="mt-1 text-apoio text-muted-foreground">Resumo da instituição no período.</p>
      </header>
      <form className="grid gap-4 md:grid-cols-3 md:items-end" onSubmit={e => { e.preventDefault(); buscar() }}>
        <div className="space-y-1"><Label htmlFor="de">De</Label><Input id="de" type="date" value={de} onChange={e => setDe(e.target.value)} /></div>
        <div className="space-y-1"><Label htmlFor="ate">Até</Label><Input id="ate" type="date" value={ate} onChange={e => setAte(e.target.value)} /></div>
        <Button type="submit" variant="outline">Gerar</Button>
      </form>
      {erro && <Alert variant="error">{erro}</Alert>}
      {!dados && !erro && <Skeleton className="h-48 w-full rounded-card" />}
      {dados && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Secao titulo="Residentes hoje, por situação" itens={dados.residentes_por_situacao} />
          <Secao titulo="Intercorrências por gravidade" itens={dados.intercorrencias_por_gravidade} />
          <Secao titulo="Administrações de medicação" itens={dados.administracoes_por_resultado} />
        </div>
      )}
    </div>
  )
}

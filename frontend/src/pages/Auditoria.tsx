import { useCallback, useEffect, useState } from 'react'
import { History, Lock } from 'lucide-react'
import { api, formatDateTime, mensagemDeErro } from '../services/api'
import { Button } from '../components/ui/button'
import { Input, Label } from '../components/ui/input'
import { Alert, Skeleton } from '../components/ui/feedback'
import { EmptyState } from '../components/ui/states'

export interface ItemAuditoria {
  id: string
  acao: string
  entidade: string | null
  registro_id: string | null
  usuario_nome: string | null
  valores_anteriores: string | null
  valores_posteriores: string | null
  created_at: string
}

const PAGINA = 50

/** Trilha de auditoria da instituição da sessão. Só leitura. */
export function Auditoria() {
  const [itens, setItens] = useState<ItemAuditoria[] | null>(null)
  const [acao, setAcao] = useState('')
  const [entidade, setEntidade] = useState('')
  const [fim, setFim] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [proibido, setProibido] = useState(false)

  const buscar = useCallback(async (skip: number, base: ItemAuditoria[]) => {
    setErro(null)
    try {
      const params: Record<string, string | number> = { skip, limit: PAGINA }
      if (acao.trim()) params.acao = acao.trim()
      if (entidade.trim()) params.entidade = entidade.trim()
      const { data } = await api.get<ItemAuditoria[]>('/auditoria/', { params })
      setItens([...base, ...data])
      setFim(data.length < PAGINA)
    } catch (e: any) {
      if (e?.response?.status === 403) setProibido(true)
      else setErro(mensagemDeErro(e, 'Não foi possível carregar a auditoria.'))
    }
  }, [acao, entidade])

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { buscar(0, []) }, [])

  if (proibido) return <EmptyState icon={Lock} title="Sem acesso à auditoria" description="Peça acesso ao administrador da instituição." />

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-titulo-tela text-brand-ink">Auditoria</h1>
        <p className="mt-1 text-apoio text-muted-foreground">Quem fez o quê e quando nesta instituição.</p>
      </header>
      <form className="grid gap-4 md:grid-cols-3 md:items-end" onSubmit={e => { e.preventDefault(); buscar(0, []) }}>
        <div className="space-y-1"><Label htmlFor="acao">Ação</Label><Input id="acao" value={acao} onChange={e => setAcao(e.target.value)} /></div>
        <div className="space-y-1"><Label htmlFor="entidade">Área do sistema</Label><Input id="entidade" value={entidade} onChange={e => setEntidade(e.target.value)} /></div>
        <Button type="submit" variant="outline">Filtrar</Button>
      </form>
      {erro && <Alert variant="error">{erro}</Alert>}
      {!itens && !erro && <Skeleton className="h-64 w-full rounded-card" />}
      {itens?.length === 0 && <EmptyState icon={History} title="Nenhum registro encontrado" description="Mude os filtros para ver outros registros." />}
      {!!itens?.length && (
        <ul className="space-y-3">
          {itens.map(i => (
            <li key={i.id} className="rounded-card border border-border bg-card p-4">
              <p className="break-words font-semibold text-foreground">{i.acao}</p>
              <p className="text-apoio text-muted-foreground">{formatDateTime(i.created_at)} · {i.usuario_nome || 'Sistema'}{i.entidade ? ` · ${i.entidade}` : ''}</p>
              {(i.valores_anteriores || i.valores_posteriores) && (
                <details className="mt-2 text-apoio">
                  <summary className="cursor-pointer">Ver detalhes</summary>
                  {i.valores_anteriores && <p className="mt-1 break-words">Antes: {i.valores_anteriores}</p>}
                  {i.valores_posteriores && <p className="mt-1 break-words">Depois: {i.valores_posteriores}</p>}
                </details>
              )}
            </li>
          ))}
        </ul>
      )}
      {!!itens?.length && !fim && <Button variant="outline" onClick={() => buscar(itens.length, itens)}>Carregar mais</Button>}
    </div>
  )
}

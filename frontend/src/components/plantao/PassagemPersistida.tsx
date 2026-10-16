import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { CheckCircle2, Inbox, Plus, Send, Trash2 } from 'lucide-react'
import { formatDateTime, mensagemDeErro } from '../../services/api'
import {
  LIMITE_OBSERVACAO, passagemApi, ROTULO_CATEGORIA, ROTULO_ORIGEM,
  type CategoriaObservacao, type ItemPassagem, type ObservacaoNova, type Passagem, type Previa,
} from '../../services/passagem'
import { plantoesApi } from '../../services/escala'
import { Button } from '../ui/button'
import { Alert, Skeleton } from '../ui/feedback'
import { cn } from '../../lib/utils'

const CAMPO = 'block min-h-[44px] w-full rounded-md border border-border bg-card px-3 text-sm'

function Item({ item }: { item: ItemPassagem }) {
  const observacao = item.origem === 'observacao'
  return (
    <li className="flex flex-col gap-1 border-b border-border py-2 last:border-b-0 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0 space-y-0.5">
        <p className="text-sm font-medium text-foreground">
          {observacao ? item.texto : item.titulo}
        </p>
        <p className="text-xs text-muted-foreground">
          {[observacao && item.categoria ? ROTULO_CATEGORIA[item.categoria]
            // Item vindo da central: o rótulo segue a natureza (pendência não é "alerta").
            : item.origem === 'alerta' && item.natureza === 'pendencia' ? 'Pendência' : ROTULO_ORIGEM[item.origem],
            item.residente_nome,
            item.previsto_em && item.origem === 'atividade' ? `previsto ${formatDateTime(item.previsto_em)}` : null]
            .filter(Boolean).join(' · ')}
        </p>
      </div>
      {item.situacao_atual && (
        <span className={cn('shrink-0 self-start rounded-full border px-2.5 py-0.5 text-xs font-semibold sm:self-auto',
          item.situacao_atual === 'aberto' ? 'border-orange-200 bg-orange-50 text-orange-800' : 'border-emerald-200 bg-emerald-50 text-emerald-800')}>
          {item.situacao_atual === 'aberto' ? 'Ainda aberto' : 'Resolvido desde então'}
        </span>
      )}
    </li>
  )
}

/** Observações por passagem (mesmo teto do backend). */
const LIMITE_OBSERVACOES = 20

/**
 * Passagens entregues aguardando o próximo turno (#125). Cada item mostra a
 * situação ATUAL da fonte; quem recebe confirma. Quem entregou não confirma.
 */
export function PassagensAReceber({ podeReceber, versao = 0 }: { podeReceber: boolean; versao?: number }) {
  const [passagens, setPassagens] = useState<Passagem[] | null>(null)
  const [erro, setErro] = useState('')
  const [sucesso, setSucesso] = useState('')
  const [recebendo, setRecebendo] = useState<string | null>(null)

  const carregar = useCallback(async () => {
    try {
      const lista = await passagemApi.listar('entregue')
      // As da minha área primeiro.
      setPassagens([...lista].sort((a, b) => Number(b.da_minha_area) - Number(a.da_minha_area)))
      setErro('')
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível carregar as passagens.'))
    }
  }, [])

  // `versao` muda quando uma passagem é entregue nesta tela: a lista reflete na hora.
  useEffect(() => { void carregar() }, [carregar, versao])

  async function receber(p: Passagem) {
    setErro('')
    setRecebendo(p.id)
    try {
      await passagemApi.receber(p.id)
      setSucesso(`Recebimento confirmado: passagem de ${p.entregue_por_nome}.`)
    } catch (e) {
      // 409: outra pessoa confirmou antes — a lista recarregada mostra o estado atual.
      setErro(mensagemDeErro(e, 'Não foi possível confirmar o recebimento.'))
    } finally {
      setRecebendo(null)
      await carregar()
    }
  }

  return (
    <section aria-label="Passagens a receber" className="space-y-3">
      <h2 className="font-display text-lg font-semibold text-foreground">Passagens a receber</h2>
      {sucesso && <Alert variant="success">{sucesso}</Alert>}
      {erro && <Alert variant="error">{erro}</Alert>}
      {passagens === null && !erro && <Skeleton className="h-20 w-full" />}
      {passagens?.length === 0 && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground"><Inbox className="size-4" aria-hidden="true" /> Nenhuma passagem aguardando recebimento.</p>
      )}
      <ul className="space-y-3">
        {passagens?.map(p => (
          <li key={p.id} className={cn('rounded-card border bg-card p-4 shadow-card', p.da_minha_area ? 'border-primary' : 'border-border')}>
            <article aria-label={`Passagem de ${p.entregue_por_nome}`} className="space-y-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="font-medium text-foreground">
                  {p.area_nome ?? 'Toda a ILPI'} · entregue por {p.entregue_por_nome}
                  {p.da_minha_area && <span className="ml-2 text-xs font-semibold text-primary">sua área</span>}
                </p>
                <span className="text-xs text-muted-foreground">{formatDateTime(p.entregue_em)}</span>
              </div>
              {p.itens.length === 0 ? (
                <p className="text-sm text-muted-foreground">Sem pendências registradas.</p>
              ) : (
                <ul>{p.itens.map((i, n) => <Item key={i.id ?? n} item={i} />)}</ul>
              )}
              {p.itens_sem_acesso > 0 && (
                <p className="text-xs text-muted-foreground">
                  Mais {p.itens_sem_acesso} {p.itens_sem_acesso === 1 ? 'item' : 'itens'} de módulos que seu perfil não consulta.
                </p>
              )}
              {podeReceber && !p.entregue_por_mim && (
                <Button onClick={() => receber(p)} disabled={recebendo !== null} className="min-h-[44px]">
                  <CheckCircle2 aria-hidden="true" /> {recebendo === p.id ? 'Confirmando…' : 'Confirmar recebimento'}
                </Button>
              )}
              {p.entregue_por_mim && <p className="text-xs text-muted-foreground">Você entregou esta passagem; quem assume o próximo turno confirma.</p>}
            </article>
          </li>
        ))}
      </ul>
    </section>
  )
}

/**
 * Passar o plantão (#125): o resumo automático vem do servidor (só com dados
 * reais e o que seu perfil lê); você acrescenta observações curtas.
 */
export function PassarPlantao({ onEntregue }: { onEntregue?: () => void } = {}) {
  const [aberto, setAberto] = useState(false)
  const [previa, setPrevia] = useState<Previa | null>(null)
  const [emPlantao, setEmPlantao] = useState(false)
  const [observacoes, setObservacoes] = useState<ObservacaoNova[]>([])
  const [nova, setNova] = useState<{ categoria: CategoriaObservacao; residente_id: string; texto: string }>({ categoria: 'assistencial', residente_id: '', texto: '' })
  // Encerrar o plantão é escolha explícita: passar a passagem não encerra por padrão.
  const [encerrar, setEncerrar] = useState(false)
  const [erro, setErro] = useState('')
  const [entregues, setEntregues] = useState<Passagem[] | null>(null)
  const [salvando, setSalvando] = useState(false)

  async function abrir() {
    setAberto(true)
    setErro('')
    setEntregues(null)
    setPrevia(null)
    setEncerrar(false)
    try {
      const [p, atual] = await Promise.all([passagemApi.previa(), plantoesApi.atual().catch(() => null)])
      setPrevia(p)
      // Só oferece encerrar a quem está de plantão E pode registrar plantão (o backend exige o mesmo).
      setEmPlantao(Boolean(atual?.plantao && atual.pode_registrar))
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível montar o resumo do plantão.'))
    }
  }

  function adicionar(e: FormEvent) {
    e.preventDefault()
    const texto = nova.texto.trim()
    if (!texto || observacoes.length >= LIMITE_OBSERVACOES) return
    setObservacoes(lista => [...lista, { categoria: nova.categoria, texto, ...(nova.residente_id ? { residente_id: nova.residente_id } : {}) }])
    setNova({ ...nova, texto: '' })
  }

  async function entregar() {
    setSalvando(true)
    setErro('')
    try {
      const lista = await passagemApi.entregar({ observacoes, encerrar_plantao: emPlantao && encerrar, ...(previa?.area_id ? { area_id: previa.area_id } : {}) })
      setEntregues(lista)
      setObservacoes([])
      setAberto(false)
      onEntregue?.()
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível entregar a passagem.'))
    } finally {
      setSalvando(false)
    }
  }

  const residentes = Array.from(new Map((previa?.itens ?? []).filter(i => i.residente_id && i.residente_nome)
    .map(i => [i.residente_id as string, i.residente_nome as string])).entries())

  return (
    <section aria-label="Passar plantão" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-lg font-semibold text-foreground">Passar plantão</h2>
        {!aberto && <Button onClick={abrir} className="min-h-[44px]"><Send aria-hidden="true" /> Preparar passagem</Button>}
      </div>
      {entregues && entregues.length > 0 && (
        <Alert variant="success">
          {entregues.length === 1
            ? `Passagem entregue às ${formatDateTime(entregues[0].entregue_em)} com ${entregues[0].itens.length} ${entregues[0].itens.length === 1 ? 'item' : 'itens'}. O próximo turno confirma o recebimento.`
            : `Passagens entregues às ${formatDateTime(entregues[0].entregue_em)}, uma por área: ${entregues.map(p => `${p.area_nome} (${p.itens.length} ${p.itens.length === 1 ? 'item' : 'itens'})`).join(', ')}. O próximo turno de cada área confirma a sua.`}
        </Alert>
      )}
      {erro && <Alert variant="error">{erro}</Alert>}
      {aberto && !previa && !erro && <Skeleton className="h-24 w-full" />}
      {aberto && !previa && erro && (
        <div className="flex flex-wrap gap-2">
          <Button onClick={abrir} className="min-h-[44px]">Tentar de novo</Button>
          <Button variant="outline" onClick={() => { setAberto(false); setErro('') }} className="min-h-[44px]">Voltar</Button>
        </div>
      )}
      {aberto && previa && (
        <div className="space-y-4 rounded-card border border-border bg-card p-4 shadow-card">
          <p className="text-sm text-muted-foreground">
            {previa.area_nome ? `Área: ${previa.area_nome}` : 'Toda a ILPI'} · de {formatDateTime(previa.janela_inicio)} até agora.
            O resumo abaixo sai das fontes; nada aqui cria registro clínico.
          </p>
          <div>
            <h3 className="text-sm font-semibold text-foreground">Automático ({previa.itens.length})</h3>
            {previa.itens.length === 0
              ? <p className="text-sm text-muted-foreground">Nada pendente nas fontes que seu perfil consulta.</p>
              : <ul aria-label="Resumo automático">{previa.itens.map((i, n) => <Item key={n} item={i} />)}</ul>}
          </div>
          <form onSubmit={adicionar} aria-label="Nova observação" className="grid gap-2 sm:grid-cols-[auto_1fr] sm:items-start">
            <label className="space-y-1 text-sm">
              <span className="font-medium text-foreground">Categoria</span>
              <select value={nova.categoria} onChange={e => setNova({ ...nova, categoria: e.target.value as CategoriaObservacao })} className={CAMPO}>
                {(Object.keys(ROTULO_CATEGORIA) as CategoriaObservacao[]).map(c => <option key={c} value={c}>{ROTULO_CATEGORIA[c]}</option>)}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium text-foreground">Residente (opcional)</span>
              <select value={nova.residente_id} onChange={e => setNova({ ...nova, residente_id: e.target.value })} className={CAMPO}>
                <option value="">Nenhum</option>
                {residentes.map(([id, nome]) => <option key={id} value={id}>{nome}</option>)}
              </select>
            </label>
            <div className="space-y-1 text-sm sm:col-span-2">
              <label className="block space-y-1">
                <span className="font-medium text-foreground">Observação</span>
                <textarea
                  value={nova.texto}
                  maxLength={LIMITE_OBSERVACAO}
                  onChange={e => setNova({ ...nova, texto: e.target.value })}
                  rows={2}
                  aria-describedby="observacao-limite"
                  className="block w-full rounded-md border border-border bg-card px-3 py-2 text-sm"
                  placeholder="Curta e objetiva (ex.: agitada no fim da tarde)"
                />
              </label>
              <span id="observacao-limite" className="text-xs text-muted-foreground">{nova.texto.length}/{LIMITE_OBSERVACAO} caracteres</span>
            </div>
            <Button type="submit" variant="outline" disabled={!nova.texto.trim() || observacoes.length >= LIMITE_OBSERVACOES}
              className="min-h-[44px] sm:col-span-2 sm:justify-self-start">
              <Plus aria-hidden="true" /> Adicionar observação
            </Button>
            {observacoes.length >= LIMITE_OBSERVACOES && (
              <p className="text-xs text-muted-foreground sm:col-span-2">Limite de {LIMITE_OBSERVACOES} observações por passagem.</p>
            )}
          </form>
          {observacoes.length > 0 && (
            <ul aria-label="Observações" className="space-y-1">
              {observacoes.map((o, n) => (
                <li key={n} className="flex items-center justify-between gap-2 text-sm">
                  <span>{ROTULO_CATEGORIA[o.categoria]}: {o.texto}</span>
                  <button type="button" aria-label={`Remover observação ${n + 1}`} className="min-h-[44px] px-2 text-red-700"
                    onClick={() => setObservacoes(lista => lista.filter((_, i) => i !== n))}>
                    <Trash2 className="size-4" aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {emPlantao && (
            <label className="flex min-h-[44px] items-center gap-2 text-sm">
              <input type="checkbox" checked={encerrar} onChange={e => setEncerrar(e.target.checked)} />
              Encerrar meu plantão ao entregar
            </label>
          )}
          <div className="flex flex-wrap gap-2">
            <Button onClick={entregar} disabled={salvando} className="min-h-[44px]"><Send aria-hidden="true" /> Entregar passagem</Button>
            <Button variant="outline" onClick={() => setAberto(false)} className="min-h-[44px]">Voltar</Button>
          </div>
        </div>
      )}
    </section>
  )
}

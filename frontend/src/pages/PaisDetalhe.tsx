import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Check, CheckCircle2, CircleDot, Copy, Loader2, Plus, Trash2, XCircle } from 'lucide-react'
import { api, formatDate, formatDateTime, mensagemDeErro } from '../services/api'
import {
  CICLO, EDITAVEL, paisApi, PROXIMA_ACAO, ROTULO_PAIS, TERMINAIS_PAIS,
  type Plano, type TipoItem,
} from '../services/pais'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { variantePais } from './Pais'
import { Button } from '../components/ui/button'
import { Input, Label } from '../components/ui/input'
import { Alert, Badge, Skeleton } from '../components/ui/feedback'
import { Dialog, DialogContent } from '../components/ui/dialog'
import { ErrorState } from '../components/ui/states'
import { cn } from '../lib/utils'

type Funcionario = { id: string; nome: string; situacao: string; cargo?: string | null }
const SELECT = 'flex h-12 w-full rounded-lg border border-input bg-card px-3 text-[16px] text-foreground focus-visible:border-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40'
const AREA = 'w-full rounded-lg border border-input bg-card px-3 py-2 text-[16px] focus-visible:border-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40'

const SECOES: { tipo: TipoItem; titulo: string; singular: string }[] = [
  { tipo: 'necessidades', titulo: 'Necessidades', singular: 'necessidade' },
  { tipo: 'metas', titulo: 'Metas', singular: 'meta' },
  { tipo: 'intervencoes', titulo: 'Intervenções', singular: 'intervenção' },
]

/** Detalhe do PAIS (UX-07 / #80): ciclo, próxima ação e conteúdo do plano. */
export function PaisDetalhe() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { pode } = usePermissoesOuPadrao()
  const [plano, setPlano] = useState<Plano | null>(null)
  const [falha, setFalha] = useState<'nao_encontrado' | 'erro' | null>(null)
  const [nome, setNome] = useState<string | null>(null)
  const [equipe, setEquipe] = useState<Funcionario[] | null>(null)
  const [funcionarioId, setFuncionarioId] = useState('')
  const [aviso, setAviso] = useState<{ tipo: 'success' | 'error'; texto: string } | null>(null)
  const [executando, setExecutando] = useState(false)
  const [dialogo, setDialogo] = useState<'encerrar' | 'versao' | TipoItem | null>(null)
  const [anterior, setAnterior] = useState<Plano | null>(null)

  const carregar = useCallback(async () => {
    try {
      const p = await paisApi.obter(id)
      setPlano(p)
      setFalha(null)
      api.get<{ nome: string }>(`/residentes/${p.residente_id}`).then(r => setNome(r.data?.nome || null)).catch(() => setNome(null))
      if (p.anterior_id) paisApi.obter(p.anterior_id).then(setAnterior).catch(() => setAnterior(null))
      else setAnterior(null)
    } catch (e: any) {
      setFalha(e?.response?.status === 404 ? 'nao_encontrado' : 'erro')
    }
  }, [id])

  useEffect(() => { carregar() }, [carregar])
  useEffect(() => {
    // Revisor, aprovador e responsável são designados entre os funcionários
    // ativos (contrato do backend). Sem acesso à equipe, as ações que exigem
    // designação explicam o bloqueio em vez de pedir um id.
    api.get<Funcionario[]>('/funcionarios/').then(r => setEquipe((r.data || []).filter(f => f.situacao === 'ativo'))).catch(() => setEquipe(null))
  }, [])

  async function executar(fn: () => Promise<unknown>, sucesso: string, depois?: (r: any) => void) {
    setExecutando(true)
    setAviso(null)
    try {
      const r = await fn()
      if (depois) depois(r)
      else await carregar()
      setAviso({ tipo: 'success', texto: sucesso })
    } catch (e) {
      await carregar()
      setAviso({ tipo: 'error', texto: mensagemDeErro(e, 'Não foi possível concluir a ação.') })
    } finally {
      setExecutando(false)
      setDialogo(null)
    }
  }

  if (falha === 'nao_encontrado') return <ErrorState title="Plano não encontrado" description={<>Ele pode pertencer a outra instituição. <Link to="/plano" className="font-semibold text-primary underline">Voltar aos planos</Link></>} />
  if (falha === 'erro') return <ErrorState title="Não foi possível carregar o plano" onRetry={carregar} />
  if (!plano) return <div className="space-y-4" aria-label="Carregando plano"><Skeleton className="h-10 w-72" /><Skeleton className="h-24 w-full" /><Skeleton className="h-64 w-full" /></div>

  const p = plano
  const editavel = EDITAVEL.includes(p.situacao) && pode('planos_cuidados:atualizar')
  const proxima = PROXIMA_ACAO[p.situacao]
  const ativos = {
    necessidades: p.necessidades.filter(n => n.situacao === 'ativa'),
    metas: p.metas.filter(m => m.situacao === 'ativa'),
    intervencoes: p.intervencoes.filter(i => i.situacao === 'ativa'),
  }
  const completo = ativos.necessidades.length > 0 && ativos.metas.length > 0 && ativos.intervencoes.length > 0
  const bloqueadoPorVigente = p.situacao === 'aprovado' && anterior?.situacao === 'vigente'
  const nomeFuncionario = (fid: string | null) => (fid && equipe?.find(f => f.id === fid)?.nome) || null

  async function avancar() {
    if (!proxima) return
    const fns = {
      iniciar: () => paisApi.iniciarElaboracao(p.id),
      revisar: () => paisApi.revisar(p.id, funcionarioId),
      aprovar: () => paisApi.aprovar(p.id, funcionarioId),
      ativar: () => paisApi.ativar(p.id),
    }
    await executar(fns[proxima.acao], proxima.sucesso)
    setFuncionarioId('')
  }

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <Link to="/plano" className="inline-flex min-h-[32px] items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" aria-hidden="true" /> Plano de cuidados
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">{nome || 'Residente'}</h1>
            <p className="text-sm text-muted-foreground">
              PAIS versão {p.versao} · desde {formatDate(p.data_inicial)}{p.data_final ? ` até ${formatDate(p.data_final)}` : ''}
              {' · '}<Link to={`/residentes/${p.residente_id}`} className="font-medium text-primary hover:underline">prontuário</Link>
            </p>
          </div>
          <Badge variant={variantePais(p.situacao)} className="text-sm">{ROTULO_PAIS[p.situacao]}</Badge>
        </div>
        {p.objetivos && <p className="rounded-lg bg-muted px-4 py-3 text-sm text-foreground"><strong className="font-semibold">Objetivos:</strong> {p.objetivos}</p>}
        {p.motivo_versao && <p className="text-xs text-muted-foreground">Motivo desta versão: {p.motivo_versao}</p>}
      </div>

      <nav aria-label="Ciclo do plano">
        <ol className="grid grid-cols-5 gap-2">
          {CICLO.map((etapa, i) => {
            const atual = CICLO.indexOf(p.situacao)
            const feito = TERMINAIS_PAIS.includes(p.situacao) || (atual >= 0 && i < atual)
            const corrente = etapa === p.situacao
            return (
              <li key={etapa} aria-current={corrente ? 'step' : undefined} className="flex flex-col items-center gap-1.5 text-center">
                <span className={cn('flex size-8 items-center justify-center rounded-full border-2 text-xs font-semibold',
                  feito && 'border-brand bg-brand text-white', corrente && !feito && 'border-brand bg-brand-soft text-primary ring-4 ring-brand/15',
                  !feito && !corrente && 'border-border bg-card text-muted-foreground')}>
                  {feito ? <Check className="size-4" aria-hidden="true" /> : i + 1}
                </span>
                <span className={cn('text-[11px] leading-tight', corrente ? 'font-semibold text-foreground' : 'text-muted-foreground')}>{ROTULO_PAIS[etapa]}</span>
              </li>
            )
          })}
        </ol>
      </nav>

      {aviso && <Alert variant={aviso.tipo}>{aviso.texto}</Alert>}

      {TERMINAIS_PAIS.includes(p.situacao) && (
        <Alert variant="info" title={p.situacao === 'encerrado' ? `Plano encerrado em ${formatDate(p.encerrado_em)}` : 'Versão substituída'}>
          {p.situacao === 'encerrado' ? `Motivo: ${p.motivo_encerramento}` : p.superseded_by ? <Link to={`/plano/${p.superseded_by}`} className="font-semibold underline">Abrir a versão que a substituiu</Link> : null}
        </Alert>
      )}

      {proxima && pode(proxima.permissao) && (
        <section aria-label="Próxima etapa" className="space-y-3 rounded-card border border-border bg-card p-5 shadow-card">
          <h2 className="font-display text-base font-semibold text-foreground">Próxima etapa: {proxima.rotulo}</h2>
          {proxima.acao === 'aprovar' && (
            <ul className="space-y-1 text-sm">
              {SECOES.map(s => {
                const ok = ativos[s.tipo].length > 0
                return (
                  <li key={s.tipo} className={cn('flex items-center gap-2', ok ? 'text-emerald-800' : 'text-amber-800')}>
                    {ok ? <CheckCircle2 className="size-4" aria-hidden="true" /> : <CircleDot className="size-4" aria-hidden="true" />}
                    Ao menos uma {s.singular} ativa{ok ? '' : ' — pendente'}
                  </li>
                )
              })}
            </ul>
          )}
          {proxima.exigeFuncionario && (
            equipe === null ? (
              <Alert variant="warning">Seu perfil não consegue listar a equipe para indicar quem {proxima.acao === 'revisar' ? 'revisou' : 'aprovou'}. Peça a quem tem acesso à Equipe.</Alert>
            ) : (
              <div className="space-y-2">
                <Label htmlFor="pais-funcionario">{proxima.exigeFuncionario}</Label>
                <select id="pais-funcionario" className={SELECT} value={funcionarioId} onChange={e => setFuncionarioId(e.target.value)}>
                  <option value="">Selecione um funcionário ativo…</option>
                  {equipe.map(f => <option key={f.id} value={f.id}>{f.nome}{f.cargo ? ` · ${f.cargo}` : ''}</option>)}
                </select>
              </div>
            )
          )}
          {bloqueadoPorVigente && anterior && (
            <Alert variant="warning" title="A versão anterior ainda está vigente">
              Para esta versão entrar em vigência, encerre antes a <Link to={`/plano/${anterior.id}`} className="font-semibold underline">versão {anterior.versao}</Link>.
            </Alert>
          )}
          <Button disabled={executando || (!!proxima.exigeFuncionario && !funcionarioId) || (proxima.acao === 'aprovar' && !completo) || bloqueadoPorVigente} onClick={avancar}>
            {executando && <Loader2 className="animate-spin" aria-hidden="true" />} {proxima.rotulo}
          </Button>
        </section>
      )}

      {(p.revisado_em || p.aprovado_em) && (
        <p className="text-xs text-muted-foreground">
          {p.revisado_em && <>Revisado em {formatDateTime(p.revisado_em)}{nomeFuncionario(p.revisor_funcionario_id) ? ` por ${nomeFuncionario(p.revisor_funcionario_id)}` : ''}. </>}
          {p.aprovado_em && <>Aprovado em {formatDateTime(p.aprovado_em)}{nomeFuncionario(p.aprovador_funcionario_id) ? ` por ${nomeFuncionario(p.aprovador_funcionario_id)}` : ''}.</>}
        </p>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {SECOES.map(s => (
          <section key={s.tipo} aria-label={s.titulo} className="space-y-3 rounded-card border border-border bg-card p-5 shadow-card">
            <div className="flex items-center justify-between gap-2">
              <h2 className="font-display text-base font-semibold text-foreground">{s.titulo} <span className="text-sm font-normal text-muted-foreground">({ativos[s.tipo].length})</span></h2>
              {editavel && (
                <Button variant="outline" size="sm" className="h-9" onClick={() => setDialogo(s.tipo)}>
                  <Plus aria-hidden="true" /> Adicionar
                </Button>
              )}
            </div>
            {ativos[s.tipo].length === 0 ? (
              <p className="text-sm text-muted-foreground">Nenhuma {s.singular} ativa.</p>
            ) : (
              <ul className="space-y-2">
                {(ativos[s.tipo] as { id: string; descricao: string }[]).map(item => (
                  <li key={item.id} className="flex items-start gap-2 rounded-lg bg-muted/60 px-3 py-2 text-sm">
                    <div className="min-w-0 flex-1">
                      <p className="text-foreground">{item.descricao}</p>
                      <DetalheItem tipo={s.tipo} item={item} plano={p} nomeFuncionario={nomeFuncionario} />
                    </div>
                    {editavel && (
                      <button type="button" aria-label={`Remover ${s.singular}: ${item.descricao}`} disabled={executando}
                        onClick={() => executar(() => paisApi.inativar(p.id, s.tipo, item.id), `${s.singular[0].toUpperCase()}${s.singular.slice(1)} removida do plano.`)}
                        className="inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-red-50 hover:text-red-700">
                        <Trash2 className="size-4" aria-hidden="true" />
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        ))}
      </div>
      {!EDITAVEL.includes(p.situacao) && !TERMINAIS_PAIS.includes(p.situacao) && (
        <p className="text-sm text-muted-foreground">O conteúdo fica fixo depois da elaboração. Ajustes são feitos em uma nova versão, a partir do plano aprovado ou vigente.</p>
      )}

      {(p.situacao === 'aprovado' || p.situacao === 'vigente') && (pode('planos_cuidados:atualizar') || (p.situacao === 'vigente' && pode('planos_cuidados:encerrar'))) && (
        <section aria-label="Outras ações" className="flex flex-wrap gap-2">
          {pode('planos_cuidados:atualizar') && !p.superseded_by && (
            <Button variant="outline" onClick={() => setDialogo('versao')}><Copy aria-hidden="true" /> Criar nova versão</Button>
          )}
          {p.situacao === 'vigente' && pode('planos_cuidados:encerrar') && (
            <Button variant="ghost" className="text-red-700 hover:bg-red-50" onClick={() => setDialogo('encerrar')}><XCircle aria-hidden="true" /> Encerrar plano</Button>
          )}
        </section>
      )}
      {p.anterior_id && <p className="text-xs text-muted-foreground"><Link to={`/plano/${p.anterior_id}`} className="font-medium text-primary hover:underline">Ver versão anterior</Link></p>}

      {(dialogo === 'necessidades' || dialogo === 'metas' || dialogo === 'intervencoes') && (
        <DialogoItem tipo={dialogo} plano={p} equipe={equipe} aoFechar={() => setDialogo(null)}
          aoSalvar={dados => executar(() => paisApi.adicionar(p.id, dialogo, dados), 'Item adicionado ao plano.')} />
      )}
      {dialogo === 'versao' && (
        <DialogoTexto titulo="Criar nova versão" descricao={p.situacao === 'vigente'
            ? 'A nova versão nasce como rascunho, com as necessidades, metas e intervenções ativas desta. Esta continua vigente enquanto a nova é elaborada; para a nova entrar em vigência, esta precisa ser encerrada.'
            : 'A nova versão nasce como rascunho, com as necessidades, metas e intervenções ativas desta. Ao entrar em vigência, ela substitui esta.'}
          rotulo="Motivo da nova versão" botao="Criar nova versão" aoFechar={() => setDialogo(null)}
          aoConfirmar={motivo => executar(() => paisApi.novaVersao(p.id, motivo), 'Nova versão criada.', (nova: Plano) => navigate(`/plano/${nova.id}`))} />
      )}
      {dialogo === 'encerrar' && (
        <DialogoTexto titulo="Encerrar plano" descricao="O plano deixa de valer. Todo o conteúdo e o histórico são preservados." rotulo="Motivo do encerramento"
          botao="Encerrar plano" destrutiva equipe={equipe} aoFechar={() => setDialogo(null)}
          aoConfirmar={(motivo, fid) => executar(() => paisApi.encerrar(p.id, motivo, fid as string), 'Plano encerrado.')} />
      )}
    </div>
  )
}

function DetalheItem({ tipo, item, plano, nomeFuncionario }: { tipo: TipoItem; item: any; plano: Plano; nomeFuncionario: (id: string | null) => string | null }) {
  const partes: string[] = []
  if (tipo === 'necessidades') partes.push(...[item.categoria, item.gravidade && `gravidade ${item.gravidade}`, item.origem !== 'manual' && `origem: ${item.origem}`].filter(Boolean))
  if (tipo === 'metas') partes.push(...[item.indicador && `indicador: ${item.indicador}`, item.valor_esperado && `esperado: ${item.valor_esperado}`, item.prazo && `prazo ${formatDate(item.prazo)}`, nomeFuncionario(item.responsavel_funcionario_id)].filter(Boolean))
  if (tipo === 'intervencoes') {
    const necessidade = plano.necessidades.find(n => n.id === item.necessidade_id)
    partes.push(...[item.frequencia, item.horario, item.perfil_responsavel, item.prioridade && `prioridade ${item.prioridade}`, necessidade && `para: ${necessidade.descricao}`].filter(Boolean))
  }
  return partes.length ? <p className="text-xs text-muted-foreground">{partes.join(' · ')}</p> : null
}

function DialogoItem({ tipo, plano, equipe, aoFechar, aoSalvar }: {
  tipo: TipoItem; plano: Plano; equipe: Funcionario[] | null; aoFechar: () => void; aoSalvar: (dados: Record<string, string>) => void
}) {
  const [dados, setDados] = useState<Record<string, string>>({})
  const campo = (chave: string) => ({ value: dados[chave] || '', onChange: (e: { target: { value: string } }) => setDados({ ...dados, [chave]: e.target.value }) })
  const titulo = { necessidades: 'Nova necessidade', metas: 'Nova meta', intervencoes: 'Nova intervenção' }[tipo]
  function salvar(e: React.FormEvent) {
    e.preventDefault()
    const limpos = Object.fromEntries(Object.entries(dados).map(([k, v]) => [k, v.trim()]).filter(([, v]) => v))
    aoSalvar(limpos)
  }
  return (
    <Dialog open onOpenChange={a => { if (!a) aoFechar() }}>
      <DialogContent title={titulo}>
        <form onSubmit={salvar} className="space-y-4">
          <div className="space-y-2"><Label htmlFor="item-descricao">Descrição</Label><textarea id="item-descricao" required rows={2} className={AREA} {...campo('descricao')} /></div>
          {tipo === 'necessidades' && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2"><Label htmlFor="item-categoria">Categoria</Label><Input id="item-categoria" {...campo('categoria')} /></div>
              <div className="space-y-2"><Label htmlFor="item-gravidade">Gravidade</Label><Input id="item-gravidade" {...campo('gravidade')} /></div>
            </div>
          )}
          {tipo === 'metas' && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2"><Label htmlFor="item-indicador">Indicador</Label><Input id="item-indicador" {...campo('indicador')} /></div>
                <div className="space-y-2"><Label htmlFor="item-esperado">Valor esperado</Label><Input id="item-esperado" {...campo('valor_esperado')} /></div>
              </div>
              <div className="space-y-2"><Label htmlFor="item-prazo">Prazo</Label><Input id="item-prazo" type="date" {...campo('prazo')} /></div>
              {equipe && (
                <div className="space-y-2">
                  <Label htmlFor="item-responsavel">Responsável (opcional)</Label>
                  <select id="item-responsavel" className={SELECT} {...campo('responsavel_funcionario_id')}>
                    <option value="">Sem responsável definido</option>
                    {equipe.map(f => <option key={f.id} value={f.id}>{f.nome}</option>)}
                  </select>
                </div>
              )}
            </>
          )}
          {tipo === 'intervencoes' && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2"><Label htmlFor="item-frequencia">Frequência</Label><Input id="item-frequencia" {...campo('frequencia')} /></div>
                <div className="space-y-2"><Label htmlFor="item-horario">Horário</Label><Input id="item-horario" maxLength={20} {...campo('horario')} /></div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2"><Label htmlFor="item-perfil">Perfil responsável</Label><Input id="item-perfil" {...campo('perfil_responsavel')} /></div>
                <div className="space-y-2"><Label htmlFor="item-prioridade">Prioridade</Label><Input id="item-prioridade" maxLength={20} {...campo('prioridade')} /></div>
              </div>
              {plano.necessidades.some(n => n.situacao === 'ativa') && (
                <div className="space-y-2">
                  <Label htmlFor="item-necessidade">Atende à necessidade (opcional)</Label>
                  <select id="item-necessidade" className={SELECT} {...campo('necessidade_id')}>
                    <option value="">Nenhuma específica</option>
                    {plano.necessidades.filter(n => n.situacao === 'ativa').map(n => <option key={n.id} value={n.id}>{n.descricao}</option>)}
                  </select>
                </div>
              )}
              <div className="space-y-2"><Label htmlFor="item-instrucoes">Instruções (opcional)</Label><textarea id="item-instrucoes" rows={2} className={AREA} {...campo('instrucoes')} /></div>
            </>
          )}
          <Button type="submit" className="w-full" disabled={!dados.descricao?.trim()}>Adicionar</Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function DialogoTexto({ titulo, descricao, rotulo, botao, destrutiva, equipe, aoFechar, aoConfirmar }: {
  titulo: string; descricao: string; rotulo: string; botao: string; destrutiva?: boolean; equipe?: Funcionario[] | null
  aoFechar: () => void; aoConfirmar: (texto: string, funcionarioId?: string) => void
}) {
  const [texto, setTexto] = useState('')
  const [fid, setFid] = useState('')
  const exigeFuncionario = equipe !== undefined
  return (
    <Dialog open onOpenChange={a => { if (!a) aoFechar() }}>
      <DialogContent title={titulo} description={descricao}>
        <form onSubmit={e => { e.preventDefault(); aoConfirmar(texto.trim(), fid || undefined) }} className="space-y-4">
          {exigeFuncionario && (equipe === null ? (
            <Alert variant="warning">Seu perfil não consegue listar a equipe para designar o responsável.</Alert>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="dt-funcionario">Responsável</Label>
              <select id="dt-funcionario" required className={SELECT} value={fid} onChange={e => setFid(e.target.value)}>
                <option value="">Selecione um funcionário ativo…</option>
                {equipe!.map(f => <option key={f.id} value={f.id}>{f.nome}</option>)}
              </select>
            </div>
          ))}
          <div className="space-y-2"><Label htmlFor="dt-texto">{rotulo}</Label><textarea id="dt-texto" required rows={3} className={AREA} value={texto} onChange={e => setTexto(e.target.value)} /></div>
          <Button type="submit" variant={destrutiva ? 'destructive' : 'default'} className="w-full" disabled={!texto.trim() || (exigeFuncionario && !fid)}>{botao}</Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}

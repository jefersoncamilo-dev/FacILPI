import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Ban, Check, ChevronRight, Clock, Pill, SlidersHorizontal, TriangleAlert, WifiOff, X } from 'lucide-react'
import { formatDateTime, mensagemDeErro } from '../services/api'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { MeuTurno } from '../components/plantao/MeuTurno'
import { MinhaArea } from '../components/plantao/MinhaArea'
import { PainelRegistro } from '../components/plantao/PainelRegistro'
import { meuPlantaoApi, type MeuPlantaoResumo } from '../services/meuPlantao'
import { FUSO_HORARIO_REAL, MENSAGEM_HORARIO, horaAtual, resolverHorario } from '../lib/horarioReal'
import { cn } from '../lib/utils'
import {
  PLANTAO_LIMIT_PADRAO,
  encerrarIntercorrencia,
  getPlantao,
  getResidentesResumo,
  registrarAdministracao,
  registrarExecucaoCuidado,
  rotuloDoItem,
  type PlantaoItem,
  type PlantaoOrigem,
  type ResultadoCuidado,
  type ResultadoDose,
} from '../services/plantao'

// UX-05 (#91): permissão que cada ação exige no backend. Sem ela, a pendência
// continua visível (informa o turno), mas não abre registro.
const PERMISSAO_ACAO: Record<PlantaoOrigem, string> = {
  cuidado: 'execucoes:criar',
  medicacao: 'administracoes:criar',
  intercorrencia: 'intercorrencias:atualizar',
}

const SUCESSO_ACAO: Record<PlantaoOrigem, string> = {
  cuidado: 'Execução registrada',
  medicacao: 'Administração registrada',
  intercorrencia: 'Intercorrência encerrada',
}

const ACAO_ORIGEM: Record<PlantaoOrigem, string> = {
  cuidado: 'Registrar execução',
  medicacao: 'Registrar administração',
  intercorrencia: 'Encerrar',
}

// #136: "Não realizado" mantém recusa e omissão separadas. Os motivos comuns
// vão no texto da `justificativa` (o contrato não tem campo de motivo).
const MOTIVOS_NAO_REALIZADO = [
  'Residente fora do quarto/ausente',
  'Residente dormindo',
  'Contraindicação observada',
  'Falta de material',
  'Outro motivo',
] as const
const OUTRO_MOTIVO = 'Outro motivo'

const ROTULO_CUIDADO: Record<ResultadoCuidado, string> = { executada: 'Realizado', recusada: 'Recusado', omitida: 'Não realizado' }
const ROTULO_DOSE: Record<ResultadoDose, string> = { administrada: 'Administrada', recusada: 'Recusada', omitida: 'Não administrada' }

type Filtro = 'todos' | 'atrasados' | PlantaoOrigem
type Visao = 'atividade' | 'residente'

interface PreferenciasLista { filtro: Filtro; visao: Visao; residente: string }
const CHAVE_PREFERENCIAS = 'facilpi:meu-plantao:lista'
const CHAVE_ROLAGEM = 'facilpi:meu-plantao:rolagem'
const PREFERENCIAS_PADRAO: PreferenciasLista = { filtro: 'todos', visao: 'atividade', residente: '' }

// Armazenamento de conveniência (pode falhar em aba privada): nunca quebra a tela.
function lerSessao<T>(chave: string, padrao: T): T {
  try { const v = sessionStorage.getItem(chave); return v ? { ...padrao, ...JSON.parse(v) } : padrao } catch { return padrao }
}
function gravarSessao(chave: string, valor: unknown) {
  try { sessionStorage.setItem(chave, JSON.stringify(valor)) } catch { /* sem armazenamento */ }
}

interface FormAcao {
  resultadoCuidado: ResultadoCuidado | ''
  resultadoDose: ResultadoDose | ''
  motivoRecusa: string
  motivoNao: string
  detalheNao: string
  hora: string
  quantidade: string
  justificativa: string
  observacao: string
  desfecho: string
}
type ErrosForm = Partial<Record<'resultado' | 'motivoRecusa' | 'motivoNao' | 'detalheNao' | 'hora' | 'quantidade' | 'justificativa' | 'desfecho', string>>

function formVazio(): FormAcao {
  return {
    resultadoCuidado: '', resultadoDose: '', motivoRecusa: '', motivoNao: '', detalheNao: '',
    hora: horaAtual(), quantidade: '', justificativa: '', observacao: '', desfecho: '',
  }
}

const chave = (item: Pick<PlantaoItem, 'origem' | 'registro_id'>) => `${item.origem}:${item.registro_id}`

/**
 * `?desde=` (ISO) amplia o início da projeção para trás — vem da Passagem de
 * Plantão, para que cuidados e doses previstos antes da abertura da tela e
 * ainda sem registro apareçam em "Atrasadas" com as ações de sempre. Sem o
 * parâmetro, a projeção é a padrão do backend (agora → +24 h).
 */
export function lerDesde(valor: string | null, agora = Date.now()): string | null {
  if (!valor) return null
  const t = Date.parse(valor)
  return Number.isFinite(t) && t < agora ? new Date(t).toISOString() : null
}

function atrasado(item: PlantaoItem, agora: number): boolean {
  if (!item.previsto_em) return false
  return new Date(item.previsto_em).getTime() < agora
}

const formatoHora = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', timeZone: FUSO_HORARIO_REAL })
const formatoDia = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', timeZone: FUSO_HORARIO_REAL })
function horaCurta(iso: string): string {
  try { return formatoHora.format(new Date(iso)) } catch { return iso }
}
function diaSeOutro(iso: string, agora: number): string | null {
  try {
    const d = formatoDia.format(new Date(iso))
    return d === formatoDia.format(new Date(agora)) ? null : d
  } catch { return null }
}

/** Ordem da projeção: com horário primeiro (crescente), intercorrências sem horário por último. */
function porPrevisto(a: PlantaoItem, b: PlantaoItem) {
  if (!a.previsto_em && !b.previsto_em) return 0
  if (!a.previsto_em) return 1
  if (!b.previsto_em) return -1
  return new Date(a.previsto_em).getTime() - new Date(b.previsto_em).getTime()
}

interface Registrado { item: PlantaoItem; texto: string }

export function MeuPlantao() {
  const { pode } = usePermissoesOuPadrao()
  const [params] = useSearchParams()
  const desde = lerDesde(params.get('desde'))
  const [itens, setItens] = useState<PlantaoItem[]>([])
  const [carregando, setCarregando] = useState(true)
  // `erro` separado de lista vazia: sem essa distinção um 403 viraria
  // "nenhuma pendência" na tela do plantonista.
  const [erro, setErro] = useState('')
  const [nomes, setNomes] = useState<Record<string, string>>({})
  const [prefs, setPrefs] = useState<PreferenciasLista>(() => lerSessao(CHAVE_PREFERENCIAS, PREFERENCIAS_PADRAO))
  // #136: o que foi registrado nesta tela continua na posição em que estava, com o
  // resultado em texto — a lista não "pula" depois de salvar.
  const [registrados, setRegistrados] = useState<Record<string, Registrado>>({})
  const [aviso, setAviso] = useState('')

  const [itemAberto, setItemAberto] = useState<PlantaoItem | null>(null)
  const [form, setForm] = useState<FormAcao>(formVazio)
  const [erros, setErros] = useState<ErrosForm>({})
  const [erroAcao, setErroAcao] = useState('')
  const [semConexao, setSemConexao] = useState(false)
  const [salvando, setSalvando] = useState(false)
  const [filtrosAbertos, setFiltrosAbertos] = useState(false)
  // Rascunho por item: fechar o painel sem salvar não apaga o que foi preenchido.
  const rascunhos = useRef<Record<string, FormAcao>>({})

  useEffect(() => { gravarSessao(CHAVE_PREFERENCIAS, prefs) }, [prefs])

  const carregar = useCallback(async (opcoes: { silencioso?: boolean } = {}): Promise<PlantaoItem[] | null> => {
    if (!opcoes.silencioso) setCarregando(true)
    try {
      const data = await getPlantao(desde ? { a_partir_de: desde } : {})
      setItens(data)
      setErro('')
      return data
    } catch (e) {
      // Recarga silenciosa (depois de salvar) não troca a lista por um erro: a
      // tela continua com o que já mostrava.
      if (!opcoes.silencioso) {
        setItens([])
        setErro(mensagemDeErro(e, 'Não foi possível carregar o plantão.'))
      }
      return null
    } finally {
      if (!opcoes.silencioso) setCarregando(false)
    }
  }, [desde])

  useEffect(() => { carregar() }, [carregar])

  // #126: recorte do plantão pela área (só com plantão ativo e com o que o perfil lê).
  const [resumo, setResumo] = useState<MeuPlantaoResumo | null>(null)
  // Só a resposta mais recente vale: um resumo antigo não "desfaz" o plantão recém-encerrado.
  const pedidoResumo = useRef(0)
  const carregarResumo = useCallback(() => {
    const pedido = ++pedidoResumo.current
    meuPlantaoApi.resumo()
      .then(r => { if (pedido === pedidoResumo.current) setResumo(r) })
      .catch(() => { if (pedido === pedidoResumo.current) setResumo(null) })
  }, [])
  useEffect(() => { carregarResumo() }, [carregarResumo])
  const aoMudarAlerta = useCallback(() => { carregarResumo(); void carregar({ silencioso: true }) }, [carregarResumo, carregar])

  useEffect(() => {
    // Auxiliar: a falha aqui não vira erro de tela, só mantém o id como rótulo.
    getResidentesResumo()
      .then(lista => setNomes(Object.fromEntries(lista.map(r => [r.id, r.nome]))))
      .catch(() => setNomes({}))
  }, [])

  // Local (quarto/leito) só existe no recorte da área; sem ele, o nome identifica.
  const locais = useMemo(() => Object.fromEntries((resumo?.residentes ?? []).map(r => [r.id, r.local ?? ''])), [resumo])
  const nomeDe = (id: string) => nomes[id] || id

  // Rolagem: volta ao mesmo ponto ao retornar para a tela. A posição é gravada
  // enquanto a pessoa rola — na desmontagem a janela já reflete a tela seguinte.
  const rolagemRestaurada = useRef(false)
  useEffect(() => {
    let quadro = 0
    const aoRolar = () => {
      cancelAnimationFrame(quadro)
      quadro = requestAnimationFrame(() => {
        if (rolagemRestaurada.current && window.location.pathname === '/plantao') gravarSessao(CHAVE_ROLAGEM, { y: window.scrollY })
      })
    }
    window.addEventListener('scroll', aoRolar, { passive: true })
    return () => { cancelAnimationFrame(quadro); window.removeEventListener('scroll', aoRolar) }
  }, [])
  useEffect(() => {
    if (carregando || rolagemRestaurada.current) return
    rolagemRestaurada.current = true
    const { y } = lerSessao(CHAVE_ROLAGEM, { y: 0 })
    if (y > 0) window.scrollTo?.(0, y)
  }, [carregando])

  useEffect(() => {
    if (!aviso) return
    const t = setTimeout(() => setAviso(''), 5000)
    return () => clearTimeout(t)
  }, [aviso])

  // A tela fica aberta durante o plantão: o "Atrasada" precisa aparecer quando o
  // horário passa, sem esperar outra interação. Só re-renderiza; não chama a API.
  const [, setRelogio] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setRelogio(n => n + 1), 30_000)
    return () => clearInterval(id)
  }, [])
  const agora = Date.now()

  // Pendências da projeção + o que foi registrado aqui (na mesma posição).
  const todos = useMemo(() => {
    const presentes = new Set(itens.map(chave))
    const extras = Object.values(registrados).filter(r => !presentes.has(chave(r.item))).map(r => r.item)
    return [...itens, ...extras].sort(porPrevisto)
  }, [itens, registrados])

  const pendente = (item: PlantaoItem) => !registrados[chave(item)]
  const baseResidente = prefs.residente ? todos.filter(i => i.residente_id === prefs.residente) : todos

  const contagens = useMemo(() => {
    const p = baseResidente.filter(pendente)
    return {
      todos: p.length,
      atrasados: p.filter(i => atrasado(i, agora)).length,
      cuidado: p.filter(i => i.origem === 'cuidado').length,
      medicacao: p.filter(i => i.origem === 'medicacao').length,
      intercorrencia: p.filter(i => i.origem === 'intercorrencia').length,
    } as Record<Filtro, number>
  }, [baseResidente, registrados, agora])

  const lista = baseResidente.filter(item => {
    if (prefs.filtro === 'todos') return true
    if (prefs.filtro === 'atrasados') return pendente(item) && atrasado(item, agora)
    return item.origem === prefs.filtro
  })

  // Ordem em que "Salvar e próximo" percorre a lista (a mesma que a pessoa vê).
  const ordemVisivel = useMemo(() => {
    if (prefs.visao === 'residente') {
      const ids: string[] = []
      for (const i of lista) if (!ids.includes(i.residente_id)) ids.push(i.residente_id)
      return ids.flatMap(id => lista.filter(i => i.residente_id === id))
    }
    return [
      ...lista.filter(i => atrasado(i, agora)),
      ...lista.filter(i => i.previsto_em && !atrasado(i, agora)),
      ...lista.filter(i => !i.previsto_em),
    ]
  }, [lista, prefs.visao, agora])

  /** Próximo cuidado elegível: sem registro, com permissão, dentro dos filtros. Medicação e intercorrência não entram. */
  function proximoCuidado(atual: string, ignorar: string[] = []): PlantaoItem | null {
    const elegiveis = ordemVisivel.filter(i => i.origem === 'cuidado' && pode(PERMISSAO_ACAO.cuidado))
    const idx = elegiveis.findIndex(i => chave(i) === atual)
    const sequencia = idx >= 0 ? [...elegiveis.slice(idx + 1), ...elegiveis.slice(0, idx)] : elegiveis
    return sequencia.find(i => chave(i) !== atual && !ignorar.includes(chave(i)) && pendente(i)) ?? null
  }

  function abrir(item: PlantaoItem) {
    setItemAberto(item)
    setForm(rascunhos.current[chave(item)] ?? formVazio())
    setErros({})
    setErroAcao('')
    setSemConexao(false)
  }

  function fechar() {
    if (itemAberto) rascunhos.current[chave(itemAberto)] = form
    setItemAberto(null)
    setErroAcao('')
    setSemConexao(false)
  }

  const atualizar = (parcial: Partial<FormAcao>) => setForm(f => ({ ...f, ...parcial }))

  // Espelha as validações do backend para não gastar uma ida ao servidor com um 422 previsível.
  function validar(item: PlantaoItem): ErrosForm {
    const e: ErrosForm = {}
    if (item.origem === 'cuidado') {
      if (!form.resultadoCuidado) e.resultado = 'Escolha o resultado.'
      if (form.resultadoCuidado === 'recusada' && !form.motivoRecusa.trim()) e.motivoRecusa = 'Descreva o motivo da recusa.'
      if (form.resultadoCuidado === 'omitida' && !form.motivoNao) e.motivoNao = 'Escolha o motivo.'
      if (form.resultadoCuidado === 'omitida' && form.motivoNao === OUTRO_MOTIVO && !form.detalheNao.trim()) e.detalheNao = 'Descreva o motivo.'
      const h = resolverHorario(form.hora)
      if (!h.ok) e.hora = MENSAGEM_HORARIO[h.erro]
    } else if (item.origem === 'medicacao') {
      if (!form.resultadoDose) e.resultado = 'Escolha o resultado.'
      if (form.resultadoDose === 'administrada') {
        const q = Number(form.quantidade)
        if (!form.quantidade.trim() || Number.isNaN(q) || q <= 0) e.quantidade = 'Informe a quantidade realizada (maior que zero).'
      } else if (form.resultadoDose && !form.justificativa.trim()) {
        e.justificativa = 'Justificativa obrigatória para recusa ou omissão.'
      }
    } else if (!form.desfecho.trim()) {
      e.desfecho = 'Informe o desfecho da intercorrência.'
    }
    return e
  }

  function justificativaCuidado(): string | undefined {
    if (form.resultadoCuidado === 'recusada') return form.motivoRecusa.trim()
    if (form.resultadoCuidado === 'omitida') return form.detalheNao.trim() ? `${form.motivoNao}: ${form.detalheNao.trim()}` : form.motivoNao
    return undefined
  }

  async function salvar(destino: 'fechar' | 'proximo') {
    const item = itemAberto
    if (!item || salvando) return // evita duplo toque
    const invalidos = validar(item)
    setErros(invalidos)
    if (Object.keys(invalidos).length) {
      requestAnimationFrame(() => document.querySelector<HTMLElement>('[data-painel-registro] [aria-invalid="true"], [data-painel-registro] input[name="resultado"]')?.focus())
      return
    }
    const k = chave(item)
    setSalvando(true)
    setErroAcao('')
    setSemConexao(false)
    let texto = ''
    try {
      if (item.origem === 'cuidado') {
        const h = resolverHorario(form.hora)
        const ocorrido_em = h.ok ? h.iso : new Date().toISOString()
        const just = justificativaCuidado()
        await registrarExecucaoCuidado({
          ocorrencia_id: item.registro_id,
          resultado: form.resultadoCuidado as ResultadoCuidado,
          ocorrido_em,
          ...(form.observacao.trim() ? { observacao: form.observacao.trim() } : {}),
          ...(just ? { justificativa: just } : {}),
        })
        texto = `${ROTULO_CUIDADO[form.resultadoCuidado as ResultadoCuidado]} às ${horaCurta(ocorrido_em)}`
      } else if (item.origem === 'medicacao') {
        // Fluxo de doses mantido: o instante é o de agora, como antes.
        const ocorrido_em = new Date().toISOString()
        await registrarAdministracao({
          dose_prevista_id: item.registro_id,
          resultado: form.resultadoDose as ResultadoDose,
          ocorrido_em,
          ...(form.resultadoDose === 'administrada' ? { quantidade_realizada: Number(form.quantidade) } : {}),
          ...(form.resultadoDose !== 'administrada' && form.justificativa.trim() ? { justificativa: form.justificativa.trim() } : {}),
          ...(form.observacao.trim() ? { observacao: form.observacao.trim() } : {}),
        })
        texto = `${ROTULO_DOSE[form.resultadoDose as ResultadoDose]} às ${horaCurta(ocorrido_em)}`
      } else {
        await encerrarIntercorrencia(item.registro_id, form.desfecho.trim())
        texto = 'Encerrada'
      }
      delete rascunhos.current[k]
      setRegistrados(r => ({ ...r, [k]: { item, texto } }))
      // A fonte mudou: projeção e resumo da área são relidos sem trocar a lista por "Carregando".
      void carregar({ silencioso: true })
      carregarResumo()
      const msg = `${SUCESSO_ACAO[item.origem]}: ${rotuloDoItem(item)} · ${nomeDe(item.residente_id)} — ${texto}.`
      if (destino === 'proximo') {
        const prox = proximoCuidado(k, [k])
        if (prox) { setAviso(msg); abrir(prox); return }
        setAviso(`${msg} Não há mais cuidados pendentes neste filtro.`)
      } else {
        setAviso(msg)
      }
      setItemAberto(null)
    } catch (e) {
      const resposta = (e as { response?: { status?: number } })?.response
      if (!resposta) {
        // Sem resposta: nada foi confirmado. O formulário fica como está para tentar de novo.
        setSemConexao(true)
        setErroAcao('Sem conexão com o servidor. Nada foi confirmado. O que você preencheu continua aqui.')
      } else if (resposta.status === 409) {
        // 409 cobre "já tem execução vigente" e outros conflitos. Só a projeção diz
        // se o item deixou de estar pendente; nesse caso não há o que repetir.
        const nova = await carregar({ silencioso: true })
        if (nova && !nova.some(i => chave(i) === k)) {
          delete rascunhos.current[k]
          setRegistrados(r => ({ ...r, [k]: { item, texto: 'Já tinha registro' } }))
          setAviso('Este item não está mais pendente. Nenhum registro duplicado foi criado.')
          setItemAberto(null)
        } else {
          setErroAcao(mensagemDeErro(e, 'Não foi possível registrar.'))
        }
      } else {
        setErroAcao(mensagemDeErro(e, 'Não foi possível registrar.'))
        void carregar({ silencioso: true })
      }
    } finally {
      setSalvando(false)
    }
  }

  // ---------- Filtros ----------
  const chipsRef = useRef<HTMLDivElement>(null)
  const [chipsMais, setChipsMais] = useState(false)
  const medirChips = useCallback(() => {
    const c = chipsRef.current
    if (c) setChipsMais(c.scrollLeft + c.clientWidth < c.scrollWidth - 4)
  }, [])
  useEffect(() => {
    medirChips()
    window.addEventListener('resize', medirChips)
    return () => window.removeEventListener('resize', medirChips)
  }, [medirChips, carregando, contagens])

  const opcoesFiltro: { value: Filtro; label: string }[] = [
    { value: 'todos', label: 'Todos' },
    { value: 'atrasados', label: 'Atrasados' },
    { value: 'cuidado', label: 'Cuidados' },
    { value: 'medicacao', label: 'Medicação' },
    { value: 'intercorrencia', label: 'Intercorrências' },
  ]
  const residentesNaLista = useMemo(() => {
    const ids: string[] = []
    for (const i of todos) if (!ids.includes(i.residente_id)) ids.push(i.residente_id)
    return ids.map(id => ({ id, nome: nomeDe(id) })).sort((a, b) => a.nome.localeCompare(b.nome, 'pt-BR'))
  }, [todos, nomes])

  // ---------- Linha ----------
  function estadoDoItem(item: PlantaoItem): { texto: string; icone: ReactNode; classe: string } {
    const reg = registrados[chave(item)]
    if (reg) return { texto: reg.texto, icone: <Check className="size-3.5" aria-hidden="true" />, classe: 'border-emerald-200 bg-emerald-50 text-emerald-800' }
    if (!item.previsto_em) return { texto: 'Em aberto', icone: <TriangleAlert className="size-3.5" aria-hidden="true" />, classe: 'border-red-200 bg-red-50 text-red-700' }
    if (atrasado(item, agora)) return { texto: 'Atrasada', icone: <Clock className="size-3.5" aria-hidden="true" />, classe: 'border-orange-200 bg-orange-50 text-orange-800' }
    return { texto: 'Pendente', icone: <Clock className="size-3.5" aria-hidden="true" />, classe: 'border-border bg-muted text-slate-700' }
  }

  // Funções de render (não componentes): definidas aqui dentro, componentes seriam
  // recriados a cada render e os campos perderiam o foco.
  function linha(item: PlantaoItem, comResidente: boolean) {
    const k = chave(item)
    const reg = registrados[k]
    const podeAgir = pode(PERMISSAO_ACAO[item.origem]) && !reg
    const estado = estadoDoItem(item)
    const rotulo = rotuloDoItem(item)
    const nome = nomeDe(item.residente_id)
    const local = locais[item.residente_id]
    const dia = item.previsto_em ? diaSeOutro(item.previsto_em, agora) : null
    const conteudo = (
      <>
        <span className="w-12 shrink-0 text-sm font-bold tabular-nums text-foreground">
          {item.previsto_em ? horaCurta(item.previsto_em) : '—'}
          {dia && <span className="block text-[11px] font-normal text-muted-foreground">{dia}</span>}
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="flex items-center gap-1.5 font-medium text-foreground">
            {item.origem === 'medicacao' && <Pill className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />}
            {item.origem === 'intercorrencia' && <TriangleAlert className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />}
            <span className="min-w-0 break-words">{rotulo}</span>
          </span>
          {comResidente && <span className="text-xs text-muted-foreground">{nome}{local ? ` · ${local}` : ''}</span>}
          <span className="flex flex-wrap gap-1">
            <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold', estado.classe)}>{estado.icone}{estado.texto}</span>
            {item.prioridade === 'alta' && !reg && <span className="inline-flex items-center rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700">Prioridade alta</span>}
          </span>
        </span>
      </>
    )
    const base = 'flex w-full items-center gap-3 border-t border-border px-3 py-2.5 text-left first:border-t-0 min-h-[56px]'
    if (!podeAgir) {
      return <div key={k} id={`linha-${k}`} tabIndex={-1} className={cn(base, 'bg-card focus:outline-none')}>{conteudo}</div>
    }
    return (
      <button
        key={k}
        type="button"
        id={`linha-${k}`}
        onClick={() => abrir(item)}
        aria-label={`${ACAO_ORIGEM[item.origem]}: ${rotulo}, ${nome}${item.previsto_em ? `, previsto ${horaCurta(item.previsto_em)}` : ''}, ${estado.texto}`}
        className={cn(base, 'bg-card transition-colors hover:bg-slate-50 active:bg-muted', itemAberto && chave(itemAberto) === k && 'bg-brand-soft')}
      >
        {conteudo}
        <ChevronRight className="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
      </button>
    )
  }

  // ---------- Painel ----------
  function erroCampo(campo: keyof ErrosForm, id: string) {
    return erros[campo] ? <p id={id} className="text-sm font-semibold text-red-700">{erros[campo]}</p> : null
  }
  const invalido = (campo: keyof ErrosForm, id: string) => (erros[campo] ? { 'aria-invalid': true as const, 'aria-describedby': id } : {})

  function opcoesResultado<T extends string>(valor: T | '', opcoes: { v: T; rotulo: string; icone: ReactNode; tom: string }[], aoEscolher: (v: T) => void) {
    return (
      <div className="mt-2 grid grid-cols-3 gap-2">
        {opcoes.map(o => (
          <label key={o.v} className="relative">
            <input
              type="radio"
              name="resultado"
              value={o.v}
              checked={valor === o.v}
              disabled={salvando}
              onChange={() => aoEscolher(o.v)}
              className="peer absolute inset-0 opacity-0"
              {...(erros.resultado ? { 'aria-describedby': 'erro-resultado' } : {})}
            />
            <span className={cn(
              'flex min-h-[64px] cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border-2 border-input bg-card px-1 py-2 text-center text-[13px] font-semibold leading-tight transition-colors',
              'peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 peer-disabled:opacity-60',
              valor === o.v && o.tom,
            )}>
              {o.icone}{o.rotulo}
            </span>
          </label>
        ))}
      </div>
    )
  }

  function montarPainel(item: PlantaoItem) {
    const nome = nomeDe(item.residente_id)
    const local = locais[item.residente_id]
    const estado = estadoDoItem(item)
    const cabecalho = (
      <>
        <p className="font-semibold text-foreground">{nome}</p>
        {local && <p className="whitespace-nowrap text-muted-foreground">{local}</p>}
        <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {item.previsto_em
            ? `Previsto ${horaCurta(item.previsto_em)}${diaSeOutro(item.previsto_em, agora) ? ` · ${diaSeOutro(item.previsto_em, agora)}` : ''}`
            : 'Sem horário previsto'}
          <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-semibold', estado.classe)}>{estado.icone}{estado.texto}</span>
        </p>
      </>
    )
    const alertaErro = erroAcao ? (
      <div role="alert" tabIndex={-1} className="flex gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-800">
        {semConexao ? <WifiOff className="mt-0.5 size-4 shrink-0" aria-hidden="true" /> : <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />}
        <span>{erroAcao}</span>
      </div>
    ) : null
    const textoBotao = (padrao: string) => (salvando ? 'Salvando…' : semConexao ? 'Tentar de novo' : padrao)

    if (item.origem === 'cuidado') {
      const h = resolverHorario(form.hora)
      return {
        cabecalho,
        corpo: (
          <>
            {alertaErro}
            <fieldset>
              <legend className="text-sm font-semibold">Resultado obrigatório</legend>
              {opcoesResultado<ResultadoCuidado>(
                form.resultadoCuidado,
                [
                  { v: 'executada', rotulo: 'Realizado', icone: <Check className="size-5" aria-hidden="true" />, tom: 'border-primary bg-brand-soft text-brand-ink' },
                  { v: 'recusada', rotulo: 'Recusado', icone: <X className="size-5" aria-hidden="true" />, tom: 'border-violet-500 bg-violet-50 text-violet-800' },
                  { v: 'omitida', rotulo: 'Não realizado', icone: <Ban className="size-5" aria-hidden="true" />, tom: 'border-slate-500 bg-slate-100 text-slate-800' },
                ],
                v => { atualizar({ resultadoCuidado: v }); setErros({}) },
              )}
              {erroCampo('resultado', 'erro-resultado')}
            </fieldset>
            {form.resultadoCuidado === 'recusada' && (
              <div className="space-y-1">
                <label htmlFor="motivo-recusa" className="text-sm font-semibold">Motivo da recusa (obrigatório)</label>
                <textarea id="motivo-recusa" className="input min-h-[72px]" value={form.motivoRecusa} disabled={salvando}
                  onChange={e => atualizar({ motivoRecusa: e.target.value })} {...invalido('motivoRecusa', 'erro-motivo-recusa')} />
                {erroCampo('motivoRecusa', 'erro-motivo-recusa')}
              </div>
            )}
            {form.resultadoCuidado === 'omitida' && (
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <label htmlFor="motivo-nao" className="text-sm font-semibold">Por que não foi realizado? (obrigatório)</label>
                  <select id="motivo-nao" className="input" value={form.motivoNao} disabled={salvando}
                    onChange={e => atualizar({ motivoNao: e.target.value })} {...invalido('motivoNao', 'erro-motivo-nao')}>
                    <option value="">Selecione…</option>
                    {MOTIVOS_NAO_REALIZADO.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                  {erroCampo('motivoNao', 'erro-motivo-nao')}
                </div>
                <div className="space-y-1">
                  <label htmlFor="detalhe-nao" className="text-sm font-semibold">Detalhe {form.motivoNao === OUTRO_MOTIVO ? '(obrigatório)' : '(opcional)'}</label>
                  <input id="detalhe-nao" className="input" value={form.detalheNao} disabled={salvando}
                    onChange={e => atualizar({ detalheNao: e.target.value })} {...invalido('detalheNao', 'erro-detalhe-nao')} />
                  {erroCampo('detalheNao', 'erro-detalhe-nao')}
                </div>
              </div>
            )}
            <div className="space-y-1">
              <label htmlFor="hora-real" className="text-sm font-semibold">Horário real do cuidado</label>
              <div className="flex gap-2">
                <input id="hora-real" type="time" className="input min-w-0 flex-1" value={form.hora} disabled={salvando}
                  onChange={e => atualizar({ hora: e.target.value })}
                  {...(erros.hora ? { 'aria-invalid': true as const, 'aria-describedby': 'erro-hora' } : { 'aria-describedby': 'dica-hora' })} />
                <button type="button" disabled={salvando} onClick={() => { atualizar({ hora: horaAtual() }); setErros(x => ({ ...x, hora: undefined })) }}
                  className="min-h-[44px] shrink-0 rounded-lg border border-input bg-card px-4 text-sm font-semibold hover:bg-muted">
                  Agora
                </button>
              </div>
              {erros.hora
                ? erroCampo('hora', 'erro-hora')
                : <p id="dica-hora" className="text-xs text-muted-foreground">Informe quando o cuidado aconteceu.{h.ok && h.ontem ? ' (ontem)' : ''}</p>}
            </div>
            <div className="space-y-1">
              <label htmlFor="observacao" className="text-sm font-semibold">Observação (opcional)</label>
              <textarea id="observacao" className="input min-h-[64px]" value={form.observacao} disabled={salvando}
                onChange={e => atualizar({ observacao: e.target.value })} />
            </div>
          </>
        ),
        rodape: (
          <>
            <button type="button" onClick={() => salvar('fechar')} disabled={salvando || !form.resultadoCuidado}
              className="min-h-[44px] flex-1 rounded-lg border border-input bg-card px-4 font-semibold hover:bg-muted disabled:opacity-50">
              {textoBotao('Salvar')}
            </button>
            <button type="button" onClick={() => salvar('proximo')} disabled={salvando || !form.resultadoCuidado} className="btn-primary flex-1">
              {salvando ? 'Aguarde…' : semConexao ? 'Tentar e ir ao próximo' : 'Salvar e próximo'}
            </button>
          </>
        ),
      }
    }

    if (item.origem === 'medicacao') {
      return {
        cabecalho,
        corpo: (
          <>
            {alertaErro}
            <fieldset>
              <legend className="text-sm font-semibold">Resultado obrigatório</legend>
              {opcoesResultado<ResultadoDose>(
                form.resultadoDose,
                [
                  { v: 'administrada', rotulo: 'Administrada', icone: <Check className="size-5" aria-hidden="true" />, tom: 'border-primary bg-brand-soft text-brand-ink' },
                  { v: 'recusada', rotulo: 'Recusada', icone: <X className="size-5" aria-hidden="true" />, tom: 'border-violet-500 bg-violet-50 text-violet-800' },
                  { v: 'omitida', rotulo: 'Não administrada', icone: <Ban className="size-5" aria-hidden="true" />, tom: 'border-slate-500 bg-slate-100 text-slate-800' },
                ],
                v => { atualizar({ resultadoDose: v }); setErros({}) },
              )}
              {erroCampo('resultado', 'erro-resultado')}
            </fieldset>
            {form.resultadoDose === 'administrada' && (
              <div className="space-y-1">
                <label htmlFor="quantidade" className="text-sm font-semibold">Quantidade realizada (obrigatória)</label>
                <input id="quantidade" className="input" type="number" min="0" step="any" inputMode="decimal" value={form.quantidade} disabled={salvando}
                  onChange={e => atualizar({ quantidade: e.target.value })} {...invalido('quantidade', 'erro-quantidade')} />
                {erroCampo('quantidade', 'erro-quantidade')}
              </div>
            )}
            {(form.resultadoDose === 'recusada' || form.resultadoDose === 'omitida') && (
              <div className="space-y-1">
                <label htmlFor="justificativa-dose" className="text-sm font-semibold">Justificativa (obrigatória)</label>
                <textarea id="justificativa-dose" className="input min-h-[64px]" value={form.justificativa} disabled={salvando}
                  onChange={e => atualizar({ justificativa: e.target.value })} {...invalido('justificativa', 'erro-justificativa')} />
                {erroCampo('justificativa', 'erro-justificativa')}
              </div>
            )}
            <div className="space-y-1">
              <label htmlFor="observacao" className="text-sm font-semibold">Observação (opcional)</label>
              <textarea id="observacao" className="input min-h-[64px]" value={form.observacao} disabled={salvando}
                onChange={e => atualizar({ observacao: e.target.value })} />
            </div>
            <p className="text-xs text-muted-foreground">O horário da administração é o do registro.</p>
          </>
        ),
        rodape: (
          <button type="button" onClick={() => salvar('fechar')} disabled={salvando || !form.resultadoDose} className="btn-primary flex-1">
            {textoBotao('Registrar administração')}
          </button>
        ),
      }
    }

    return {
      cabecalho,
      corpo: (
        <>
          {alertaErro}
          <div className="space-y-1">
            <label htmlFor="desfecho" className="text-sm font-semibold">Desfecho (obrigatório)</label>
            <textarea id="desfecho" className="input min-h-[72px]" value={form.desfecho} disabled={salvando}
              onChange={e => atualizar({ desfecho: e.target.value })} {...invalido('desfecho', 'erro-desfecho')} />
            {erroCampo('desfecho', 'erro-desfecho')}
          </div>
        </>
      ),
      rodape: (
        <button type="button" onClick={() => salvar('fechar')} disabled={salvando} className="btn-primary flex-1">
          {textoBotao('Encerrar intercorrência')}
        </button>
      ),
    }
  }

  const painel = itemAberto ? montarPainel(itemAberto) : null

  // ---------- Grupos ----------
  const grupos = prefs.visao === 'atividade'
    ? [
        // UX-05: agrupado pela pergunta do turno — o que já passou da hora, o que vem
        // a seguir, e o que não tem horário. A ordem dentro do grupo é a da projeção.
        { titulo: 'Atrasadas', itens: lista.filter(i => atrasado(i, agora)) },
        { titulo: 'Próximas', itens: lista.filter(i => i.previsto_em && !atrasado(i, agora)) },
        { titulo: 'Intercorrências abertas', itens: lista.filter(i => !i.previsto_em) },
      ].filter(g => g.itens.length > 0)
    : []
  const porResidente = prefs.visao === 'residente'
    ? (() => {
        const ids: string[] = []
        for (const i of lista) if (!ids.includes(i.residente_id)) ids.push(i.residente_id)
        return ids.map(id => ({ id, itens: lista.filter(i => i.residente_id === id) }))
      })()
    : []
  const pendentesAtrasados = contagens.atrasados

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-foreground sm:text-2xl">Meu Plantão</h1>
        <p className="text-sm text-muted-foreground">
          {desde
            ? <>Desde {formatDateTime(desde)} e próximas 24 h · <Link to="/plantao" className="font-medium text-primary hover:underline">ver só a partir de agora</Link></>
            : 'Próximas 24 h · cuidados, doses e intercorrências'}
        </p>
      </div>

      {/* #120: início/fim do próprio plantão e por quais áreas responde (só com plantao:registrar). */}
      <MeuTurno onMudou={carregarResumo} />
      {resumo && <MinhaArea resumo={resumo} podeAssumir={pode('alertas:assumir')} onMudou={aoMudarAlerta} />}

      <div className="space-y-2">
        <div className="relative -mx-4 sm:mx-0">
          <div ref={chipsRef} onScroll={medirChips} role="group" aria-label="Filtrar pendências (deslize para ver mais)"
            className="flex gap-2 overflow-x-auto px-4 [scrollbar-width:none] sm:px-0 [&::-webkit-scrollbar]:hidden">
            {opcoesFiltro.map(o => {
              const ativo = prefs.filtro === o.value
              return (
                <button key={o.value} type="button" aria-pressed={ativo}
                  onClick={() => setPrefs(p => ({ ...p, filtro: ativo && o.value !== 'todos' ? 'todos' : o.value }))}
                  className="flex min-h-[44px] shrink-0 items-center">
                  <span className={cn(
                    'inline-flex h-9 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 text-sm font-medium transition-colors',
                    ativo ? 'border-foreground bg-foreground text-white' : 'border-border bg-card text-foreground hover:bg-muted',
                  )}>
                    {o.label} <span className={ativo ? 'text-slate-300' : 'text-muted-foreground'}>{contagens[o.value]}</span>
                  </span>
                </button>
              )
            })}
          </div>
          {chipsMais && (
            <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 right-0 flex w-14 items-center justify-end bg-gradient-to-l from-background via-background/90 to-transparent pr-1 text-muted-foreground">
              <ChevronRight className="size-5" />
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          <div role="group" aria-label="Organizar lista" className="flex flex-1 overflow-hidden rounded-lg border border-border bg-card">
            {([{ v: 'atividade', l: 'Por atividade' }, { v: 'residente', l: 'Por residente' }] as const).map(o => (
              <button key={o.v} type="button" aria-pressed={prefs.visao === o.v} onClick={() => setPrefs(p => ({ ...p, visao: o.v }))}
                className={cn('min-h-[44px] flex-1 px-2 text-sm transition-colors', prefs.visao === o.v ? 'bg-brand-soft font-semibold text-brand-ink' : 'text-foreground hover:bg-muted')}>
                {o.l}
              </button>
            ))}
          </div>
          <button type="button" id="botao-filtros" onClick={() => setFiltrosAbertos(true)}
            className="inline-flex min-h-[44px] shrink-0 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-sm hover:bg-muted">
            <SlidersHorizontal className="size-4" aria-hidden="true" />Filtros
            {prefs.residente && <span className="rounded-full bg-primary px-1.5 text-[11px] font-bold text-primary-foreground">1</span>}
          </button>
        </div>

        {prefs.residente && (
          <button type="button" onClick={() => setPrefs(p => ({ ...p, residente: '' }))} aria-label={`Remover filtro de residente: ${nomeDe(prefs.residente)}`}
            className="inline-flex min-h-[44px] items-center">
            <span className="inline-flex h-9 items-center gap-1 rounded-full border border-emerald-200 bg-brand-soft px-3 text-sm font-medium text-brand-ink">
              {nomeDe(prefs.residente)} <X className="size-4" aria-hidden="true" />
            </span>
          </button>
        )}
      </div>

      {pendentesAtrasados > 0 && !erro && prefs.filtro !== 'atrasados' && (
        <p className="text-sm font-medium text-orange-900">
          <Clock className="mr-1 inline size-4 text-orange-800" aria-hidden="true" />
          {pendentesAtrasados} {pendentesAtrasados === 1 ? 'pendência atrasada' : 'pendências atrasadas'}
        </p>
      )}

      {itens.length >= PLANTAO_LIMIT_PADRAO && !erro && (
        <div className="rounded-lg border border-orange-200 bg-orange-50 px-4 py-3">
          <span className="text-sm text-muted-foreground">Exibindo as primeiras {PLANTAO_LIMIT_PADRAO} pendências. Pode haver mais no período.</span>
        </div>
      )}

      {carregando ? (
        <div className="card py-16 text-center text-muted-foreground">Carregando plantão…</div>
      ) : erro ? (
        <div className="card py-10 text-center" role="alert">
          <TriangleAlert className="mx-auto mb-3 size-7 text-orange-700" aria-hidden="true" />
          <p className="text-sm font-medium text-red-700">{erro}</p>
          <button onClick={() => carregar()} className="btn-primary mt-4 inline-flex">Tentar novamente</button>
        </div>
      ) : lista.length === 0 ? (
        <div className="card py-16 text-center text-muted-foreground">Nenhuma pendência neste filtro</div>
      ) : prefs.visao === 'atividade' ? (
        <div className="space-y-5">
          {grupos.map(grupo => (
            <section key={grupo.titulo} aria-label={grupo.titulo} className="space-y-2">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {grupo.titulo} <span className="font-normal">({grupo.itens.length})</span>
              </h2>
              <div className="overflow-hidden rounded-xl border border-border bg-card">
                {grupo.itens.map(item => linha(item, true))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {porResidente.map(g => (
            <section key={g.id} aria-label={nomeDe(g.id)} className="overflow-hidden rounded-xl border border-border bg-card">
              <div className="flex items-center gap-2 border-b border-border bg-slate-50 px-3 py-2">
                <div className="min-w-0">
                  <p className="font-semibold text-foreground">{nomeDe(g.id)}</p>
                  {locais[g.id] && <p className="text-xs text-muted-foreground">{locais[g.id]}</p>}
                </div>
              </div>
              {g.itens.map(item => linha(item, false))}
            </section>
          ))}
        </div>
      )}

      {/* Confirmação visível e anunciada; atualiza só o item salvo. */}
      <div role="status" aria-live="polite" className="pointer-events-none fixed inset-x-0 top-20 z-[60] flex justify-center px-3">
        {aviso && <div className="max-w-md rounded-lg bg-foreground px-4 py-2.5 text-sm text-white shadow-lg">{aviso}</div>}
      </div>

      <PainelRegistro
          aberto={itemAberto !== null}
          aoFechar={fechar}
          titulo={itemAberto ? rotuloDoItem(itemAberto) : ''}
          cabecalho={painel?.cabecalho}
          rodape={painel?.rodape}
          chaveConteudo={itemAberto ? chave(itemAberto) : undefined}
          idRetorno={itemAberto ? `linha-${chave(itemAberto)}` : undefined}
        >
          <div data-painel-registro className="space-y-4">{painel?.corpo}</div>
        </PainelRegistro>

      <PainelRegistro
        aberto={filtrosAbertos}
        aoFechar={() => setFiltrosAbertos(false)}
        titulo="Filtros"
        cabecalho={<p className="text-muted-foreground">Aplicados na hora; ficam salvos ao voltar.</p>}
        rodape={
          <>
            <button type="button" onClick={() => setPrefs(PREFERENCIAS_PADRAO)} className="min-h-[44px] flex-1 rounded-lg border border-input bg-card px-4 font-semibold hover:bg-muted">Limpar</button>
            <button type="button" onClick={() => setFiltrosAbertos(false)} className="btn-primary flex-1">Ver {lista.length} {lista.length === 1 ? 'item' : 'itens'}</button>
          </>
        }
      >
        <div className="space-y-1">
          <label htmlFor="filtro-residente" className="text-sm font-semibold">Residente</label>
          <select id="filtro-residente" className="input" value={prefs.residente} onChange={e => setPrefs(p => ({ ...p, residente: e.target.value }))}>
            <option value="">Todos os residentes</option>
            {residentesNaLista.map(r => <option key={r.id} value={r.id}>{r.nome}</option>)}
          </select>
        </div>
      </PainelRegistro>
    </div>
  )
}

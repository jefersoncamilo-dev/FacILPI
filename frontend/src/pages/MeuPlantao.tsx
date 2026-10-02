import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ListChecks, TriangleAlert } from 'lucide-react'
import { formatDateTime, mensagemDeErro } from '../services/api'
import { Modal } from '../components/Modal'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { Alert } from '../components/ui/feedback'
import { MeuTurno } from '../components/plantao/MeuTurno'
import { MinhaArea } from '../components/plantao/MinhaArea'
import { RegistrarCuidado } from '../components/plantao/RegistrarCuidado'
import { RegistrarLote } from '../components/plantao/RegistrarLote'
import { ItemPlantao } from '../components/plantao/ItemPlantao'
import { FiltrosPlantao } from '../components/plantao/FiltrosPlantao'
import {
  FILTROS_PADRAO, SITUACOES, VISOES, agrupar, atendeSituacao, filtrar,
  type Filtros, type Situacao, type Visao,
} from '../components/plantao/visoes'
import { meuPlantaoApi, type MeuPlantaoResumo } from '../services/meuPlantao'
import { cn } from '../lib/utils'
import {
  PLANTAO_LIMIT_PADRAO,
  encerrarIntercorrencia,
  getPlantao,
  getResidentesResumo,
  registrarAdministracao,
  rotuloDoItem,
  type PlantaoItem,
  type PlantaoOrigem,
  type ResultadoDose,
} from '../services/plantao'

// UX-05 (#91): permissão que cada ação exige no backend. Sem ela, a pendência
// continua visível (informa o turno), mas o botão não é oferecido.
const PERMISSAO_ACAO: Record<PlantaoOrigem, string> = {
  cuidado: 'execucoes:criar',
  medicacao: 'administracoes:criar',
  intercorrencia: 'intercorrencias:atualizar',
}

const SUCESSO_ACAO: Record<PlantaoOrigem, string> = {
  cuidado: 'Registro salvo.',
  medicacao: 'Administração registrada.',
  intercorrencia: 'Intercorrência encerrada.',
}

const ACAO_ORIGEM: Record<PlantaoOrigem, string> = {
  cuidado: 'Registrar',
  medicacao: 'Registrar administração',
  intercorrencia: 'Encerrar',
}

const JANELA_ATRASO_MS = 24 * 60 * 60 * 1000

const chaveDoItem = (item: PlantaoItem) => `${item.origem}:${item.registro_id}`

// UX-01A.2: visão e filtros sobrevivem à navegação dentro da sessão do navegador.
const CHAVE_VISAO = 'facilpi:plantao:visao'
const CHAVE_FILTROS = 'facilpi:plantao:filtros'

function lerSessao<T>(chave: string, padrao: T, valido: (v: unknown) => boolean): T {
  try {
    const bruto = sessionStorage.getItem(chave)
    const valor: unknown = bruto ? JSON.parse(bruto) : null
    return valor !== null && valido(valor) ? valor as T : padrao
  } catch {
    return padrao
  }
}

function gravarSessao(chave: string, valor: unknown) {
  try { sessionStorage.setItem(chave, JSON.stringify(valor)) } catch { /* sem sessão: só não persiste */ }
}

// Estado do formulário de medicação/intercorrência. O cuidado tem o próprio
// Registrar rápido (UX-01A.1); só um diálogo fica aberto por vez.
interface FormAcao {
  resultadoDose: ResultadoDose
  quantidade: string
  justificativa: string
  observacao: string
  desfecho: string
}

const FORM_VAZIO: FormAcao = {
  resultadoDose: 'administrada',
  quantidade: '',
  justificativa: '',
  observacao: '',
  desfecho: '',
}

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

export function MeuPlantao() {
  const { pode } = usePermissoesOuPadrao()
  const [params] = useSearchParams()
  const desde = lerDesde(params.get('desde'))
  const [sucesso, setSucesso] = useState('')
  const [itens, setItens] = useState<PlantaoItem[]>([])
  const [carregando, setCarregando] = useState(true)
  // `erro` separado de lista vazia: sem essa distinção um 403 viraria
  // "nenhuma pendência" na tela do plantonista.
  const [erro, setErro] = useState('')
  const [nomes, setNomes] = useState<Record<string, string>>({})
  const [fotos, setFotos] = useState<Record<string, string | null | undefined>>({})
  const [visao, setVisaoEstado] = useState<Visao>(() =>
    lerSessao(CHAVE_VISAO, 'horario', v => VISOES.some(o => o.valor === v)))
  const [filtros, setFiltrosEstado] = useState<Filtros>(() =>
    lerSessao(CHAVE_FILTROS, FILTROS_PADRAO, v => SITUACOES.some(o => o.valor === (v as Filtros)?.situacao)))
  const setVisao = (v: Visao) => { setVisaoEstado(v); gravarSessao(CHAVE_VISAO, v) }
  const setFiltros = (f: Filtros) => { setFiltrosEstado(f); gravarSessao(CHAVE_FILTROS, f) }

  const [itemAberto, setItemAberto] = useState<PlantaoItem | null>(null)
  const [cuidadoAberto, setCuidadoAberto] = useState<PlantaoItem | null>(null)
  // UX-01B: seleção múltipla só de cuidados de rotina (origem "cuidado"), para
  // quem pode registrar execução. Medicação e intercorrência nunca entram.
  const [selecionando, setSelecionando] = useState(false)
  const [selecionados, setSelecionados] = useState<Set<string>>(() => new Set())
  // UX-01C: itens do lote em registro (cópia do momento em que o diálogo abriu).
  const [lote, setLote] = useState<PlantaoItem[] | null>(null)
  // Depois de salvar, o foco vai para o "Registrar" do próximo item da lista.
  const focarApos = useRef<string | null>(null)
  const [form, setForm] = useState<FormAcao>(FORM_VAZIO)
  const [erroAcao, setErroAcao] = useState('')
  const [salvando, setSalvando] = useState(false)

  // `silencioso`: recarga depois de um registro — sem trocar a lista pelo
  // "Carregando…", para não perder rolagem, filtro e posição na fila.
  const carregar = useCallback(async ({ silencioso = false }: { silencioso?: boolean } = {}) => {
    if (!silencioso) setCarregando(true)
    try {
      // UX-01A.2: sem `?desde=`, a fila começa 24 h atrás (a mesma janela do alerta
      // "sem registro", HORAS_JANELA_PLANTAO) — senão nada atrasado aparece.
      const inicio = desde ?? new Date(Date.now() - JANELA_ATRASO_MS).toISOString()
      const data = await getPlantao({ a_partir_de: inicio })
      setItens(data)
      setErro('')
    } catch (e) {
      // A lista é zerada junto com o erro para não exibir dados obsoletos
      // ao lado de uma mensagem de falha.
      setItens([])
      setErro(mensagemDeErro(e, 'Não foi possível carregar o plantão.'))
    } finally {
      setCarregando(false)
    }
  }, [desde])

  useEffect(() => { carregar() }, [carregar])

  // Item que saiu da fila (registrado por alguém, cancelado) sai da seleção.
  useEffect(() => {
    setSelecionados(atual => {
      const presentes = new Set(itens.map(chaveDoItem))
      const mantidos = [...atual].filter(k => presentes.has(k))
      return mantidos.length === atual.size ? atual : new Set(mantidos)
    })
  }, [itens])

  useEffect(() => {
    if (!focarApos.current) return
    document.querySelector<HTMLElement>(`[data-acao-plantao="${focarApos.current}"]`)?.focus()
    focarApos.current = null
  }, [itens])

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
  const aoMudarAlerta = useCallback(() => { carregarResumo(); void carregar() }, [carregarResumo, carregar])

  useEffect(() => {
    // Auxiliar: a falha aqui não vira erro de tela, só mantém o id como rótulo.
    getResidentesResumo()
      .then(lista => {
        setNomes(Object.fromEntries(lista.map(r => [r.id, r.nome])))
        setFotos(Object.fromEntries(lista.map(r => [r.id, r.foto])))
      })
      .catch(() => setNomes({}))
  }, [])

  const agora = Date.now()

  // Contagem de cada situação respeita os demais filtros (origem/residente).
  const semSituacao = filtrar(itens, { ...filtros, situacao: 'todos' }, agora)
  const contagens = Object.fromEntries(SITUACOES.map(s =>
    [s.valor, semSituacao.filter(i => atendeSituacao(i, s.valor, agora)).length])) as Record<Situacao, number>
  const lista = filtrar(itens, filtros, agora)
  const grupos = agrupar(lista, visao, nomes, agora)
  const residentesDaFila = useMemo(() => [...new Set(itens.map(i => i.residente_id))]
    .map(id => ({ id, nome: nomes[id] || id }))
    .sort((a, b) => a.nome.localeCompare(b.nome, 'pt-BR')), [itens, nomes])

  const elegivel = (item: PlantaoItem) => item.origem === 'cuidado' && pode(PERMISSAO_ACAO.cuidado)
  const haElegiveis = itens.some(elegivel)
  const selecionadosNaFila = itens.filter(i => selecionados.has(chaveDoItem(i)))

  function alternar(item: PlantaoItem) {
    setSelecionados(atual => {
      const novo = new Set(atual)
      const k = chaveDoItem(item)
      if (novo.has(k)) novo.delete(k)
      else novo.add(k)
      return novo
    })
  }

  function alternarGrupo(itensDoGrupo: PlantaoItem[], marcar: boolean) {
    setSelecionados(atual => {
      const novo = new Set(atual)
      for (const item of itensDoGrupo) {
        if (marcar) novo.add(chaveDoItem(item))
        else novo.delete(chaveDoItem(item))
      }
      return novo
    })
  }

  function sairDaSelecao() {
    setSelecionando(false)
    setSelecionados(new Set())
  }

  // Salvos saem da fila e da seleção já; se algo falhou, o diálogo continua
  // aberto só com o que falta e a seleção mantém esses itens.
  function loteSalvo(salvos: PlantaoItem[], restantes: number) {
    if (salvos.length) {
      const feitos = new Set(salvos.map(chaveDoItem))
      setItens(atuais => atuais.filter(i => !feitos.has(chaveDoItem(i))))
      setSucesso(salvos.length === 1 ? '1 registro salvo.' : `${salvos.length} registros salvos.`)
      void carregar({ silencioso: true })
      carregarResumo()
    }
    if (restantes === 0) {
      setLote(null)
      sairDaSelecao()
    }
  }

  function abrir(item: PlantaoItem) {
    setSucesso('')
    if (item.origem === 'cuidado') { setCuidadoAberto(item); return }
    setItemAberto(item)
    setForm(FORM_VAZIO)
    setErroAcao('')
  }

  function fechar() {
    setItemAberto(null)
    setErroAcao('')
  }

  // Espelha as validações condicionais dos schemas do backend para não gastar
  // uma ida ao servidor com um 422 previsível.
  function validar(item: PlantaoItem): string {
    if (item.origem === 'medicacao') {
      if (form.resultadoDose === 'administrada') {
        const quantidade = Number(form.quantidade)
        if (!form.quantidade.trim() || Number.isNaN(quantidade) || quantidade <= 0) {
          return 'Informe a quantidade realizada (maior que zero).'
        }
      } else if (!form.justificativa.trim()) {
        return 'Justificativa obrigatória para recusa ou omissão.'
      }
      return ''
    }
    if (!form.desfecho.trim()) return 'Informe o desfecho da intercorrência.'
    return ''
  }

  async function confirmar() {
    if (!itemAberto) return
    const invalido = validar(itemAberto)
    if (invalido) { setErroAcao(invalido); return }

    setSalvando(true)
    setErroAcao('')
    // O instante do registro é o de agora: o plantonista está anotando o que
    // acabou de acontecer. Data retroativa exige a tela do próprio módulo.
    const ocorrido_em = new Date().toISOString()
    try {
      if (itemAberto.origem === 'medicacao') {
        await registrarAdministracao({
          dose_prevista_id: itemAberto.registro_id,
          resultado: form.resultadoDose,
          ocorrido_em,
          ...(form.resultadoDose === 'administrada' ? { quantidade_realizada: Number(form.quantidade) } : {}),
          ...(form.justificativa.trim() ? { justificativa: form.justificativa.trim() } : {}),
          ...(form.observacao.trim() ? { observacao: form.observacao.trim() } : {}),
        })
      } else {
        await encerrarIntercorrencia(itemAberto.registro_id, form.desfecho.trim())
      }
      const origem = itemAberto.origem
      fechar()
      await carregar({ silencioso: true })
      // #126: a fonte mudou — o resumo da área (prioridades, atrasadas) também.
      carregarResumo()
      setSucesso(SUCESSO_ACAO[origem])
    } catch (e) {
      // Conflito de concorrência (outro plantonista já registrou) chega aqui.
      // A projeção é recarregada para que a lista atrás do modal reflita a
      // realidade, e a mensagem do backend fica visível.
      setErroAcao(mensagemDeErro(e, 'Não foi possível registrar.'))
      await carregar({ silencioso: true })
    } finally {
      setSalvando(false)
    }
  }

  function cuidadoSalvo(item: PlantaoItem) {
    const chave = `${item.origem}:${item.registro_id}`
    const botoes = [...document.querySelectorAll<HTMLElement>('[data-acao-plantao]')]
    const atual = botoes.findIndex(b => b.dataset.acaoPlantao === chave)
    focarApos.current = (botoes[atual + 1] ?? botoes[atual - 1])?.dataset.acaoPlantao ?? null
    setCuidadoAberto(null)
    // Some da fila na hora; a recarga silenciosa confirma com a projeção oficial.
    setItens(atuais => atuais.filter(i => !(i.origem === item.origem && i.registro_id === item.registro_id)))
    setSucesso(SUCESSO_ACAO.cuidado)
    void carregar({ silencioso: true })
    carregarResumo()
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      <div className="space-y-1">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Meu Plantão</h1>
          {/* Filtros secundários ficam no cabeçalho: a barra de situação cabe inteira em 360px. */}
          <FiltrosPlantao filtros={filtros} residentes={residentesDaFila} onMudar={setFiltros} />
        </div>
        <p className="text-sm text-muted-foreground max-sm:sr-only">
          {desde
            ? <>Pendências desde {formatDateTime(desde)} e das próximas 24 horas — cuidados, doses e intercorrências abertas · <Link to="/plantao" className="font-medium text-primary hover:underline">voltar à fila padrão</Link></>
            : 'Atrasos das últimas 24 h e pendências das próximas 24 h'}
        </p>
      </div>

      {/* #120: início/fim do próprio plantão e por quais áreas responde (só com plantao:registrar). */}
      <MeuTurno onMudou={carregarResumo} />
      {resumo && <MinhaArea resumo={resumo} podeAssumir={pode('alertas:assumir')} onMudou={aoMudarAlerta} />}

      <div className="space-y-3">
        <div className="grid grid-cols-3 gap-1 rounded-lg bg-muted p-1" role="group" aria-label="Organizar por">
          {VISOES.map(opcao => (
            <button
              key={opcao.valor}
              aria-label={opcao.rotulo}
              aria-pressed={visao === opcao.valor}
              onClick={() => setVisao(opcao.valor)}
              className={cn(
                'min-h-[44px] rounded-md px-2 text-sm font-medium transition-colors',
                visao === opcao.valor ? 'bg-card text-foreground shadow-sm' : 'text-slate-600 hover:text-foreground',
              )}
            >
              <span className="sm:hidden">{opcao.curto}</span>
              <span className="max-sm:hidden">{opcao.rotulo}</span>
            </button>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-2" role="group" aria-label="Situação">
            {SITUACOES.map(opcao => (
              <button
                key={opcao.valor}
                aria-pressed={filtros.situacao === opcao.valor}
                onClick={() => setFiltros({ ...filtros, situacao: opcao.valor })}
                className={cn(
                  'inline-flex min-h-[44px] items-center justify-center gap-1.5 whitespace-nowrap rounded-full border px-2 text-sm font-medium',
                  filtros.situacao === opcao.valor
                    ? 'border-primary bg-brand-soft text-primary'
                    : opcao.valor === 'atrasados' && contagens.atrasados > 0
                      ? 'border-orange-300 bg-card text-orange-900 hover:bg-orange-50'
                      : 'border-border bg-card text-foreground hover:bg-muted',
                )}
              >
                {opcao.rotulo} <span className="tabular-nums">{contagens[opcao.valor]}</span>
              </button>
            ))}
        </div>
      </div>

      {sucesso && <Alert variant="success">{sucesso}</Alert>}

      {haElegiveis && !carregando && !erro && (
        <div className="flex items-center justify-end gap-3 sm:justify-between">
          <p className="text-sm text-muted-foreground max-sm:sr-only">
            {selecionando ? 'Toque nos cuidados para marcar.' : 'Vários cuidados iguais? Marque e registre juntos.'}
          </p>
          <button
            type="button"
            onClick={() => (selecionando ? sairDaSelecao() : setSelecionando(true))}
            aria-pressed={selecionando}
            className={cn(
              'inline-flex min-h-[44px] shrink-0 items-center gap-2 rounded-lg border px-3 text-sm font-medium',
              selecionando ? 'border-primary bg-brand-soft text-primary' : 'border-border bg-card hover:bg-muted',
            )}
          >
            <ListChecks className="size-4" aria-hidden="true" />
            {selecionando ? 'Cancelar seleção' : 'Selecionar'}
          </button>
        </div>
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
      ) : (
        <div className="space-y-6">
          {/* UX-01A.2: mesma fila, três leituras. Por horário mantém a pergunta do
              turno (atrasadas, próximas, sem horário); por cuidado e por residente
              agrupam sem mudar a ordem oficial dentro do grupo. */}
          {grupos.map(grupo => {
            const elegiveisDoGrupo = grupo.itens.filter(elegivel)
            const todosMarcados = elegiveisDoGrupo.length > 0 && elegiveisDoGrupo.every(i => selecionados.has(chaveDoItem(i)))
            return (
              <section key={grupo.chave} aria-label={grupo.titulo} className="space-y-2">
                <div className="flex min-h-[44px] items-center justify-between gap-2">
                  <h2 className="flex items-baseline gap-2">
                    <span className={visao === 'horario'
                      ? 'text-xs font-semibold uppercase tracking-wide text-muted-foreground'
                      : 'font-semibold text-foreground'}>
                      {grupo.titulo}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {visao === 'horario'
                        ? `(${grupo.itens.length})`
                        : `${grupo.itens.length} ${grupo.itens.length === 1 ? 'pendente' : 'pendentes'}`}
                    </span>
                  </h2>
                  {selecionando && elegiveisDoGrupo.length > 1 && (
                    <button
                      type="button"
                      onClick={() => alternarGrupo(elegiveisDoGrupo, !todosMarcados)}
                      className="min-h-[44px] shrink-0 px-2 text-sm font-medium text-primary hover:underline"
                    >
                      {todosMarcados ? 'Desmarcar todos' : `Marcar todos (${elegiveisDoGrupo.length})`}
                    </button>
                  )}
                </div>
                {grupo.itens.map(item => {
                  const podeAgir = pode(PERMISSAO_ACAO[item.origem])
                  return (
                    <ItemPlantao
                      key={chaveDoItem(item)}
                      item={item}
                      nomeResidente={nomes[item.residente_id]}
                      fotoResidente={fotos[item.residente_id]}
                      agora={agora}
                      destaque={visao === 'cuidado' ? 'residente' : 'cuidado'}
                      acao={podeAgir && !selecionando ? { rotulo: ACAO_ORIGEM[item.origem], onClick: () => abrir(item) } : undefined}
                      selecao={selecionando && elegivel(item)
                        ? { selecionado: selecionados.has(chaveDoItem(item)), onAlternar: () => alternar(item) }
                        : undefined}
                    />
                  )
                })}
              </section>
            )
          })}
        </div>
      )}

      {selecionando && (
        // Fica acima da navegação inferior no mobile; no desktop, rente ao fim da tela.
        <div className="sticky bottom-24 z-20 flex items-center gap-3 rounded-card border border-primary/40 bg-card p-3 shadow-lg xl:bottom-4" role="region" aria-label="Seleção">
          <span className="min-w-0 flex-1 text-sm font-semibold" aria-live="polite">
            {selecionadosNaFila.length === 0
              ? 'Nenhum cuidado marcado'
              : `${selecionadosNaFila.length} ${selecionadosNaFila.length === 1 ? 'marcado' : 'marcados'}`}
          </span>
          {selecionadosNaFila.length > 0 && (
            <>
              <button type="button" onClick={() => setSelecionados(new Set())} className="min-h-[44px] px-2 text-sm font-medium text-muted-foreground hover:text-foreground max-[400px]:hidden">
                Limpar
              </button>
              <button type="button" onClick={() => { setSucesso(''); setLote(selecionadosNaFila) }} className="btn-primary min-h-[48px] shrink-0 whitespace-nowrap px-4 text-sm">
                Registrar em lote ({selecionadosNaFila.length})
              </button>
            </>
          )}
        </div>
      )}

      <RegistrarLote itens={lote} nomes={nomes} onFechar={() => setLote(null)} onSalvos={loteSalvo} />

      <Modal open={itemAberto !== null} onClose={fechar} title={itemAberto ? ACAO_ORIGEM[itemAberto.origem] : ''}>
        {itemAberto && (
          <div className="space-y-3">
            <div className="text-sm text-textMuted">{rotuloDoItem(itemAberto)}</div>

            {itemAberto.origem === 'medicacao' && (
              <>
                <label className="block text-sm font-medium" htmlFor="resultado-dose">Resultado</label>
                <select
                  id="resultado-dose"
                  className="input"
                  value={form.resultadoDose}
                  onChange={e => setForm({ ...form, resultadoDose: e.target.value as ResultadoDose })}
                >
                  <option value="administrada">Administrada</option>
                  <option value="recusada">Recusada</option>
                  <option value="omitida">Omitida</option>
                </select>
                {form.resultadoDose === 'administrada' ? (
                  <input
                    className="input"
                    type="number"
                    min="0"
                    step="any"
                    placeholder="Quantidade realizada (obrigatória)"
                    value={form.quantidade}
                    onChange={e => setForm({ ...form, quantidade: e.target.value })}
                  />
                ) : (
                  <input
                    className="input"
                    placeholder="Justificativa (obrigatória)"
                    value={form.justificativa}
                    onChange={e => setForm({ ...form, justificativa: e.target.value })}
                  />
                )}
                <input
                  className="input"
                  placeholder="Observação (opcional)"
                  value={form.observacao}
                  onChange={e => setForm({ ...form, observacao: e.target.value })}
                />
              </>
            )}

            {itemAberto.origem === 'intercorrencia' && (
              <input
                className="input"
                placeholder="Desfecho (obrigatório)"
                value={form.desfecho}
                onChange={e => setForm({ ...form, desfecho: e.target.value })}
              />
            )}

            {erroAcao && <div className="text-sm text-danger" role="alert">{erroAcao}</div>}

            <button onClick={confirmar} disabled={salvando} className="btn-primary w-full disabled:opacity-60">
              {salvando ? 'Registrando…' : 'Confirmar'}
            </button>
          </div>
        )}
      </Modal>

      <RegistrarCuidado
        item={cuidadoAberto}
        nomeResidente={cuidadoAberto ? nomes[cuidadoAberto.residente_id] : undefined}
        onFechar={() => setCuidadoAberto(null)}
        onSalvo={cuidadoSalvo}
        onFalha={() => void carregar({ silencioso: true })}
      />
    </div>
  )
}

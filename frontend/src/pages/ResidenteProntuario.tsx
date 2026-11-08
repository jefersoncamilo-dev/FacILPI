import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import { ChevronDown, ChevronRight, FileText, Info, Pill, X, type LucideIcon } from 'lucide-react'
import { api } from '../services/api'
import {
  fimDoDiaISO,
  getProntuario,
  inicioDoDiaISO,
  ProntuarioConsultaParams,
  ProntuarioEvento,
} from '../services/prontuario'
import { ResidenteCabecalho, ResidenteResumo } from '../components/prontuario/ResidenteCabecalho'
import { FILTROS_INICIAIS, FiltrosValue, ProntuarioFiltros } from '../components/prontuario/ProntuarioFiltros'
import { ProntuarioLinhaDoTempo } from '../components/prontuario/ProntuarioLinhaDoTempo'
import { ResumoResidente } from '../components/prontuario/ResumoResidente'
import { ProntuarioCarregando, ProntuarioErro, ProntuarioVazio } from '../components/prontuario/ProntuarioEstados'
import { RegistrarSinalVitalModal } from '../components/sinaisVitais/RegistrarSinalVitalModal'
import { RegistrarIntercorrenciaModal } from '../components/intercorrencias/RegistrarIntercorrenciaModal'
import { RegistrarSaidaModal } from '../components/residentes/RegistrarSaidaModal'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { useContextoResidente } from '../hooks/useContextoResidente'
import { PRONTUARIO_ORIGENS, type ProntuarioOrigem } from '../services/prontuario'
import { cn } from '../lib/utils'
import { AbasModulo, idAba, idPainel } from '../components/modulo/AbasModulo'
import { useAbaUrl } from '../hooks/useFiltrosUrl'
import { PainelHoje } from '../components/prontuario/PainelHoje'
import { LinhaDoTempoCategoria } from '../components/prontuario/LinhaDoTempoCategoria'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '../components/ui/dropdown-menu'

// UX-NAV-3: as 7 abas da ficha, na ordem da rotina. Cada uma aparece só com
// uma das chaves que a alimentam; a primeira permitida é a padrão. O backend
// continua decidindo cada consulta.
type AbaFicha = 'hoje' | 'resumo' | 'medicacao' | 'saude' | 'cuidados' | 'linha-do-tempo' | 'documentos'
const ABAS_FICHA: { id: AbaFicha; rotulo: string; chaves: string[] | null }[] = [
  { id: 'hoje', rotulo: 'Hoje', chaves: ['plantao:ler', 'sinais_vitais:ler'] },
  { id: 'resumo', rotulo: 'Resumo', chaves: null },
  { id: 'medicacao', rotulo: 'Medicação', chaves: ['prescricoes:ler', 'administracoes:ler'] },
  { id: 'saude', rotulo: 'Saúde', chaves: ['sinais_vitais:ler', 'intercorrencias:ler', 'avaliacoes:ler'] },
  { id: 'cuidados', rotulo: 'Cuidados e PAIS', chaves: ['planos_cuidados:ler', 'programacoes:ler', 'execucoes:ler', 'grau_dependencia:ler', 'avaliacoes:ler'] },
  { id: 'linha-do-tempo', rotulo: 'Linha do tempo', chaves: null },
  { id: 'documentos', rotulo: 'Documentos', chaves: ['documentos:ler'] },
]

export function abasPermitidas(pode: (chave?: string) => boolean) {
  return ABAS_FICHA.filter(a => !a.chaves || a.chaves.some(c => pode(c)))
}

// UX-04 (#89): atalhos da visão longitudinal por origem, sobre os mesmos filtros
// do endpoint (sem consulta nova). Só aparecem origens que a sessão pode ler.
const VISOES: { origem: ProntuarioOrigem; rotulo: string }[] = [
  { origem: 'sinal_vital', rotulo: 'Sinais vitais' },
  { origem: 'intercorrencia', rotulo: 'Intercorrências' },
  { origem: 'avaliacao', rotulo: 'Avaliações' },
  { origem: 'pais', rotulo: 'PAIS' },
  { origem: 'grau_dependencia', rotulo: 'Grau de dependência' },
]

function paramsDeFiltros(f: FiltrosValue, cursor?: string): ProntuarioConsultaParams {
  return {
    categoria: f.categoria,
    origem: f.origem,
    desde: f.desde ? inicioDoDiaISO(f.desde) : undefined,
    ate: f.ate ? fimDoDiaISO(f.ate) : undefined,
    incluir_movimentacoes: f.incluirMovimentacoes,
    limit: 20,
    cursor,
  }
}

// Mapeia só os status realmente distintos do endpoint (400/403/404/422) — ver
// backend/src/application/prontuario.py. Qualquer outro erro cai no genérico.
function mensagemErro(status?: number): string {
  if (status === 400) return 'A navegação expirou. Reaplique os filtros para continuar.'
  if (status === 403) return 'Você não tem permissão para ver estes registros.'
  if (status === 404) return 'Residente não encontrado.'
  if (status === 422) return 'Os filtros informados são inválidos.'
  return 'Não foi possível carregar o prontuário agora.'
}

export function ResidenteProntuario() {
  const { id } = useParams<{ id: string }>()
  const { pode, status: statusPermissoes } = usePermissoesOuPadrao()
  const contexto = useContextoResidente(id)
  // UX-NAV-3: aba na URL (`?aba=`). Inválida ou sem permissão cai na primeira
  // permitida, sem entrada no histórico, com aviso dispensável.
  const abas = abasPermitidas(pode)
  const { ativa: aba, trocar: trocarAba, invalida, pedida } = useAbaUrl(
    abas.map(a => a.id),
    'aba',
    statusPermissoes !== 'carregando',
  )
  const [aviso, setAviso] = useState('')
  useEffect(() => {
    if (!invalida || !pedida) return
    const conhecida = ABAS_FICHA.find(a => a.id === pedida)
    const destino = abas[0]?.rotulo ?? 'Resumo'
    setAviso(conhecida
      ? `${conhecida.rotulo} não está liberada para você. Mostrando a aba ${destino}.`
      : `Não encontramos essa parte da ficha. Mostrando a aba ${destino}.`)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invalida, pedida])
  function irPara(nova: AbaFicha) {
    setAviso('')
    trocarAba(nova)
  }
  // Recarrega os painéis depois de um registro feito aqui.
  const [versaoDados, setVersaoDados] = useState(0)

  const [residente, setResidente] = useState<ResidenteResumo | null>(null)
  const [residenteErro, setResidenteErro] = useState<string | null>(null)

  const [filtros, setFiltros] = useState<FiltrosValue>(FILTROS_INICIAIS)
  const [eventos, setEventos] = useState<ProntuarioEvento[]>([])
  const eventosRef = useRef<ProntuarioEvento[]>([])
  useEffect(() => {
    eventosRef.current = eventos
  }, [eventos])

  const [carregandoInicial, setCarregandoInicial] = useState(true)
  const [erroCarga, setErroCarga] = useState<string | null>(null)
  // Erro de filtro não substitui os eventos já carregados (decisão explícita
  // do BUILD: 403 ao trocar filtro preserva a lista anterior).
  const [erroFiltro, setErroFiltro] = useState<string | null>(null)

  // Só a requisição mais recente pode escrever no estado: os filtros do desktop disparam a cada
  // alteração e, sem isso, uma resposta antiga chega depois e contradiz o filtro exibido.
  const requisicaoRef = useRef(0)

  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [carregandoMais, setCarregandoMais] = useState(false)
  const [erroPaginacao, setErroPaginacao] = useState<string | null>(null)

  // Registro de sinais vitais: entrada preferencial do módulo, já no contexto do
  // residente. O reflexo na linha do tempo vem do backend (origem `sinal_vital`),
  // por isso o sucesso apenas recarrega a consulta — nada é inserido no cliente.
  const [registrandoSinais, setRegistrandoSinais] = useState(false)
  const [sucessoSinais, setSucessoSinais] = useState('')
  const [semPermissaoSinais, setSemPermissaoSinais] = useState(false)

  // Mesmo desenho para intercorrencia: o reflexo na linha do tempo vem do
  // backend (origem `intercorrencia`), entao o sucesso apenas recarrega.
  const [registrandoIntercorrencia, setRegistrandoIntercorrencia] = useState(false)
  const [sucessoIntercorrencia, setSucessoIntercorrencia] = useState('')
  const [semPermissaoIntercorrencia, setSemPermissaoIntercorrencia] = useState(false)
  const [registrandoSaida, setRegistrandoSaida] = useState(false)
  const [sucessoSaida, setSucessoSaida] = useState('')
  const [versaoResidente, setVersaoResidente] = useState(0)

  useEffect(() => {
    if (!id) return
    setResidente(null)
    setResidenteErro(null)
    api
      .get(`/residentes/${id}`)
      .then(({ data }) => setResidente(data))
      .catch((e: any) => setResidenteErro(mensagemErro(e.response?.status)))
  }, [id, versaoResidente])

  const carregar = useCallback(
    async (filtrosAtuais: FiltrosValue) => {
      if (!id) return
      const requisicao = ++requisicaoRef.current
      // A paginação pertence ao conjunto que está sendo substituído: mantê-la deixaria o botão
      // clicável durante a troca e anexaria uma página do filtro anterior à lista nova.
      setNextCursor(null)
      setHasMore(false)
      setErroFiltro(null)
      const jaTinhaEventos = eventosRef.current.length > 0
      if (!jaTinhaEventos) {
        setCarregandoInicial(true)
        setErroCarga(null)
      }
      try {
        const resposta = await getProntuario(id, paramsDeFiltros(filtrosAtuais))
        if (requisicao !== requisicaoRef.current) return
        setEventos(resposta.items)
        setHasMore(resposta.has_more)
        setNextCursor(resposta.next_cursor)
        setErroPaginacao(null)
      } catch (e: any) {
        if (requisicao !== requisicaoRef.current) return
        const msg = mensagemErro(e.response?.status)
        if (jaTinhaEventos) {
          setErroFiltro(msg)
        } else {
          setErroCarga(msg)
        }
      } finally {
        // Uma carga superada não apaga o "carregando" da carga que a sucedeu.
        if (requisicao === requisicaoRef.current) setCarregandoInicial(false)
      }
    },
    [id],
  )

  useEffect(() => {
    carregar(FILTROS_INICIAIS)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  function aplicarFiltros(novos: FiltrosValue) {
    setFiltros(novos)
    carregar(novos)
  }

  async function carregarMais() {
    if (!id || !nextCursor || carregandoMais) return
    // Uma troca de filtro durante o append invalida esta página: ela pertence ao filtro anterior.
    const requisicao = requisicaoRef.current
    setCarregandoMais(true)
    setErroPaginacao(null)
    try {
      const resposta = await getProntuario(id, paramsDeFiltros(filtros, nextCursor))
      if (requisicao !== requisicaoRef.current) return
      setEventos(prev => [...prev, ...resposta.items])
      setHasMore(resposta.has_more)
      setNextCursor(resposta.next_cursor)
    } catch (e: any) {
      if (requisicao !== requisicaoRef.current) return
      const status = e.response?.status
      setErroPaginacao(mensagemErro(status))
      // Cursor inválido: sem limpar, o botão repetiria a mesma requisição indefinidamente.
      // Falha transitória mantém o cursor para permitir nova tentativa.
      if (status === 400) {
        setNextCursor(null)
        setHasMore(false)
      }
    } finally {
      setCarregandoMais(false)
    }
  }

  // UX-NAV-3: uma ação "Registrar" (o residente já vem fixo) em vez de vários
  // botões. Cada opção só aparece para quem pode registrar; o 403 do backend
  // continua como defesa (semPermissao*). Saída (N2, rara e irreversível) segue
  // separada, por último. Fica no cabeçalho da ficha.
  const acoesFicha = (
    <div className="flex flex-col gap-2 sm:flex-row">
      {((pode('sinais_vitais:criar') && !semPermissaoSinais) || (pode('intercorrencias:criar') && !semPermissaoIntercorrencia)) && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button type="button" className="btn-primary inline-flex w-full items-center justify-center gap-2 sm:w-auto">
              + Registrar <ChevronDown className="size-4" aria-hidden="true" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {pode('sinais_vitais:criar') && !semPermissaoSinais && (
              <DropdownMenuItem onSelect={() => { setSucessoSinais(''); setSucessoIntercorrencia(''); setRegistrandoSinais(true) }}>
                Sinais vitais
              </DropdownMenuItem>
            )}
            {pode('intercorrencias:criar') && !semPermissaoIntercorrencia && (
              <DropdownMenuItem onSelect={() => { setSucessoSinais(''); setSucessoIntercorrencia(''); setRegistrandoIntercorrencia(true) }}>
                Intercorrência
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      {residente?.situacao === 'Ativo' && pode('residentes:registrar_saida') && (
        <button
          type="button"
          onClick={() => { setSucessoSaida(''); setRegistrandoSaida(true) }}
          className="btn-secondary w-full sm:w-auto"
        >
          Registrar saída
        </button>
      )}
    </div>
  )

  return (
    <div className="space-y-4">
      {/* min-h-[44px]: alvo de toque, mesma convenção de ContextPicker e FuncionarioCard. */}
      <Link to="/residentes" className="text-sm text-primary hover:underline inline-flex items-center min-h-[44px]">← Residentes</Link>

      {residenteErro ? (
        <ProntuarioErro mensagem={residenteErro} onRetry={() => window.location.reload()} />
      ) : (
        <div className="space-y-4">
          <ResidenteCabecalho residente={residente} contexto={contexto} acoes={acoesFicha} />

          <div className="space-y-4 min-w-0">

            {sucessoSaida && (
              <div role="status" className="card border-l-4 border-l-success py-3">
                <span className="text-sm font-medium text-success">{sucessoSaida}</span>
              </div>
            )}

            {semPermissaoSinais && (
              <p className="text-sm text-textMuted">
                Seu perfil não permite registrar sinais vitais. A consulta continua disponível.
              </p>
            )}

            {semPermissaoIntercorrencia && (
              <p className="text-sm text-textMuted">
                Seu perfil não permite registrar intercorrências. A consulta continua disponível.
              </p>
            )}

            {sucessoSinais && (
              <div role="status" className="card border-l-4 border-l-success py-3">
                <span className="text-sm font-medium text-success">{sucessoSinais}</span>
              </div>
            )}

            {sucessoIntercorrencia && (
              <div role="status" className="card border-l-4 border-l-success py-3">
                <span className="text-sm font-medium text-success">{sucessoIntercorrencia}</span>
              </div>
            )}

            {aviso && (
              <div role="status" className="flex items-center gap-3 rounded-card border border-info bg-info-soft py-1 pl-4 pr-1 text-sm text-foreground">
                <Info className="size-5 shrink-0 text-info" aria-hidden="true" />
                <span className="flex-1 py-2 font-medium">{aviso}</span>
                <button type="button" aria-label="Fechar aviso" onClick={() => setAviso('')}
                  className="flex size-11 shrink-0 items-center justify-center rounded-lg hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  <X className="size-5" aria-hidden="true" />
                </button>
              </div>
            )}

            <AbasModulo abas={abas} ativa={aba} onTrocar={irPara} rotulo="Ficha do residente" prefixo="ficha" />

            <div role="tabpanel" id={idPainel('ficha', aba)} aria-labelledby={idAba('ficha', aba)} className="space-y-4">
            {!id ? null : aba === 'hoje' ? (
              <PainelHoje residenteId={id} pode={pode} versao={versaoDados} />
            ) : aba === 'resumo' ? (
              <ResumoResidente residenteId={id} />
            ) : aba === 'medicacao' ? (
              <>
                <AtalhoFicha to={`/residentes/${id}/medicacao`} icone={Pill} titulo="Prescrições e doses" texto="Abrir a medicação deste residente." />
                <LinhaDoTempoCategoria residenteId={id} categoria="medicacao" titulo="Histórico de medicação" vazio="Nenhuma prescrição ou administração registrada." versao={versaoDados} />
              </>
            ) : aba === 'saude' ? (
              <>
                <LinhaDoTempoCategoria residenteId={id} categoria="clinico" titulo="Avaliações, sinais e intercorrências" vazio="Nenhum registro de saúde ainda." versao={versaoDados} />
              </>
            ) : aba === 'cuidados' ? (
              <>
                <div className="grid gap-2 sm:grid-cols-2">
                  {pode('planos_cuidados:ler') && <AtalhoFicha to={`/plano?residente=${id}`} icone={FileText} titulo="Plano de cuidados (PAIS)" texto="Objetivos, ações e revisões." />}
                  {pode('avaliacoes:ler') && <AtalhoFicha to={`/avaliacoes?residente=${id}`} icone={FileText} titulo="Avaliações" texto="Avaliações e grau de dependência." />}
                </div>
                <LinhaDoTempoCategoria residenteId={id} categoria="assistencia" titulo="Histórico de cuidados" vazio="Nenhum cuidado, plano ou grau registrado." versao={versaoDados} />
              </>
            ) : aba === 'documentos' ? (
              // D2: Documentos não é origem da linha do tempo; a entrada é navegação
              // com o residente no contexto, não uma segunda listagem aqui.
              <AtalhoFicha to={`/documentos?residente=${id}`} icone={FileText} titulo="Documentos do residente" texto="Ver, cadastrar e validar documentos." />
            ) : (
              <div className="space-y-4">
              <VisoesRapidas filtros={filtros} pode={pode} aoEscolher={aplicarFiltros} />

              <ProntuarioFiltros value={filtros} onChange={aplicarFiltros} />

              {erroFiltro && (
                <div role="alert" className="card bg-critico-soft border-critico/30 p-3 text-sm text-danger">
                  {erroFiltro}
                </div>
              )}

              {carregandoInicial ? (
                <ProntuarioCarregando />
              ) : erroCarga ? (
                <ProntuarioErro mensagem={erroCarga} onRetry={() => carregar(filtros)} />
              ) : eventos.length === 0 ? (
                <ProntuarioVazio />
              ) : (
                <>
                  <ProntuarioLinhaDoTempo eventos={eventos} />
                  {erroPaginacao && (
                    <p role="alert" className="text-sm text-danger text-center">{erroPaginacao}</p>
                  )}
                  {hasMore && (
                    <div className="text-center">
                      <button
                        type="button"
                        onClick={carregarMais}
                        disabled={carregandoMais}
                        className="btn-secondary disabled:opacity-60"
                      >
                        {carregandoMais ? 'Carregando…' : 'Carregar mais'}
                      </button>
                    </div>
                  )}
                </>
              )}
              </div>
            )}
            </div>
          </div>
        </div>
      )}

      {id && (
        <RegistrarSinalVitalModal
          open={registrandoSinais}
          onClose={() => setRegistrandoSinais(false)}
          onRegistrado={() => {
            setRegistrandoSinais(false)
            setSucessoSinais('Sinais vitais registrados.')
            setVersaoDados(v => v + 1)
            carregar(filtros)
          }}
          residenteFixo={{ id, nome: residente?.nome ?? '' }}
          onPermissaoNegada={() => setSemPermissaoSinais(true)}
        />
      )}

      {id && (
        <RegistrarIntercorrenciaModal
          open={registrandoIntercorrencia}
          onClose={() => setRegistrandoIntercorrencia(false)}
          onRegistrado={() => {
            setRegistrandoIntercorrencia(false)
            setSucessoIntercorrencia('Intercorrência registrada.')
            setVersaoDados(v => v + 1)
            carregar(filtros)
          }}
          residenteFixo={{ id, nome: residente?.nome ?? '' }}
          onPermissaoNegada={() => setSemPermissaoIntercorrencia(true)}
        />
      )}

      {id && residente && (
        <RegistrarSaidaModal
          open={registrandoSaida}
          onClose={() => setRegistrandoSaida(false)}
          onRegistrado={() => {
            setRegistrandoSaida(false)
            setSucessoSaida('Saída registrada. Encerre as pendências na tela de cada módulo.')
            setVersaoResidente(v => v + 1)
            carregar(filtros)
          }}
          residente={{ id, nome: residente.nome }}
          podeLiberarLeito={pode('quartos_leitos:atualizar')}
        />
      )}
    </div>
  )
}

function VisoesRapidas({
  filtros,
  pode,
  aoEscolher,
}: {
  filtros: FiltrosValue
  pode: (chave?: string) => boolean
  aoEscolher: (f: FiltrosValue) => void
}) {
  const permitidas = VISOES.filter(v => pode(PRONTUARIO_ORIGENS.find(o => o.value === v.origem)?.permissao))
  if (permitidas.length < 2) return null
  const semRecorte = !filtros.categoria && !filtros.desde && !filtros.ate
  const opcoes = [{ origem: undefined as ProntuarioOrigem | undefined, rotulo: 'Tudo' }, ...permitidas]
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Ver no prontuário">
      {opcoes.map(v => {
        const ativa = semRecorte && filtros.origem === v.origem
        return (
          <button
            key={v.rotulo}
            type="button"
            aria-pressed={ativa}
            onClick={() => aoEscolher({ ...FILTROS_INICIAIS, origem: v.origem })}
            className={cn(
              'min-h-[36px] rounded-full border px-3 text-sm font-medium transition-colors',
              ativa ? 'border-brand bg-accent text-accent-foreground' : 'border-border bg-card text-muted-foreground hover:text-foreground',
            )}
          >
            {v.rotulo}
          </button>
        )
      })}
    </div>
  )
}

/** Atalho da ficha para a tela do módulo, com o residente já no contexto. */
function AtalhoFicha({ to, icone: Icone, titulo, texto }: { to: string; icone: LucideIcon; titulo: string; texto: string }) {
  return (
    <Link to={to} className="card flex min-h-[64px] items-center gap-3 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-primary" aria-hidden="true">
        <Icone className="size-5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-semibold text-foreground">{titulo}</span>
        <span className="block text-sm text-muted-foreground">{texto}</span>
      </span>
      <ChevronRight className="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
    </Link>
  )
}

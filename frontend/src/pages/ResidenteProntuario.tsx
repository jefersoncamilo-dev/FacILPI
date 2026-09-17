import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
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
import { ProntuarioCarregando, ProntuarioErro, ProntuarioVazio } from '../components/prontuario/ProntuarioEstados'
import { RegistrarSinalVitalModal } from '../components/sinaisVitais/RegistrarSinalVitalModal'
import { RegistrarIntercorrenciaModal } from '../components/intercorrencias/RegistrarIntercorrenciaModal'

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

  useEffect(() => {
    if (!id) return
    setResidente(null)
    setResidenteErro(null)
    api
      .get(`/residentes/${id}`)
      .then(({ data }) => setResidente(data))
      .catch((e: any) => setResidenteErro(mensagemErro(e.response?.status)))
  }, [id])

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

  return (
    <div className="space-y-4">
      {/* min-h-[44px]: alvo de toque, mesma convenção de ContextPicker e FuncionarioCard. */}
      <Link to="/residentes" className="text-sm text-primary hover:underline inline-flex items-center min-h-[44px]">← Residentes</Link>

      {residenteErro ? (
        <ProntuarioErro mensagem={residenteErro} onRetry={() => window.location.reload()} />
      ) : (
        <div className="lg:grid lg:grid-cols-[280px_1fr] lg:gap-6 lg:items-start space-y-4 lg:space-y-0">
          <ResidenteCabecalho residente={residente} />

          <div className="space-y-4 min-w-0">
            {/* Duas acoes de registro convivem aqui. Empilham em 360 e ficam lado a
                lado a partir de sm; a hierarquia vem das classes ja existentes —
                sinais vitais e o ato rotineiro (primaria), intercorrencia e o
                excepcional (secundaria). Sem redesenho do Prontuario. */}
            <div className="flex flex-col sm:flex-row gap-2">
              {!semPermissaoSinais && (
                <button
                  type="button"
                  onClick={() => { setSucessoSinais(''); setSucessoIntercorrencia(''); setRegistrandoSinais(true) }}
                  className="btn-primary w-full sm:w-auto"
                >
                  + Registrar sinais vitais
                </button>
              )}
              {!semPermissaoIntercorrencia && (
                <button
                  type="button"
                  onClick={() => { setSucessoSinais(''); setSucessoIntercorrencia(''); setRegistrandoIntercorrencia(true) }}
                  className="btn-secondary w-full sm:w-auto"
                >
                  + Registrar intercorrência
                </button>
              )}
              {/* D2: Documentos nao e origem da linha do tempo, entao a entrada
                  aqui e navegacao com o residente ja no contexto — e nao uma
                  segunda listagem embutida no Prontuario. O parametro `residente`
                  e estado de UI; a consulta sai como `residente_id`. */}
              {id && (
                <Link
                  to={`/documentos?residente=${id}`}
                  className="btn-secondary w-full sm:w-auto text-center inline-flex items-center justify-center"
                >
                  Documentos
                </Link>
              )}
            </div>

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

            <ProntuarioFiltros value={filtros} onChange={aplicarFiltros} />

            {erroFiltro && (
              <div role="alert" className="card bg-red-50 border-red-200 p-3 text-sm text-danger">
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
        </div>
      )}

      {id && (
        <RegistrarSinalVitalModal
          open={registrandoSinais}
          onClose={() => setRegistrandoSinais(false)}
          onRegistrado={() => {
            setRegistrandoSinais(false)
            setSucessoSinais('Sinais vitais registrados.')
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
            carregar(filtros)
          }}
          residenteFixo={{ id, nome: residente?.nome ?? '' }}
          onPermissaoNegada={() => setSemPermissaoIntercorrencia(true)}
        />
      )}
    </div>
  )
}

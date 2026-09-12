import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../services/api'
import { getProntuario, ProntuarioConsultaParams, ProntuarioEvento } from '../services/prontuario'
import { ResidenteCabecalho, ResidenteResumo } from '../components/prontuario/ResidenteCabecalho'
import { FILTROS_INICIAIS, FiltrosValue, ProntuarioFiltros } from '../components/prontuario/ProntuarioFiltros'
import { ProntuarioLinhaDoTempo } from '../components/prontuario/ProntuarioLinhaDoTempo'
import { ProntuarioCarregando, ProntuarioErro, ProntuarioVazio } from '../components/prontuario/ProntuarioEstados'

function paramsDeFiltros(f: FiltrosValue, cursor?: string): ProntuarioConsultaParams {
  return {
    categoria: f.categoria,
    origem: f.origem,
    desde: f.desde ? `${f.desde}T00:00:00` : undefined,
    ate: f.ate ? `${f.ate}T23:59:59` : undefined,
    incluir_movimentacoes: f.incluirMovimentacoes,
    limit: 20,
    cursor,
  }
}

// Mapeia só os status realmente distintos do endpoint (403/404/422) — ver
// backend/src/application/prontuario.py. Qualquer outro erro cai no genérico.
function mensagemErro(status?: number): string {
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

  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [carregandoMais, setCarregandoMais] = useState(false)
  const [erroPaginacao, setErroPaginacao] = useState<string | null>(null)

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
      setErroFiltro(null)
      const jaTinhaEventos = eventosRef.current.length > 0
      if (!jaTinhaEventos) {
        setCarregandoInicial(true)
        setErroCarga(null)
      }
      try {
        const resposta = await getProntuario(id, paramsDeFiltros(filtrosAtuais))
        setEventos(resposta.items)
        setHasMore(resposta.has_more)
        setNextCursor(resposta.next_cursor)
      } catch (e: any) {
        const msg = mensagemErro(e.response?.status)
        if (jaTinhaEventos) {
          setErroFiltro(msg)
        } else {
          setErroCarga(msg)
        }
      } finally {
        setCarregandoInicial(false)
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
    setCarregandoMais(true)
    setErroPaginacao(null)
    try {
      const resposta = await getProntuario(id, paramsDeFiltros(filtros, nextCursor))
      setEventos(prev => [...prev, ...resposta.items])
      setHasMore(resposta.has_more)
      setNextCursor(resposta.next_cursor)
    } catch (e: any) {
      setErroPaginacao(mensagemErro(e.response?.status))
    } finally {
      setCarregandoMais(false)
    }
  }

  return (
    <div className="space-y-4">
      <Link to="/residentes" className="text-sm text-primary hover:underline inline-block">← Residentes</Link>

      {residenteErro ? (
        <ProntuarioErro mensagem={residenteErro} onRetry={() => window.location.reload()} />
      ) : (
        <div className="lg:grid lg:grid-cols-[280px_1fr] lg:gap-6 lg:items-start space-y-4 lg:space-y-0">
          <ResidenteCabecalho residente={residente} />

          <div className="space-y-4 min-w-0">
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
    </div>
  )
}

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { TriangleAlert } from 'lucide-react'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { formatDateTime, mensagemDeErro } from '../services/api'
// `GET /residentes/` já tem um consumidor tipado; duplicar a função criaria uma
// segunda declaração da mesma chamada.
import { getResidentesResumo, type ResidenteResumo } from '../services/plantao'
import {
  INTERCORRENCIAS_LIMIT_PADRAO,
  getIntercorrencias,
  type Gravidade,
  type Intercorrencia,
} from '../services/intercorrencias'
import { RegistrarIntercorrenciaModal } from '../components/intercorrencias/RegistrarIntercorrenciaModal'

const TODOS = ''

const BADGE_GRAVIDADE: Record<Gravidade, string> = {
  leve: 'badge-success',
  moderada: 'badge-warning',
  grave: 'badge-danger',
}

const ROTULO_GRAVIDADE: Record<Gravidade, string> = {
  leve: 'Leve',
  moderada: 'Moderada',
  grave: 'Grave',
}

export function Intercorrencias() {
  const { pode } = usePermissoesOuPadrao()
  const [registros, setRegistros] = useState<Intercorrencia[]>([])
  const [carregando, setCarregando] = useState(true)
  // `erro` separado de lista vazia: sem essa distinção um 403 viraria
  // "nenhuma intercorrência" para quem não tem permissão de leitura.
  const [erro, setErro] = useState('')

  const [params, setParams] = useSearchParams()
  const [residentes, setResidentes] = useState<ResidenteResumo[]>([])
  const [erroResidentes, setErroResidentes] = useState(false)
  const [residenteId, setResidenteId] = useState<string>(TODOS)

  const [modalAberto, setModalAberto] = useState(() => params.get('registrar') === '1')
  // UX-11 (#101): `?registrar=1` (ações rápidas do Início) abre o registro
  // direto; ao fechar, o parâmetro sai para não reabrir ao recarregar.
  useEffect(() => {
    if (!modalAberto && params.has('registrar')) {
      const p = new URLSearchParams(params)
      p.delete('registrar')
      setParams(p, { replace: true })
    }
  }, [modalAberto, params, setParams])
  const [sucesso, setSucesso] = useState('')
  // O token não carrega permissões e nenhum endpoint expõe as chaves efetivas,
  // então a tela só descobre a incapacidade pela resposta do backend. Depois do
  // primeiro 403 a ação deixa de ser oferecida.
  const [semPermissaoCriar, setSemPermissaoCriar] = useState(false)

  const carregar = useCallback(async (alvo: string) => {
    setCarregando(true)
    try {
      const data = await getIntercorrencias(alvo ? { residente_id: alvo } : {})
      setRegistros(data)
      setErro('')
    } catch (e) {
      // A lista é zerada junto com o erro para não exibir dado obsoleto ao lado
      // de uma mensagem de falha.
      setRegistros([])
      setErro(mensagemDeErro(e, 'Não foi possível carregar as intercorrências.'))
    } finally {
      setCarregando(false)
    }
  }, [])

  useEffect(() => { carregar(residenteId) }, [carregar, residenteId])

  useEffect(() => {
    getResidentesResumo()
      .then(lista => { setResidentes(lista); setErroResidentes(false) })
      .catch(() => { setResidentes([]); setErroResidentes(true) })
  }, [])

  const nomes = useMemo(
    () => Object.fromEntries(residentes.map(r => [r.id, r.nome])),
    [residentes],
  )

  function aoRegistrar() {
    setModalAberto(false)
    setSucesso('Intercorrência registrada.')
    carregar(residenteId)
  }

  const residenteSelecionado = residentes.find(r => r.id === residenteId) ?? null
  const abertas = registros.filter(r => r.situacao === 'aberta').length

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Intercorrências</h1>
          <p className="text-textMuted text-sm">Eventos relevantes com gravidade, SBAR e providências</p>
        </div>
        {/* UX-05: só para quem pode registrar; o 403 segue como defesa. */}
        {pode('intercorrencias:criar') && !semPermissaoCriar && (
          <button onClick={() => { setSucesso(''); setModalAberto(true) }} className="btn-alerta">
            + Registrar intercorrência
          </button>
        )}
      </div>

      {semPermissaoCriar && (
        <div className="card border-l-4 border-l-warning py-3">
          <span className="text-sm text-textMuted">
            Seu perfil não permite registrar intercorrências. A consulta continua disponível.
          </span>
        </div>
      )}

      <div className="card p-3 flex flex-col sm:flex-row sm:items-center gap-3">
        <label className="text-sm font-medium whitespace-nowrap" htmlFor="int-filtro-residente">Residente</label>
        <select
          id="int-filtro-residente"
          className="input sm:flex-1"
          value={residenteId}
          onChange={e => { setSucesso(''); setResidenteId(e.target.value) }}
        >
          <option value={TODOS}>Todos os residentes</option>
          {residentes.map(r => (
            <option key={r.id} value={r.id}>{r.nome}</option>
          ))}
        </select>
        {residenteId !== TODOS && (
          <Link to={`/residentes/${residenteId}`} className="btn-secondary text-sm whitespace-nowrap text-center">
            Abrir prontuário
          </Link>
        )}
      </div>

      {erroResidentes && (
        <div className="card border-l-4 border-l-warning py-3">
          <span className="text-sm text-textMuted">
            Não foi possível carregar a lista de residentes. Os registros aparecem pelo identificador.
          </span>
        </div>
      )}

      {sucesso && (
        <div role="status" className="card border-l-4 border-l-success py-3">
          <span className="text-sm font-medium text-success">{sucesso}</span>
        </div>
      )}

      {abertas > 0 && !erro && !carregando && (
        <div className="card border-l-4 border-l-warning py-3">
          <span className="text-sm font-medium text-warning">
            <TriangleAlert className="mr-1 inline size-4 align-text-bottom" aria-hidden="true" />{abertas} {abertas === 1 ? 'intercorrência aberta' : 'intercorrências abertas'} — o encerramento é feito no Meu Plantão
          </span>
        </div>
      )}

      {registros.length >= INTERCORRENCIAS_LIMIT_PADRAO && !erro && (
        <div className="card border-l-4 border-l-warning py-3">
          <span className="text-sm text-textMuted">
            Exibindo as {INTERCORRENCIAS_LIMIT_PADRAO} mais recentes. Pode haver mais no histórico.
          </span>
        </div>
      )}

      {carregando ? (
        <div role="status" aria-live="polite" className="card py-16 text-center text-textMuted">
          Carregando intercorrências…
        </div>
      ) : erro ? (
        <div className="card py-10 text-center" role="alert">
          <TriangleAlert className="mx-auto mb-3 size-7 text-orange-700" aria-hidden="true" />
          <p className="text-sm text-danger font-medium">{erro}</p>
          <button onClick={() => carregar(residenteId)} className="btn-primary mt-4 inline-flex">Tentar novamente</button>
        </div>
      ) : registros.length === 0 ? (
        <div className="card py-16 text-center text-textMuted">
          <p className="font-medium">Nenhuma intercorrência registrada</p>
          <p className="text-sm mt-1">
            {residenteId === TODOS
              ? 'Registre a primeira para começar o histórico.'
              : 'Este residente ainda não tem intercorrência registrada.'}
          </p>
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {registros.map(registro => (
            <article
              key={registro.id}
              className={`card min-w-0 border-l-4 ${registro.situacao === 'aberta' ? 'border-l-warning' : 'border-l-success'}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-semibold truncate">{nomes[registro.residente_id] || registro.residente_id}</div>
                  <div className="text-xs text-textMuted">{formatDateTime(registro.ocorrido_em)}</div>
                </div>
                <span className={BADGE_GRAVIDADE[registro.gravidade] ?? 'badge-success'}>
                  {ROTULO_GRAVIDADE[registro.gravidade] ?? registro.gravidade}
                </span>
              </div>

              <p className="mt-3 font-medium break-words">{registro.tipo}</p>

              {registro.sbar_situacao && (
                <p className="mt-2 text-sm text-textMuted break-words">{registro.sbar_situacao}</p>
              )}
              {registro.providencia && (
                <p className="mt-2 text-sm text-textMuted break-words">
                  <span className="font-medium text-textMain">Providência:</span> {registro.providencia}
                </p>
              )}
              {registro.desfecho && (
                <p className="mt-2 text-sm text-textMuted break-words">
                  <span className="font-medium text-textMain">Desfecho:</span> {registro.desfecho}
                </p>
              )}

              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-textMuted">
                <span className={registro.situacao === 'aberta' ? 'badge-warning' : 'badge-success'}>
                  {registro.situacao === 'aberta' ? 'Aberta' : 'Encerrada'}
                </span>
                <span>Registrado por {registro.responsavel || '—'}</span>
              </div>
            </article>
          ))}
        </div>
      )}

      <RegistrarIntercorrenciaModal
        open={modalAberto}
        onClose={() => setModalAberto(false)}
        onRegistrado={aoRegistrar}
        residenteFixo={residenteSelecionado}
        residentes={residentes}
        onPermissaoNegada={() => setSemPermissaoCriar(true)}
      />
    </div>
  )
}

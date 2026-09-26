import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { TriangleAlert } from 'lucide-react'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { formatDateTime, mensagemDeErro } from '../services/api'
// `GET /residentes/` já tem um consumidor tipado; duplicar a função criaria uma
// segunda declaração da mesma chamada.
import { getResidentesResumo, type ResidenteResumo } from '../services/plantao'
import {
  SINAIS_VITAIS_LIMIT_PADRAO,
  getSinaisVitais,
  sinaisMedidos,
  type SinalVital,
} from '../services/sinaisVitais'
import { RegistrarSinalVitalModal } from '../components/sinaisVitais/RegistrarSinalVitalModal'

const TODOS = ''

export function SinaisVitais() {
  const { pode } = usePermissoesOuPadrao()
  const [registros, setRegistros] = useState<SinalVital[]>([])
  const [carregando, setCarregando] = useState(true)
  // `erro` separado de lista vazia: sem essa distinção um 403 viraria
  // "nenhum registro" na tela de quem não tem permissão de leitura.
  const [erro, setErro] = useState('')

  const [residentes, setResidentes] = useState<ResidenteResumo[]>([])
  const [erroResidentes, setErroResidentes] = useState(false)
  const [residenteId, setResidenteId] = useState<string>(TODOS)

  const [modalAberto, setModalAberto] = useState(false)
  const [sucesso, setSucesso] = useState('')
  // O token não carrega permissões, então a tela só descobre a incapacidade
  // pela resposta do backend. Depois do primeiro 403 a ação deixa de ser
  // oferecida, em vez de repetir uma recusa previsível.
  const [semPermissaoCriar, setSemPermissaoCriar] = useState(false)

  const carregar = useCallback(async (alvo: string) => {
    setCarregando(true)
    try {
      const data = await getSinaisVitais(alvo ? { residente_id: alvo } : {})
      setRegistros(data)
      setErro('')
    } catch (e) {
      // A lista é zerada junto com o erro para não exibir dado obsoleto ao lado
      // de uma mensagem de falha.
      setRegistros([])
      setErro(mensagemDeErro(e, 'Não foi possível carregar os sinais vitais.'))
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
    setSucesso('Sinais vitais registrados.')
    carregar(residenteId)
  }

  const residenteSelecionado = residentes.find(r => r.id === residenteId) ?? null

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Sinais Vitais</h1>
          <p className="text-textMuted text-sm">Temperatura, pressão, frequências, saturação, glicemia e peso</p>
        </div>
        {/* UX-05: só para quem pode registrar; o 403 segue como defesa. */}
        {pode('sinais_vitais:criar') && !semPermissaoCriar && (
          <button onClick={() => { setSucesso(''); setModalAberto(true) }} className="btn-primary">
            + Registrar aferição
          </button>
        )}
      </div>

      {semPermissaoCriar && (
        <div className="card border-l-4 border-l-warning py-3">
          <span className="text-sm text-textMuted">
            Seu perfil não permite registrar sinais vitais. A consulta continua disponível.
          </span>
        </div>
      )}

      <div className="card p-3 flex flex-col sm:flex-row sm:items-center gap-3">
        <label className="text-sm font-medium whitespace-nowrap" htmlFor="sv-filtro-residente">Residente</label>
        <select
          id="sv-filtro-residente"
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

      {registros.length >= SINAIS_VITAIS_LIMIT_PADRAO && !erro && (
        <div className="card border-l-4 border-l-warning py-3">
          <span className="text-sm text-textMuted">
            Exibindo os {SINAIS_VITAIS_LIMIT_PADRAO} registros mais recentes. Pode haver mais no histórico.
          </span>
        </div>
      )}

      {carregando ? (
        <div role="status" aria-live="polite" className="card py-16 text-center text-textMuted">
          Carregando sinais vitais…
        </div>
      ) : erro ? (
        <div className="card py-10 text-center" role="alert">
          <TriangleAlert className="mx-auto mb-3 size-7 text-amber-700" aria-hidden="true" />
          <p className="text-sm text-danger font-medium">{erro}</p>
          <button onClick={() => carregar(residenteId)} className="btn-primary mt-4 inline-flex">Tentar novamente</button>
        </div>
      ) : registros.length === 0 ? (
        <div className="card py-16 text-center text-textMuted">
          <p className="font-medium">Nenhum sinal vital registrado</p>
          <p className="text-sm mt-1">
            {residenteId === TODOS
              ? 'Registre a primeira aferição para começar o histórico.'
              : 'Este residente ainda não tem aferição registrada.'}
          </p>
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {registros.map(registro => (
            <article key={registro.id} className="card min-w-0">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-semibold truncate">{nomes[registro.residente_id] || registro.residente_id}</div>
                  <div className="text-xs text-textMuted">{formatDateTime(registro.data)}</div>
                </div>
              </div>
              <ul className="mt-3 flex flex-wrap gap-2">
                {sinaisMedidos(registro).map(medido => (
                  <li key={medido.label} className="px-2.5 py-1 bg-slate-100 rounded-full text-xs">
                    <span className="text-textMuted">{medido.label}:</span> <span className="font-semibold">{medido.texto}</span>
                  </li>
                ))}
              </ul>
              {registro.observacao && (
                <p className="mt-3 text-sm text-textMuted break-words">{registro.observacao}</p>
              )}
              <p className="mt-3 text-xs text-textMuted">Registrado por {registro.profissional || '—'}</p>
            </article>
          ))}
        </div>
      )}

      <RegistrarSinalVitalModal
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

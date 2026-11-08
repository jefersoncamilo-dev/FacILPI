import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
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
import { PaginaModulo, type LinkVerTambem } from '../components/modulo/PaginaModulo'
import { AbasModulo, idAba, idPainel } from '../components/modulo/AbasModulo'
import { BarraFiltros } from '../components/modulo/BarraFiltros'
import { LinkResidente } from '../components/modulo/LinkResidente'
import { useAbaUrl, useFiltrosUrl } from '../hooks/useFiltrosUrl'
import { useGrausAtivos } from '../hooks/useGrausAtivos'

const TODOS = ''

// UX-NAV-0 (piloto): "Todos" é a aba padrão para não esconder registros
// antigos; "Hoje" recorta no próprio navegador, sem consulta nova.
const ABAS = [
  { id: 'todos', rotulo: 'Todos' },
  { id: 'hoje', rotulo: 'Hoje' },
] as const
const IDS_ABAS = ABAS.map(a => a.id)
const FILTROS = ['residente'] as const

function ehHoje(iso: string, agora = new Date()): boolean {
  const d = new Date(iso)
  return d.getFullYear() === agora.getFullYear() && d.getMonth() === agora.getMonth() && d.getDate() === agora.getDate()
}

export function SinaisVitais() {
  const { pode } = usePermissoesOuPadrao()
  const [registros, setRegistros] = useState<SinalVital[]>([])
  const [carregando, setCarregando] = useState(true)
  // `erro` separado de lista vazia: sem essa distinção um 403 viraria
  // "nenhum registro" na tela de quem não tem permissão de leitura.
  const [erro, setErro] = useState('')

  const [params, setParams] = useSearchParams()
  const [residentes, setResidentes] = useState<ResidenteResumo[]>([])
  const [erroResidentes, setErroResidentes] = useState(false)
  const [residentesCarregados, setResidentesCarregados] = useState(false)
  // UX-NAV-0: residente filtrado e aba ficam na URL (recarregar mantém).
  const filtros = useFiltrosUrl(FILTROS)
  const residenteId = filtros.valores.residente || TODOS
  const { ativa: aba, trocar: trocarAba } = useAbaUrl(IDS_ABAS)
  // UX-GRAU: círculo e selo do grau oficial no nome (a lista segue cronológica).
  const { grauDe } = useGrausAtivos()

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
      .finally(() => setResidentesCarregados(true))
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
  const visiveis = aba === 'hoje' ? registros.filter(r => !!r.data && ehHoje(r.data)) : registros

  const verTambem: LinkVerTambem[] = [
    ...(residenteId !== TODOS ? [{ to: `/residentes/${residenteId}`, rotulo: 'Abrir prontuário' }] : []),
    ...(pode('intercorrencias:ler') ? [{ to: '/intercorrencias', rotulo: 'Intercorrências' }] : []),
  ]

  return (
    <PaginaModulo
      titulo="Sinais Vitais"
      subtitulo="Temperatura, pressão, frequências, saturação, glicemia e peso"
      voltarPara="/modulos/cuidado"
      verTambem={verTambem}
      acao={
        // UX-05: só para quem pode registrar; o 403 segue como defesa.
        pode('sinais_vitais:criar') && !semPermissaoCriar ? (
          <button onClick={() => { setSucesso(''); setModalAberto(true) }} className="btn-primary">
            + Registrar aferição
          </button>
        ) : undefined
      }
    >

      {semPermissaoCriar && (
        <div className="card border-l-4 border-l-warning py-3">
          <span className="text-sm text-textMuted">
            Seu perfil não permite registrar sinais vitais. A consulta continua disponível.
          </span>
        </div>
      )}

      <AbasModulo abas={ABAS} ativa={aba} onTrocar={trocarAba} rotulo="Sinais vitais" prefixo="sv" />

      <BarraFiltros
        onLimpar={() => { setSucesso(''); filtros.limpar() }}
        chips={residenteId !== TODOS ? [{
          chave: 'residente',
          // Sem a lista ainda, nunca mostra o identificador cru; com falha, segue a regra da tela.
          rotulo: `Residente: ${nomes[residenteId] || (!residentesCarregados ? 'carregando…' : erroResidentes ? residenteId : 'não encontrado')}`,
          onRemover: () => { setSucesso(''); filtros.definir('residente', '') },
        }] : []}
      >
        <label className="text-sm font-medium whitespace-nowrap" htmlFor="sv-filtro-residente">Residente</label>
        <select
          id="sv-filtro-residente"
          className="input sm:flex-1"
          value={residenteId}
          onChange={e => { setSucesso(''); filtros.definir('residente', e.target.value) }}
        >
          <option value={TODOS}>Todos os residentes</option>
          {residentes.map(r => (
            <option key={r.id} value={r.id}>{r.nome}</option>
          ))}
        </select>
      </BarraFiltros>

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

      <div role="tabpanel" id={idPainel('sv', aba)} aria-labelledby={idAba('sv', aba)} className="space-y-4">
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
          <TriangleAlert className="mx-auto mb-3 size-7 text-alerta-forte" aria-hidden="true" />
          <p className="text-sm text-danger font-medium">{erro}</p>
          <button onClick={() => carregar(residenteId)} className="btn-primary mt-4 inline-flex">Tentar novamente</button>
        </div>
      ) : visiveis.length === 0 ? (
        <div className="card py-16 text-center text-textMuted">
          <p className="font-medium">{aba === 'hoje' && registros.length > 0 ? 'Nenhuma aferição hoje' : 'Nenhum sinal vital registrado'}</p>
          <p className="text-sm mt-1">
            {aba === 'hoje' && registros.length > 0
              ? 'Os registros anteriores estão na aba Todos.'
              : residenteId === TODOS
              ? 'Registre a primeira aferição para começar o histórico.'
              : 'Este residente ainda não tem aferição registrada.'}
          </p>
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {visiveis.map(registro => (
            <article key={registro.id} className="card min-w-0">
              <LinkResidente
                id={registro.residente_id}
                nome={nomes[registro.residente_id]}
                detalhe={formatDateTime(registro.data)}
                grau={grauDe(registro.residente_id)}
              />
              <ul className="mt-3 flex flex-wrap gap-2">
                {sinaisMedidos(registro).map(medido => (
                  <li key={medido.label} className="px-2.5 py-1 bg-muted rounded-full text-xs">
                    <span className="text-textMuted">{medido.label}:</span> <span className="font-semibold">{medido.texto}</span>
                  </li>
                ))}
              </ul>
              {registro.observacao && (
                <p className="mt-3 text-sm text-textMuted wrap-break-word">{registro.observacao}</p>
              )}
              <p className="mt-3 text-xs text-textMuted">Registrado por {registro.profissional || '—'}</p>
            </article>
          ))}
        </div>
      )}
      </div>

      <RegistrarSinalVitalModal
        open={modalAberto}
        onClose={() => setModalAberto(false)}
        onRegistrado={aoRegistrar}
        residenteFixo={residenteSelecionado}
        residentes={residentes}
        onPermissaoNegada={() => setSemPermissaoCriar(true)}
      />
    </PaginaModulo>
  )
}

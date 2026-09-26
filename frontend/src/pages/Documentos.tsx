import { useCallback, useEffect, useMemo, useState } from 'react'
import { Paperclip, TriangleAlert } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { formatDate, mensagemDeErro } from '../services/api'
// `GET /residentes/` já tem um consumidor tipado; duplicar a função criaria uma
// segunda declaração da mesma chamada.
import { getResidentesResumo, type ResidenteResumo } from '../services/plantao'
import {
  DOCUMENTOS_LIMIT_PADRAO,
  baixarArquivo,
  formatarTamanho,
  getDocumentos,
  mensagemDeErroDeBlob,
  salvarArquivo,
  type Documento,
} from '../services/documentos'
import { CadastrarDocumentoModal } from '../components/documentos/CadastrarDocumentoModal'
import { AnexarArquivoModal } from '../components/documentos/AnexarArquivoModal'

const TODOS = ''

// Parâmetro de URL do frontend. Existe só para carregar o contexto vindo do
// Prontuário; a consulta continua saindo como `?residente_id=` — o contrato
// oficial do backend.
const PARAM_RESIDENTE = 'residente'

export function Documentos() {
  const [searchParams, setSearchParams] = useSearchParams()

  const [documentos, setDocumentos] = useState<Documento[]>([])
  const [carregando, setCarregando] = useState(true)
  // `erro` separado de lista vazia: sem essa distinção um 403 viraria
  // "nenhum documento" na tela de quem não tem permissão de leitura.
  const [erro, setErro] = useState('')

  const [residentes, setResidentes] = useState<ResidenteResumo[]>([])
  const [erroResidentes, setErroResidentes] = useState(false)
  const residenteId = searchParams.get(PARAM_RESIDENTE) ?? TODOS

  const [cadastrando, setCadastrando] = useState(false)
  const [documentoParaAnexo, setDocumentoParaAnexo] = useState<Documento | null>(null)
  const [sucesso, setSucesso] = useState('')
  const [baixando, setBaixando] = useState('')
  // O token não carrega permissões e nenhum endpoint expõe as chaves efetivas,
  // então a tela só descobre a incapacidade pela resposta do backend. Depois do
  // primeiro 403 a ação deixa de ser oferecida.
  const [semPermissaoCriar, setSemPermissaoCriar] = useState(false)
  const [semPermissaoAnexar, setSemPermissaoAnexar] = useState(false)

  const carregar = useCallback(async (alvo: string) => {
    setCarregando(true)
    try {
      // O nome do parâmetro muda aqui: `?residente=` é estado de UI, o backend
      // recebe `residente_id`.
      const data = await getDocumentos(alvo ? { residente_id: alvo } : {})
      setDocumentos(data)
      setErro('')
    } catch (e) {
      // A lista é zerada junto com o erro para não exibir dado obsoleto ao lado
      // de uma mensagem de falha.
      setDocumentos([])
      setErro(mensagemDeErro(e, 'Não foi possível carregar os documentos.'))
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

  function trocarResidente(alvo: string) {
    setSucesso('')
    setErro('')
    // `replace` evita empilhar uma entrada de histórico a cada troca de filtro.
    setSearchParams(alvo ? { [PARAM_RESIDENTE]: alvo } : {}, { replace: true })
  }

  function aoCadastrar() {
    setCadastrando(false)
    setSucesso('Documento cadastrado.')
    carregar(residenteId)
  }

  function aoAnexar() {
    setDocumentoParaAnexo(null)
    setSucesso('Arquivo anexado.')
    carregar(residenteId)
  }

  async function baixar(documento: Documento) {
    setBaixando(documento.id)
    setErro('')
    try {
      const { blob, nomeArquivo } = await baixarArquivo(documento)
      salvarArquivo(blob, nomeArquivo)
    } catch (e) {
      // Em `responseType: 'blob'` o corpo de erro também é um Blob: o
      // normalizador comum não acharia `detail` e cairia no texto padrão.
      setErro(await mensagemDeErroDeBlob(e, 'Não foi possível baixar o arquivo.'))
    } finally {
      setBaixando('')
    }
  }

  const residenteSelecionado = residentes.find(r => r.id === residenteId) ?? null

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Documentos</h1>
          <p className="text-sm text-muted-foreground">Documentação do residente, com arquivo anexado e validade</p>
        </div>
        {!semPermissaoCriar && (
          <button onClick={() => { setSucesso(''); setCadastrando(true) }} className="btn-primary">
            + Cadastrar documento
          </button>
        )}
      </div>

      {semPermissaoCriar && (
        <div className="card border-l-4 border-l-warning py-3">
          <span className="text-sm text-textMuted">
            Seu perfil não permite cadastrar documentos. A consulta continua disponível.
          </span>
        </div>
      )}

      {semPermissaoAnexar && (
        <div className="card border-l-4 border-l-warning py-3">
          <span className="text-sm text-textMuted">
            Seu perfil não permite anexar arquivos. A consulta e o download continuam disponíveis.
          </span>
        </div>
      )}

      <div className="card p-3 flex flex-col sm:flex-row sm:items-center gap-3">
        <label className="text-sm font-medium whitespace-nowrap" htmlFor="doc-filtro-residente">Residente</label>
        <select
          id="doc-filtro-residente"
          className="input sm:flex-1"
          value={residenteId}
          onChange={e => trocarResidente(e.target.value)}
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
            Não foi possível carregar a lista de residentes. Os documentos aparecem pelo identificador.
          </span>
        </div>
      )}

      {sucesso && (
        <div role="status" className="card border-l-4 border-l-success py-3">
          <span className="text-sm font-medium text-success">{sucesso}</span>
        </div>
      )}

      {documentos.length >= DOCUMENTOS_LIMIT_PADRAO && !erro && (
        <div className="card border-l-4 border-l-warning py-3">
          <span className="text-sm text-textMuted">
            Exibindo os {DOCUMENTOS_LIMIT_PADRAO} documentos mais recentes. Filtre por residente para ver o conjunto completo dele.
          </span>
        </div>
      )}

      {carregando ? (
        <div role="status" aria-live="polite" className="card py-16 text-center text-textMuted">
          Carregando documentos…
        </div>
      ) : erro ? (
        <div className="card py-10 text-center" role="alert">
          <TriangleAlert className="mx-auto mb-2 size-9 text-orange-700" aria-hidden="true" />
          <p className="text-sm text-danger font-medium">{erro}</p>
          <button onClick={() => carregar(residenteId)} className="btn-primary mt-4 inline-flex">Tentar novamente</button>
        </div>
      ) : documentos.length === 0 ? (
        <div className="card py-16 text-center text-textMuted">
          <p className="font-medium">Nenhum documento cadastrado</p>
          <p className="text-sm mt-1">
            {residenteId === TODOS
              ? 'Cadastre o primeiro documento para começar o acervo.'
              : 'Este residente ainda não tem documento cadastrado.'}
          </p>
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {documentos.map(documento => (
            <article key={documento.id} className="card min-w-0">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-semibold break-words">{documento.tipo}</div>
                  <div className="text-xs text-textMuted truncate">
                    {nomes[documento.residente_id ?? ''] || documento.residente_id || '—'}
                  </div>
                </div>
                {/* Situação em texto, não só por cor. */}
                <span className={documento.situacao === 'validado' ? 'badge-success' : 'badge-warning'}>
                  {documento.situacao === 'validado' ? 'Validado' : 'Pendente'}
                </span>
              </div>

              <dl className="mt-3 space-y-1 text-sm">
                {documento.numero && (
                  <div className="flex gap-2">
                    <dt className="text-textMuted">Número:</dt>
                    <dd className="font-medium break-words">{documento.numero}</dd>
                  </div>
                )}
                {documento.validade && (
                  <div className="flex gap-2">
                    <dt className="text-textMuted">Validade:</dt>
                    {/* `validade` é data de calendário: `formatDate` neutraliza a
                        conversão de fuso que imprimiria o dia anterior. */}
                    <dd className="font-medium">{formatDate(documento.validade)}</dd>
                  </div>
                )}
                {documento.responsavel_envio && (
                  <div className="flex gap-2">
                    <dt className="text-textMuted">Envio:</dt>
                    <dd className="font-medium break-words">{documento.responsavel_envio}</dd>
                  </div>
                )}
              </dl>

              {documento.obrigatorio && (
                <p className="mt-2 text-xs font-medium text-warning">Documento obrigatório</p>
              )}

              {documento.arquivo_presente ? (
                <div className="mt-3 space-y-2">
                  <p className="text-sm text-textMuted break-words">
                    <Paperclip className="mr-1 inline size-4 align-[-2px]" aria-hidden="true" />{documento.arquivo_nome_original || 'Arquivo anexado'}
                    {documento.arquivo_tamanho != null && <> — {formatarTamanho(documento.arquivo_tamanho)}</>}
                  </p>
                  <button
                    type="button"
                    onClick={() => baixar(documento)}
                    disabled={baixando === documento.id}
                    className="btn-secondary w-full disabled:opacity-60"
                  >
                    {baixando === documento.id ? 'Baixando…' : 'Baixar arquivo'}
                  </button>
                </div>
              ) : (
                <div className="mt-3 space-y-2">
                  <p className="text-sm text-textMuted">Sem arquivo anexado</p>
                  {!semPermissaoAnexar && (
                    <button
                      type="button"
                      onClick={() => { setSucesso(''); setDocumentoParaAnexo(documento) }}
                      className="btn-secondary w-full"
                    >
                      Anexar arquivo
                    </button>
                  )}
                </div>
              )}
            </article>
          ))}
        </div>
      )}

      <CadastrarDocumentoModal
        open={cadastrando}
        onClose={() => setCadastrando(false)}
        onCadastrado={aoCadastrar}
        residenteFixo={residenteSelecionado}
        residentes={residentes}
        onPermissaoNegada={() => { setCadastrando(false); setSemPermissaoCriar(true) }}
      />

      <AnexarArquivoModal
        open={documentoParaAnexo !== null}
        onClose={() => setDocumentoParaAnexo(null)}
        onAnexado={aoAnexar}
        documento={documentoParaAnexo}
        onPermissaoNegada={() => { setDocumentoParaAnexo(null); setSemPermissaoAnexar(true) }}
      />
    </div>
  )
}

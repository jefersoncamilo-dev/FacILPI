import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { InstituicaoForm } from '../components/platform/InstituicaoForm'
import { PrimeiroGestorForm } from '../components/platform/PrimeiroGestorForm'
import { CredencialTemporariaDialog } from '../components/platform/CredencialTemporariaDialog'
import { Modal } from '../components/Modal'
import { mensagemDeErro } from '../services/api'
import {
  ativarInstituicao,
  atualizarInstituicao,
  criarPrimeiroGestor,
  inativarInstituicao,
  obterInstituicao,
} from '../services/platform'
import { ehAtiva, ehInativa, rotuloSituacao } from '../types/platform'
import type { Instituicao, InstituicaoPayload, PrimeiroGestorPayload } from '../types/platform'

/**
 * Página de provisionamento de uma ILPI: dados, status, primeiro gestor,
 * ativação e ações administrativas.
 *
 * A senha temporária do gestor vive apenas no estado desta tela, entre a
 * resposta do POST e o fechamento do diálogo. Nunca é persistida.
 */
export function PlatformInstituicaoDetalhe() {
  const { id = '' } = useParams()
  const [instituicao, setInstituicao] = useState<Instituicao | null>(null)
  const [erro, setErro] = useState('')
  const [aviso, setAviso] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const [confirmarInativacao, setConfirmarInativacao] = useState(false)
  // Transitório de propósito: sai da memória ao fechar o diálogo.
  const [credencial, setCredencial] = useState<{ email: string; senha: string } | null>(null)

  const carregar = useCallback(async () => {
    setErro('')
    try {
      setInstituicao(await obterInstituicao(id))
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível carregar a instituição.'))
    }
  }, [id])

  useEffect(() => {
    carregar()
  }, [carregar])

  async function salvar(payload: InstituicaoPayload) {
    setErro('')
    setAviso('')
    try {
      setInstituicao(await atualizarInstituicao(id, payload))
      setAviso('Dados atualizados.')
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível salvar os dados.'))
    }
  }

  async function cadastrarGestor(payload: PrimeiroGestorPayload) {
    setErro('')
    setAviso('')
    try {
      const gestor = await criarPrimeiroGestor(id, payload)
      setCredencial({ email: gestor.email, senha: gestor.senha_temporaria })
      await carregar()
    } catch (e) {
      // 409 PRIMEIRO_GESTOR_JA_EXISTE chega aqui como mensagem do backend: a
      // resposta da instituição não informa se já há gestor, então é o servidor
      // que decide — a tela não adivinha.
      setErro(mensagemDeErro(e, 'Não foi possível cadastrar o primeiro gestor.'))
    }
  }

  async function ativar() {
    setErro('')
    setAviso('')
    setOcupado(true)
    try {
      setInstituicao(await ativarInstituicao(id))
      setAviso('Instituição ativada.')
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível ativar a instituição.'))
    } finally {
      setOcupado(false)
    }
  }

  async function inativar() {
    setErro('')
    setAviso('')
    setOcupado(true)
    try {
      setInstituicao(await inativarInstituicao(id))
      setConfirmarInativacao(false)
      setAviso('Instituição marcada como inativa.')
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível inativar a instituição.'))
    } finally {
      setOcupado(false)
    }
  }

  if (!instituicao) {
    return (
      <div className="space-y-4">
        {erro ? (
          <div role="alert" className="text-sm p-3 rounded-xl bg-amber-50 text-amber-800 border border-amber-200">
            {erro}
          </div>
        ) : (
          <p className="text-sm text-textMuted">Carregando instituição...</p>
        )}
        <Link to="/platform/instituicoes" className="text-sm text-primary hover:underline">
          Voltar para a lista
        </Link>
      </div>
    )
  }

  const ativa = ehAtiva(instituicao.situacao)
  const inativa = ehInativa(instituicao.situacao)

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-bold text-primaryDeep truncate">
            {instituicao.nome_fantasia?.trim() || instituicao.razao_social}
          </h1>
          <p className="text-sm text-textMuted">Situação: {rotuloSituacao(instituicao.situacao)}</p>
        </div>
        <Link to="/platform/instituicoes" className="ml-auto text-sm text-primary hover:underline">
          Voltar
        </Link>
      </div>

      {erro && (
        <div role="alert" className="text-sm p-3 rounded-xl bg-amber-50 text-amber-800 border border-amber-200">
          {erro}
        </div>
      )}
      {aviso && (
        <div role="status" className="text-sm p-3 rounded-xl bg-emerald-50 text-emerald-800 border border-emerald-200">
          {aviso}
        </div>
      )}

      <section className="space-y-2">
        <h2 className="font-semibold">Dados da instituição</h2>
        <InstituicaoForm
          instituicao={instituicao}
          onSubmit={salvar}
          submitLabel="Salvar dados"
          disabled={ocupado}
        />
      </section>

      <section className="space-y-2">
        <h2 className="font-semibold">Primeiro gestor</h2>
        <div className="card">
          {ativa ? (
            <p className="text-sm text-textMuted">
              A instituição já está ativa, o que significa que possui administrador institucional.
              Novos usuários são criados pela própria ILPI, na tela de Equipe.
            </p>
          ) : (
            <PrimeiroGestorForm onSubmit={cadastrarGestor} disabled={ocupado} />
          )}
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="font-semibold">Ativação</h2>
        <div className="card space-y-3">
          {ativa ? (
            <>
              <p className="text-sm text-textMuted">
                Instituição ativa. Inativar faz com que ela passe a constar como inativa na
                plataforma.
              </p>
              <button
                onClick={() => setConfirmarInativacao(true)}
                disabled={ocupado}
                className="btn-secondary w-full min-h-[44px] disabled:opacity-60"
              >
                Inativar instituição
              </button>
            </>
          ) : (
            <>
              <p className="text-sm text-textMuted">
                {inativa
                  ? 'Instituição inativa. Ativar volta a torná-la operacional.'
                  : 'Ativar exige CNPJ válido, capacidade, UF e um primeiro gestor cadastrado.'}
              </p>
              <button
                onClick={ativar}
                disabled={ocupado}
                className="btn-primary w-full min-h-[44px] disabled:opacity-60"
              >
                {ocupado ? 'Processando...' : 'Ativar instituição'}
              </button>
            </>
          )}
        </div>
      </section>

      <Modal
        open={confirmarInativacao}
        onClose={() => setConfirmarInativacao(false)}
        title="Inativar instituição"
      >
        <div className="space-y-4">
          <p className="text-sm text-textMain">
            A instituição passará a constar como <strong>inativa</strong> na plataforma.
          </p>
          {/* GATE-1: inativar passou a bloquear o contexto institucional na
              requisicao seguinte, inclusive para quem ja estava com sessao
              aberta. Os vinculos em si continuam existindo — reativar devolve o
              acesso — e por isso a frase fala de acesso, nao de exclusao. */}
          <p className="text-sm text-textMuted">
            Os usuários da instituição deixam de acessar o sistema, mesmo os que já estiverem
            com sessão aberta. Os cadastros e vínculos são preservados: reativar devolve o
            acesso.
          </p>
          <div className="flex gap-2">
            <button onClick={() => setConfirmarInativacao(false)} className="btn-secondary flex-1 min-h-[44px]">
              Cancelar
            </button>
            <button onClick={inativar} disabled={ocupado} className="btn-primary flex-1 min-h-[44px] disabled:opacity-60">
              Confirmar
            </button>
          </div>
        </div>
      </Modal>

      <CredencialTemporariaDialog
        open={credencial !== null}
        onClose={() => setCredencial(null)}
        email={credencial?.email || ''}
        senha={credencial?.senha || ''}
      />
    </div>
  )
}

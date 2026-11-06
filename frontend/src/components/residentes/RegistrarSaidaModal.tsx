import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Modal } from '../Modal'
import { mensagemDeErro } from '../../services/api'
import { paraInputLocal } from '../../services/intercorrencias'
import {
  MOTIVOS_DESLIGAMENTO,
  TIPOS_SAIDA,
  getPendenciasSaida,
  registrarSaida,
  type PendenciasSaida,
  type SaidaPayload,
  type TipoSaida,
} from '../../services/saidaResidente'

interface Props {
  open: boolean
  onClose: () => void
  onRegistrado: () => void
  residente: { id: string; nome: string }
  /** Liberar o leito só aparece para quem tem quartos_leitos:atualizar. */
  podeLiberarLeito: boolean
}

// N2 (#171): nada é encerrado sozinho. A saída muda a situação do residente;
// PAIS, prescrições e programações aparecem como pendências para a ação humana
// de cada módulo, e o leito só é liberado se quem registra marcar a opção.
export function RegistrarSaidaModal({ open, onClose, onRegistrado, residente, podeLiberarLeito }: Props) {
  const [tipo, setTipo] = useState<TipoSaida>('obito')
  const [ocorridoEm, setOcorridoEm] = useState('')
  const [maximo, setMaximo] = useState('')
  const [localObito, setLocalObito] = useState<'ilpi' | 'hospital'>('ilpi')
  const [destinoTipo, setDestinoTipo] = useState<'instituicao' | 'hospital'>('instituicao')
  const [destino, setDestino] = useState('')
  const [motivo, setMotivo] = useState('')
  const [observacao, setObservacao] = useState('')
  const [liberarLeito, setLiberarLeito] = useState(false)
  const [confirmado, setConfirmado] = useState(false)
  const [pendencias, setPendencias] = useState<PendenciasSaida | null>(null)
  const [erro, setErro] = useState('')
  const [salvando, setSalvando] = useState(false)

  // Reabrir sempre começa limpo, com o relógio atual e a opção do leito desmarcada.
  useEffect(() => {
    if (!open) return
    const agora = paraInputLocal(new Date())
    setTipo('obito')
    setOcorridoEm(agora)
    setMaximo(agora)
    setLocalObito('ilpi')
    setDestinoTipo('instituicao')
    setDestino('')
    setMotivo('')
    setObservacao('')
    setLiberarLeito(false)
    setConfirmado(false)
    setErro('')
    setPendencias(null)
    getPendenciasSaida(residente.id).then(setPendencias).catch(() => setPendencias(null))
  }, [open, residente.id])

  const leito = pendencias?.pendencias.find(p => p.origem === 'leito')
  const outras = pendencias?.pendencias.filter(p => p.origem !== 'leito') ?? []

  async function confirmar() {
    if (!ocorridoEm) return setErro('Informe a data e a hora da saída.')
    if (tipo === 'transferencia' && !destino.trim()) return setErro('Informe o destino da transferência.')
    if (tipo === 'desligamento' && !motivo) return setErro('Informe o motivo do desligamento.')
    if (!confirmado) return setErro('Confirme que os dados da saída estão corretos.')
    const payload: SaidaPayload = {
      tipo,
      ocorrido_em: new Date(ocorridoEm).toISOString(),
      liberar_leito: podeLiberarLeito && !!leito && liberarLeito,
      ...(observacao.trim() ? { observacao: observacao.trim() } : {}),
      ...(tipo === 'obito' ? { local_obito: localObito } : {}),
      ...(tipo === 'transferencia' ? { destino_tipo: destinoTipo, destino_descricao: destino.trim() } : {}),
      ...(tipo === 'desligamento' ? { motivo_desligamento: motivo } : {}),
    }
    setSalvando(true)
    setErro('')
    try {
      await registrarSaida(residente.id, payload)
      onRegistrado()
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível registrar a saída.'))
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Registrar saída do residente">
      <div className="space-y-4">
        <p className="text-sm text-textMuted">
          Residente: <span className="font-medium text-textMain">{residente.nome}</span>
        </p>

        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="saida-tipo">Tipo de saída</label>
          <select id="saida-tipo" className="input" value={tipo} onChange={e => setTipo(e.target.value as TipoSaida)}>
            {TIPOS_SAIDA.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="saida-quando">Data e hora</label>
          <input id="saida-quando" className="input" type="datetime-local" max={maximo}
            value={ocorridoEm} onChange={e => setOcorridoEm(e.target.value)} />
        </div>

        {tipo === 'obito' && (
          <div>
            <label className="block text-sm font-medium mb-1" htmlFor="saida-local">Local do óbito</label>
            <select id="saida-local" className="input" value={localObito}
              onChange={e => setLocalObito(e.target.value as 'ilpi' | 'hospital')}>
              <option value="ilpi">Na ILPI</option>
              <option value="hospital">Em hospital</option>
            </select>
          </div>
        )}

        {tipo === 'transferencia' && (
          <>
            <div>
              <label className="block text-sm font-medium mb-1" htmlFor="saida-destino-tipo">Destino</label>
              <select id="saida-destino-tipo" className="input" value={destinoTipo}
                onChange={e => setDestinoTipo(e.target.value as 'instituicao' | 'hospital')}>
                <option value="instituicao">Outra instituição</option>
                <option value="hospital">Hospital</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1" htmlFor="saida-destino">Nome do destino</label>
              <input id="saida-destino" className="input" maxLength={255} value={destino}
                onChange={e => setDestino(e.target.value)} />
            </div>
          </>
        )}

        {tipo === 'desligamento' && (
          <div>
            <label className="block text-sm font-medium mb-1" htmlFor="saida-motivo">Motivo</label>
            <select id="saida-motivo" className="input" value={motivo} onChange={e => setMotivo(e.target.value)}>
              <option value="">Selecione o motivo</option>
              {MOTIVOS_DESLIGAMENTO.map(mo => <option key={mo.value} value={mo.value}>{mo.label}</option>)}
            </select>
          </div>
        )}

        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="saida-obs">Observação (opcional)</label>
          <textarea id="saida-obs" className="input" rows={2} maxLength={500} value={observacao}
            onChange={e => setObservacao(e.target.value)} />
        </div>

        {pendencias && (outras.length > 0 || pendencias.origens_sem_leitura.length > 0) && (
          <section className="rounded-xl border border-border p-3 space-y-2" aria-label="Pendências do residente">
            <p className="text-sm font-medium text-textMain">O que continua ativo</p>
            <p className="text-xs text-textMuted">Nada é encerrado automaticamente. Encerre cada item na tela própria.</p>
            <ul className="space-y-1">
              {outras.map(p => (
                <li key={`${p.origem}-${p.registro_id}`} className="text-sm text-textMain">
                  {p.link ? <Link to={p.link} className="text-primary underline">{p.descricao}</Link> : p.descricao}
                </li>
              ))}
            </ul>
            {pendencias.origens_sem_leitura.length > 0 && (
              <p className="text-xs text-textMuted">Seu perfil não vê todas as origens; pode haver outras pendências.</p>
            )}
          </section>
        )}

        {podeLiberarLeito && leito && (
          <label className="flex items-start gap-2 text-sm min-h-[44px]">
            <input type="checkbox" className="mt-1" checked={liberarLeito} onChange={e => setLiberarLeito(e.target.checked)} />
            <span>Liberar o leito agora ({leito.descricao})</span>
          </label>
        )}

        <label className="flex items-start gap-2 text-sm min-h-[44px]">
          <input type="checkbox" className="mt-1" checked={confirmado} onChange={e => setConfirmado(e.target.checked)} />
          <span>Confirmo os dados. A saída fica no histórico e só pode ser estornada por Administrador da ILPI ou Responsável Técnico.</span>
        </label>

        {erro && <div role="alert" className="text-sm text-danger">{erro}</div>}

        <button type="button" onClick={confirmar} disabled={salvando} className="btn-primary w-full disabled:opacity-60">
          {salvando ? 'Registrando…' : 'Registrar saída'}
        </button>
      </div>
    </Modal>
  )
}

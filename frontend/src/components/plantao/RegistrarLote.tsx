import { useState } from 'react'
import { CircleCheck } from 'lucide-react'
import { mensagemDeErro } from '../../services/api'
import { Dialog, DialogContent } from '../ui/dialog'
import { cn } from '../../lib/utils'
import {
  ROTULO_RESULTADO_CUIDADO,
  registrarCuidado,
  rotuloDoItem,
  type PlantaoItem,
  type ResultadoCuidado,
} from '../../services/plantao'

const HORA = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' })
const DIA = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit' })

// Hora sozinha só para hoje: "02:21" de hoje e de amanhã não podem parecer o mesmo item.
function quando(iso: string, agora = new Date()): string {
  const d = new Date(iso)
  const amanha = new Date(agora); amanha.setDate(agora.getDate() + 1)
  const mesmo = (a: Date, b: Date) => a.toDateString() === b.toDateString()
  if (mesmo(d, agora)) return HORA.format(d)
  if (mesmo(d, amanha)) return `amanhã ${HORA.format(d)}`
  return `${DIA.format(d)} ${HORA.format(d)}`
}
const FALHA = 'Não foi possível salvar. Tentar novamente.'
const EXCECOES: Exclude<ResultadoCuidado, 'executada'>[] = ['recusada', 'omitida']

interface Linha {
  resultado: ResultadoCuidado
  motivo: string
  erro?: string
}

const chave = (item: PlantaoItem) => `${item.origem}:${item.registro_id}`

/**
 * UX-01C — registro em lote. Conveniência de tela: cada cuidado marcado vira
 * UMA execução própria (mesmo `registrarCuidado` do registro individual), com
 * residente, horário, executor da sessão e auditoria individuais. Todos
 * começam como "Realizado"; qualquer item pode virar exceção (Recusado / Não
 * realizado, com motivo) sem abandonar o lote. Falha num item não desfaz os
 * outros: os salvos saem da fila e os que falharam ficam para tentar de novo.
 */
export function RegistrarLote({
  itens,
  nomes,
  onFechar,
  onSalvos,
}: {
  itens: PlantaoItem[] | null
  nomes: Record<string, string>
  onFechar: () => void
  onSalvos: (salvos: PlantaoItem[], restantes: number) => void
}) {
  return (
    <Dialog open={itens !== null} onOpenChange={aberto => { if (!aberto) onFechar() }}>
      {itens && (
        <DialogContent
          title={`Registrar ${itens.length} ${itens.length === 1 ? 'cuidado' : 'cuidados'}`}
          description="Todos como Realizado. Toque em “Exceção” no item que foi diferente."
          focarConteudo
          className="max-sm:bottom-0 max-sm:left-0 max-sm:top-auto max-sm:max-h-[92vh] max-sm:w-full max-sm:max-w-none max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-b-none max-sm:pb-[max(1.5rem,env(safe-area-inset-bottom))]"
        >
          <Lote itens={itens} nomes={nomes} onSalvos={onSalvos} />
        </DialogContent>
      )}
    </Dialog>
  )
}

function Lote({ itens, nomes, onSalvos }: { itens: PlantaoItem[]; nomes: Record<string, string>; onSalvos: (salvos: PlantaoItem[], restantes: number) => void }) {
  const [pendentes, setPendentes] = useState(itens)
  const [linhas, setLinhas] = useState<Record<string, Linha>>(() =>
    Object.fromEntries(itens.map(i => [chave(i), { resultado: 'executada', motivo: '' }])))
  const [abertas, setAbertas] = useState<Set<string>>(() => new Set())
  const [progresso, setProgresso] = useState<number | null>(null)
  const [aviso, setAviso] = useState('')

  const mudar = (k: string, parcial: Partial<Linha>) =>
    setLinhas(atual => ({ ...atual, [k]: { ...atual[k], ...parcial, erro: undefined } }))

  async function registrar() {
    const semMotivo = pendentes.filter(i => linhas[chave(i)].resultado !== 'executada' && !linhas[chave(i)].motivo.trim())
    if (semMotivo.length) {
      setAviso(semMotivo.length === 1 ? 'Informe o motivo da exceção.' : `Informe o motivo das ${semMotivo.length} exceções.`)
      setAbertas(atual => new Set([...atual, ...semMotivo.map(chave)]))
      return
    }
    setAviso('')
    const salvos: PlantaoItem[] = []
    const erros: Record<string, string> = {}
    // Um por vez, na ordem da tela: cada execução é independente e auditada.
    for (const [n, item] of pendentes.entries()) {
      setProgresso(n + 1)
      const linha = linhas[chave(item)]
      try {
        await registrarCuidado(item, { resultado: linha.resultado, justificativa: linha.motivo })
        salvos.push(item)
      } catch (e) {
        erros[chave(item)] = (e as { response?: unknown })?.response ? mensagemDeErro(e, FALHA) : FALHA
      }
    }
    setProgresso(null)
    const restantes = pendentes.filter(i => erros[chave(i)])
    onSalvos(salvos, restantes.length)
    if (restantes.length) {
      setPendentes(restantes)
      setLinhas(atual => Object.fromEntries(restantes.map(i => [chave(i), { ...atual[chave(i)], erro: erros[chave(i)] }])))
      setAviso(`${salvos.length ? `${salvos.length} salvos. ` : ''}${restantes.length} não foram salvos — confira e tente de novo.`)
    }
  }

  const salvando = progresso !== null
  const excecoes = pendentes.filter(i => linhas[chave(i)].resultado !== 'executada').length

  return (
    <div className="space-y-4">
      <ul className="max-h-[50vh] space-y-2 overflow-y-auto">
        {pendentes.map(item => {
          const k = chave(item)
          const linha = linhas[k]
          const aberta = abertas.has(k)
          // Nome acessível único mesmo com dois cuidados do mesmo residente.
          const quem = `${nomes[item.residente_id] || item.residente_id}, ${rotuloDoItem(item)}`
          return (
            <li key={k} className={cn('rounded-lg border p-3', linha.erro ? 'border-danger' : linha.resultado === 'executada' ? 'border-border' : 'border-orange-300')}>
              <div className="flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{nomes[item.residente_id] || item.residente_id}</div>
                  <div className="truncate text-sm text-muted-foreground">
                    {rotuloDoItem(item)}{item.previsto_em ? ` • ${quando(item.previsto_em)}` : ''}
                  </div>
                  <div className={cn('mt-1 text-sm font-medium', linha.resultado === 'executada' ? 'text-emerald-700' : 'text-orange-800')}>
                    {ROTULO_RESULTADO_CUIDADO[linha.resultado]}{linha.resultado !== 'executada' && linha.motivo.trim() ? `: ${linha.motivo.trim()}` : ''}
                  </div>
                </div>
                <button
                  type="button"
                  disabled={salvando}
                  aria-expanded={aberta}
                  aria-label={`${aberta ? 'Fechar exceção' : 'Exceção'} — ${quem}`}
                  onClick={() => setAbertas(atual => {
                    const novo = new Set(atual)
                    if (novo.has(k)) novo.delete(k)
                    else novo.add(k)
                    return novo
                  })}
                  className="min-h-[44px] shrink-0 rounded-lg border border-border px-3 text-sm font-medium hover:bg-muted disabled:opacity-60"
                >
                  {aberta ? 'Fechar' : 'Exceção'}
                </button>
              </div>

              {aberta && (
                <div className="mt-3 space-y-2">
                  <div className="grid grid-cols-3 gap-2" role="group" aria-label={`Resultado — ${quem}`}>
                    {(['executada', ...EXCECOES] as ResultadoCuidado[]).map(valor => (
                      <button
                        key={valor}
                        type="button"
                        aria-pressed={linha.resultado === valor}
                        onClick={() => mudar(k, { resultado: valor })}
                        className={cn(
                          'min-h-[44px] rounded-lg border px-1 text-sm font-medium',
                          linha.resultado === valor ? 'border-primary bg-brand-soft text-primary' : 'border-border hover:bg-muted',
                        )}
                      >
                        {ROTULO_RESULTADO_CUIDADO[valor]}
                      </button>
                    ))}
                  </div>
                  {linha.resultado !== 'executada' && (
                    <input
                      className="input"
                      aria-label={`Motivo — ${quem}`}
                      placeholder="Motivo (obrigatório)"
                      value={linha.motivo}
                      onChange={e => mudar(k, { motivo: e.target.value })}
                    />
                  )}
                </div>
              )}
              {linha.erro && <p className="mt-2 text-sm font-medium text-danger" role="alert">{linha.erro}</p>}
            </li>
          )
        })}
      </ul>

      {aviso && <p className="text-sm font-medium text-orange-900" role="status">{aviso}</p>}

      <button
        type="button"
        onClick={() => void registrar()}
        disabled={salvando}
        className="btn-primary inline-flex min-h-[52px] w-full items-center justify-center gap-2 disabled:opacity-60"
      >
        <CircleCheck className="size-5" aria-hidden="true" />
        {salvando
          ? `Salvando ${progresso} de ${pendentes.length}…`
          : pendentes.length === 1
            ? 'Registrar 1 cuidado'
            : `Registrar ${pendentes.length} cuidados${excecoes ? ` (${excecoes} ${excecoes === 1 ? 'exceção' : 'exceções'})` : ''}`}
      </button>
    </div>
  )
}

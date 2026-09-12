import { formatDateTime } from '../../services/api'
import { ProntuarioCategoria, ProntuarioEvento } from '../../services/prontuario'

const CATEGORIA_LABEL: Record<ProntuarioCategoria, string> = {
  clinico: 'Clínico',
  assistencia: 'Assistência',
  medicacao: 'Medicação',
  administrativo: 'Administrativo',
}

// Selo de categoria: iniciais + texto, nunca cor semântica — categoria é
// classificação, não estado (regras de cor da especificação visual aprovada).
const CATEGORIA_SIGLA: Record<ProntuarioCategoria, string> = {
  clinico: 'CL',
  assistencia: 'AS',
  medicacao: 'MD',
  administrativo: 'AD',
}

// UUID exato — sem heurística por espaço/proporção hexadecimal.
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function chaveDia(iso: string): string {
  return new Intl.DateTimeFormat('pt-BR', {
    timeZone: 'America/Sao_Paulo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(iso))
}

function rotuloDia(chave: string): string {
  const hoje = chaveDia(new Date().toISOString())
  const ontemDate = new Date()
  ontemDate.setDate(ontemDate.getDate() - 1)
  const ontem = chaveDia(ontemDate.toISOString())
  if (chave === hoje) return 'Hoje'
  if (chave === ontem) return 'Ontem'
  return chave
}

function agruparPorDia(eventos: ProntuarioEvento[]): { chave: string; eventos: ProntuarioEvento[] }[] {
  const grupos: { chave: string; eventos: ProntuarioEvento[] }[] = []
  for (const evento of eventos) {
    const chave = chaveDia(evento.ocorrido_em)
    const atual = grupos[grupos.length - 1]
    if (atual && atual.chave === chave) {
      atual.eventos.push(evento)
    } else {
      grupos.push({ chave, eventos: [evento] })
    }
  }
  return grupos
}

function AutorEvento({ autorId }: { autorId?: string | null }) {
  if (!autorId) return null
  if (UUID_RE.test(autorId)) {
    return (
      <span className="font-mono text-xs text-textMuted" title={autorId}>
        {autorId.slice(0, 8)}…
      </span>
    )
  }
  return <span className="text-xs text-textMuted">{autorId}</span>
}

// Estornado/substituído nunca dependem só de cor: sempre têm texto explícito.
function SituacaoEvento({ evento }: { evento: ProntuarioEvento }) {
  if (evento.estornado) return <span className="badge-danger">Estornado</span>
  if (evento.substituido) return <span className="badge-warning">Substituído</span>
  if (evento.situacao) {
    return (
      <span className="px-2.5 py-1 rounded-full text-xs font-semibold inline-flex items-center gap-1 bg-slate-50 text-textMuted border border-slate-200">
        {evento.situacao}
      </span>
    )
  }
  return null
}

export function ProntuarioLinhaDoTempo({ eventos }: { eventos: ProntuarioEvento[] }) {
  const grupos = agruparPorDia(eventos)
  return (
    <div className="space-y-4">
      {grupos.map(grupo => (
        <div key={grupo.chave}>
          <h2 className="text-sm font-semibold text-textMuted mb-2">{rotuloDia(grupo.chave)}</h2>
          <div className="card p-0 divide-y divide-slate-100">
            {grupo.eventos.map(evento => (
              <div key={`${evento.origem}-${evento.registro_id}-${evento.tipo}`} className="p-4 flex gap-3">
                <span
                  aria-hidden="true"
                  className="w-7 h-7 shrink-0 rounded-lg bg-slate-100 text-textMuted text-[11px] font-semibold flex items-center justify-center"
                >
                  {CATEGORIA_SIGLA[evento.categoria]}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-medium text-textMuted">{CATEGORIA_LABEL[evento.categoria]}</span>
                    <SituacaoEvento evento={evento} />
                  </div>
                  <p className="text-sm text-textMain mt-1">{evento.resumo}</p>
                  {evento.estornado && evento.motivo_estorno && (
                    <p className="text-xs text-danger mt-1">Motivo: {evento.motivo_estorno}</p>
                  )}
                  <div className="flex flex-wrap items-center gap-2 mt-1">
                    <span className="text-xs text-textMuted">{formatDateTime(evento.ocorrido_em)}</span>
                    <AutorEvento autorId={evento.autor_id} />
                  </div>
                  {evento.link && (
                    <p className="text-xs text-textMuted mt-1">Detalhe ainda não disponível</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

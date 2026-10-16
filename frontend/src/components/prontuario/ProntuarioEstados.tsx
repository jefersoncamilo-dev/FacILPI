export function ProntuarioCarregando() {
  return (
    <div role="status" aria-live="polite" className="card py-10 text-center text-textMuted">
      <p className="text-sm">Carregando prontuário…</p>
    </div>
  )
}

export function ProntuarioVazio() {
  return (
    <div className="card py-16 text-center text-textMuted">
      <p className="font-medium">Nenhum evento encontrado</p>
      <p className="text-sm mt-1">Ajuste os filtros ou o período para ver outros registros.</p>
    </div>
  )
}

export function ProntuarioErro({ mensagem, onRetry }: { mensagem: string; onRetry: () => void }) {
  return (
    <div role="alert" className="card bg-red-50 border-red-200 py-10 text-center">
      <p className="text-sm text-danger">{mensagem}</p>
      <button type="button" onClick={onRetry} className="btn-secondary mt-4">Tentar novamente</button>
    </div>
  )
}

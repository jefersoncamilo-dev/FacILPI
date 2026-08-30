export function Placeholder({ title, desc }: { title: string; desc?: string }) {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-primaryDeep">{title}</h1>
        <p className="text-textMuted text-sm mt-1">{desc || 'Módulo em construção — estrutura pronta para expansão conforme Project.md'}</p>
      </div>
      <div className="card py-16 text-center">
        <div className="text-5xl mb-3">🚧</div>
        <p className="font-medium">{title}</p>
        <p className="text-sm text-textMuted mt-2 max-w-md mx-auto">Esta seção está com layout, rota protegida e API pronta. Conecte aos endpoints já existentes (<code className="bg-slate-100 px-1 rounded">/api/*</code>) para listar/criar registros. Sidebar e responsividade já validadas em 360/768/1366px.</p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <span className="badge-success">Auth Bearer</span>
          <span className="badge-warning">/api prefix</span>
          <span className="badge-danger">Modal (sem alert)</span>
        </div>
      </div>
    </div>
  )
}

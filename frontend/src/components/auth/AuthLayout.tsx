import type { ReactNode } from 'react'
import { ClipboardCheck, ShieldCheck, Users } from 'lucide-react'
import { Logo } from '../brand/Logo'

/**
 * Casca das telas de autenticação (login, primeiro acesso, escolha de contexto).
 *
 * O banner é FIXO do FacILPI — não é por ILPI, não tem upload nem
 * configuração por tenant, e não depende de endpoint. Desktop: 55% visual /
 * 45% formulário. Mobile/tablet: o banner vira uma faixa superior reduzida e
 * o formulário é o protagonista.
 */
const PILARES = [
  {
    icon: Users,
    titulo: 'Centrado no residente',
    texto: 'O histórico e os cuidados de cada pessoa reunidos ao longo do tempo.',
  },
  {
    icon: ClipboardCheck,
    titulo: 'Rotina da equipe em dia',
    texto: 'Plantão, sinais vitais e intercorrências registrados com clareza.',
  },
  {
    icon: ShieldCheck,
    titulo: 'Acesso por perfil',
    texto: 'Cada profissional vê e faz apenas o que cabe à sua função.',
  },
]

function BannerFundo() {
  return (
    <>
      <div className="absolute inset-0 bg-gradient-to-br from-brand-ink via-primary to-brand-strong" />
      {/* Textura sutil e luzes difusas: acolhimento sem ruído visual. */}
      <div
        className="absolute inset-0 opacity-[0.07]"
        style={{ backgroundImage: 'radial-gradient(circle at 1px 1px, white 1px, transparent 0)', backgroundSize: '22px 22px' }}
      />
      <div className="absolute -right-24 -top-24 size-80 rounded-full bg-emerald-300/20 blur-3xl" />
      <div className="absolute -bottom-32 -left-16 size-96 rounded-full bg-teal-200/10 blur-3xl" />
    </>
  )
}

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-card lg:grid lg:grid-cols-[55fr_45fr]">
      {/* Desktop: painel visual */}
      <aside className="relative hidden overflow-hidden lg:flex lg:flex-col lg:justify-between lg:p-12 xl:p-16">
        <BannerFundo />
        <Logo inverted className="relative" subtitle="Gestão e cuidado para ILPIs" />
        <div className="relative max-w-lg space-y-10">
          <div className="space-y-4">
            <h2 className="font-display text-4xl font-bold leading-tight tracking-tight text-white xl:text-[2.75rem]">
              Cuidado organizado, do acolhimento ao dia a dia.
            </h2>
            <p className="text-lg leading-relaxed text-emerald-50/85">
              Residentes, equipe e rotina assistencial da sua instituição em um só lugar — com segurança e clareza.
            </p>
          </div>
          <ul className="space-y-5">
            {PILARES.map(({ icon: Icon, titulo, texto }) => (
              <li key={titulo} className="flex gap-4">
                <span className="inline-flex size-11 shrink-0 items-center justify-center rounded-xl bg-white/10 text-white ring-1 ring-white/15">
                  <Icon className="size-5" aria-hidden="true" />
                </span>
                <span>
                  <span className="block font-semibold text-white">{titulo}</span>
                  <span className="block text-sm text-emerald-50/75">{texto}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-emerald-50/60">
          Plataforma de gestão para Instituições de Longa Permanência para Idosos.
        </p>
      </aside>

      {/* Mobile/tablet: faixa superior reduzida */}
      <header className="relative overflow-hidden px-5 pb-8 pt-6 sm:px-8 lg:hidden">
        <BannerFundo />
        <div className="relative mx-auto max-w-md">
          <Logo inverted subtitle="Gestão e cuidado para ILPIs" />
          <p className="mt-4 text-sm leading-relaxed text-emerald-50/85">
            Cuidado organizado, do acolhimento ao dia a dia.
          </p>
        </div>
      </header>

      <main className="relative -mt-4 rounded-t-3xl bg-card px-5 pb-10 pt-8 sm:px-8 lg:mt-0 lg:flex lg:items-center lg:justify-center lg:rounded-none lg:px-12">
        <div className="mx-auto w-full max-w-md lg:max-w-sm">{children}</div>
      </main>
    </div>
  )
}

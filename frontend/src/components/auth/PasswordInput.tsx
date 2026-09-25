import { forwardRef, useState, type InputHTMLAttributes } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { Input } from '../ui/input'

/** Campo de senha com mostrar/ocultar acessível por teclado e leitor de tela. */
export const PasswordInput = forwardRef<HTMLInputElement, Omit<InputHTMLAttributes<HTMLInputElement>, 'type'>>(
  (props, ref) => {
    const [visivel, setVisivel] = useState(false)
    return (
      <div className="relative">
        <Input ref={ref} type={visivel ? 'text' : 'password'} className="pr-12" {...props} />
        <button
          type="button"
          onClick={() => setVisivel(v => !v)}
          aria-label={visivel ? 'Ocultar senha' : 'Mostrar senha'}
          aria-pressed={visivel}
          className="absolute right-1 top-1/2 inline-flex size-10 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          {visivel ? <EyeOff className="size-5" aria-hidden="true" /> : <Eye className="size-5" aria-hidden="true" />}
        </button>
      </div>
    )
  },
)
PasswordInput.displayName = 'PasswordInput'

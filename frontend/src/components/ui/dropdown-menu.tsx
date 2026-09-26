import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from 'react'
import * as MenuPrimitive from '@radix-ui/react-dropdown-menu'
import { cn } from '../../lib/utils'

/**
 * Menu suspenso sobre o Radix (UX-11 / #101): teclado (setas, Enter, Escape),
 * foco devolvido ao gatilho e papéis `menu`/`menuitem` prontos. Usado no menu
 * da conta (Alterar senha, Sair).
 */
export const DropdownMenu = MenuPrimitive.Root
export const DropdownMenuTrigger = MenuPrimitive.Trigger

export const DropdownMenuContent = forwardRef<
  ElementRef<typeof MenuPrimitive.Content>,
  ComponentPropsWithoutRef<typeof MenuPrimitive.Content>
>(({ className, sideOffset = 6, ...props }, ref) => (
  <MenuPrimitive.Portal>
    <MenuPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        'z-50 min-w-[200px] overflow-hidden rounded-lg border border-border bg-card p-1 text-foreground shadow-cardHover',
        'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
        className,
      )}
      {...props}
    />
  </MenuPrimitive.Portal>
))
DropdownMenuContent.displayName = 'DropdownMenuContent'

export const DropdownMenuItem = forwardRef<
  ElementRef<typeof MenuPrimitive.Item>,
  ComponentPropsWithoutRef<typeof MenuPrimitive.Item>
>(({ className, ...props }, ref) => (
  <MenuPrimitive.Item
    ref={ref}
    className={cn(
      // 44px: alvo de toque; o menu também é usado no tablet (menu lateral).
      'flex min-h-[44px] cursor-pointer select-none items-center gap-2.5 rounded-md px-3 text-sm font-medium outline-none transition-colors',
      'focus:bg-muted data-[highlighted]:bg-muted data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground',
      className,
    )}
    {...props}
  />
))
DropdownMenuItem.displayName = 'DropdownMenuItem'

export function DropdownMenuLabel({ className, ...props }: ComponentPropsWithoutRef<typeof MenuPrimitive.Label>) {
  return <MenuPrimitive.Label className={cn('px-3 py-2 text-xs text-muted-foreground', className)} {...props} />
}

export function DropdownMenuSeparator({ className, ...props }: ComponentPropsWithoutRef<typeof MenuPrimitive.Separator>) {
  return <MenuPrimitive.Separator className={cn('-mx-1 my-1 h-px bg-border', className)} {...props} />
}

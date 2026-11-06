import { expect, it } from 'vitest'
import { cn } from '../lib/utils'

it('cn mantém estilo de texto da Onda 5 ao lado da cor', () => {
  expect(cn('text-apoio', 'text-foreground')).toBe('text-apoio text-foreground')
  expect(cn('text-sm', 'text-apoio')).toBe('text-apoio')
})

import { expect, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import path from 'node:path'

// Saída de backend/tests/e2e_seed.py: só ids, nomes e e-mails sintéticos.
// A senha nunca passa por arquivo: vem de E2E_PASSWORD, gerada na config.
export const seed = JSON.parse(readFileSync(path.join(process.env.E2E_DIR!, 'seed.json'), 'utf8')) as {
  ilpiA: { nome: string; gestora: Conta; colega: Conta }
  ilpiB: { nome: string; gestora: Conta }
  residenteA: { id: string; nome: string }
  residenteB: { id: string; nome: string }
  admissaoA: { id: string; residente: string }
  planoA: { id: string; intervencao: string }
  medicamento: string
  area: string
}

type Conta = { email: string; nome: string }

// Entra pela tela: vale para sessão por cookie HttpOnly e para o fallback Bearer.
export async function entrar(page: Page, conta: Conta) {
  await page.goto('/login')
  await page.getByLabel('E-mail').fill(conta.email)
  await page.getByLabel('Senha', { exact: true }).fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page).not.toHaveURL(/\/login/, { timeout: 20_000 })
}

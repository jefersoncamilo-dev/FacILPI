import { expect, test } from '@playwright/test'
import { entrar, seed } from './apoio'

test('residente de outra ILPI não existe para quem está na ILPI A (404)', async ({ page }) => {
  await entrar(page, seed.ilpiA.gestora)
  const resposta = page.waitForResponse(r => r.url().endsWith(`/api/residentes/${seed.residenteB.id}`))
  await page.goto(`/residentes/${seed.residenteB.id}`)
  expect((await resposta).status()).toBe(404)
  await expect(page.getByRole('alert')).toContainText('Residente não encontrado.')
  await expect(page.getByText(seed.residenteB.nome)).toHaveCount(0)
})

test('a ILPI B não enxerga os residentes da ILPI A', async ({ page }) => {
  await entrar(page, seed.ilpiB.gestora)
  await page.goto('/residentes')
  await expect(page.getByRole('link', { name: new RegExp(seed.residenteB.nome) })).toBeVisible()
  await expect(page.getByRole('link', { name: new RegExp(seed.residenteA.nome) })).toHaveCount(0)
  const resposta = page.waitForResponse(r => r.url().endsWith(`/api/residentes/${seed.residenteA.id}`))
  await page.goto(`/residentes/${seed.residenteA.id}`)
  expect((await resposta).status()).toBe(404)
})

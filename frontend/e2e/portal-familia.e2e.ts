import { expect, test } from '@playwright/test'
import { randomBytes } from 'node:crypto'
import { entrar, seed } from './apoio'

// #271: a equipe libera o portal, o familiar entra com a senha provisória,
// troca no primeiro acesso e só vê o portal do próprio residente.
test.use({ viewport: { width: 390, height: 844 } })
const API = 'http://127.0.0.1:8000/api'

test('familiar entra no portal e não alcança o resto do sistema', async ({ browser }) => {
  const equipe = await browser.newPage()
  await entrar(equipe, seed.ilpiA.gestora)
  const email = `familia-${randomBytes(4).toString('hex')}@example.com`
  const csrf = (await equipe.context().cookies()).find(c => c.name === 'csrf_token')?.value ?? ''
  const criado = await equipe.request.post(`${API}/familiares/`, {
    headers: { 'X-CSRF-Token': csrf }, data: { residente_id: seed.residenteA.id, nome: 'Filha Portal', email },
  })
  expect(criado.ok(), await criado.text()).toBe(true)

  // UX-NAV-3: familiares ficam na aba Resumo da ficha.
  await equipe.goto(`/residentes/${seed.residenteA.id}?aba=resumo`)
  await equipe.getByLabel('Portal Família de Filha Portal').click()
  await expect(equipe.getByTestId('senha-provisoria')).toBeVisible()
  const senha = (await equipe.getByTestId('senha-provisoria').textContent())!.trim()
  expect(senha.length).toBeGreaterThanOrEqual(12)
  await equipe.close()

  const contexto = await browser.newContext({ viewport: { width: 390, height: 844 } })
  const familia = await contexto.newPage()
  const erros: string[] = []
  familia.on('pageerror', e => erros.push(e.message))
  await familia.goto('/login')
  await familia.getByLabel('E-mail').fill(email)
  await familia.getByLabel('Senha', { exact: true }).fill(senha)
  await familia.getByRole('button', { name: 'Entrar' }).click()
  await expect(familia).toHaveURL(/primeiro-acesso/)
  const nova = `Nova-${randomBytes(9).toString('base64url')}1a`
  await familia.getByPlaceholder('Senha temporária').fill(senha)
  await familia.getByPlaceholder('Nova senha', { exact: true }).fill(nova)
  await familia.getByPlaceholder('Confirmar nova senha').fill(nova)
  await familia.locator('button[type="submit"]').click()
  await expect(familia).toHaveURL(/\/portal$/, { timeout: 20_000 })
  await expect(familia.getByRole('heading', { name: seed.residenteA.nome, level: 1 })).toBeVisible()
  await expect(familia.getByText('Recados da equipe')).toBeVisible()

  expect((await familia.request.get(`${API}/residentes/${seed.residenteA.id}`)).status()).toBe(403)
  const sobra = await familia.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(sobra).toBeLessThanOrEqual(0)
  expect(erros).toEqual([])
  await contexto.close()
})

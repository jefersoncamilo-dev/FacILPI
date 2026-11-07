import { expect, test, type Page } from '@playwright/test'
import { entrar, seed } from './apoio'

// Complementares D5 no navegador real, em largura de celular: tela abre, ação
// principal persiste e a página não rola na horizontal.
test.use({ viewport: { width: 390, height: 844 } })

async function semRolagemLateral(page: Page) {
  const sobra = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(sobra).toBeLessThanOrEqual(0)
}

test('telas complementares funcionam no celular', async ({ page }) => {
  const erros: string[] = []
  page.on('pageerror', e => erros.push(e.message))
  await entrar(page, seed.ilpiA.gestora)
  const residente = seed.residenteA.nome
  const escolher = () => page.getByLabel('Residente', { exact: true }).selectOption({ label: residente })

  for (const [rota, titulo] of [
    ['/configuracoes', 'Configurações'], ['/auditoria', 'Auditoria'], ['/relatorios', 'Relatórios'],
  ]) {
    await page.goto(rota)
    await expect(page.getByRole('heading', { name: titulo, level: 1 })).toBeVisible()
    await semRolagemLateral(page)
  }

  await page.goto('/agenda')
  await escolher()
  await page.getByLabel('Motivo').fill('Consulta sintética')
  await page.getByLabel('Data e hora').fill('2031-03-10T10:00')
  await page.getByRole('button', { name: 'Agendar' }).click()
  await expect(page.getByText('Consulta sintética')).toBeVisible()
  await page.getByRole('button', { name: 'Cancelar', exact: true }).click()
  await page.getByLabel('Por que foi cancelado?').fill('Remarcada')
  await page.getByRole('button', { name: 'Confirmar' }).click()
  await expect(page.getByText('Remarcada')).toBeVisible()
  await semRolagemLateral(page)

  await page.goto('/multidisciplinar/enfermagem')
  await escolher()
  await page.getByLabel('Data e hora').fill('2031-03-10T10:00')
  await page.getByLabel('Evolução').fill('Evolução sintética')
  await page.getByRole('button', { name: 'Registrar atendimento' }).click()
  await expect(page.getByText('Evolução sintética')).toBeVisible()
  await semRolagemLateral(page)

  await page.goto('/pia')
  await escolher()
  await page.getByLabel('Apoio social').fill('Filha sintética')
  await page.getByRole('button', { name: 'Salvar nova versão' }).click()
  await expect(page.getByText(/^Versão 1/)).toBeVisible()
  await semRolagemLateral(page)

  await page.goto('/estoque')
  await page.getByLabel('Novo item').fill('Luva sintética')
  await page.getByLabel('Unidade').fill('cx')
  await page.getByRole('button', { name: 'Cadastrar item' }).click()
  await expect(page.getByRole('option', { name: 'Luva sintética' })).toBeAttached()
  await page.getByLabel('Item', { exact: true }).selectOption({ label: 'Luva sintética' })
  await page.getByLabel('Quantidade').fill('8')
  await page.getByLabel('Lote').fill('L1')
  await page.getByRole('button', { name: 'Registrar movimento' }).click()
  await expect(page.getByText('8 cx')).toBeVisible()
  await semRolagemLateral(page)

  await page.goto('/financeiro')
  await escolher()
  await page.getByLabel('Competência').fill('2031-03')
  await page.getByLabel('Valor (R$)').fill('3500,50')
  await page.getByLabel('Vencimento').fill('2031-03-10')
  await page.getByRole('button', { name: 'Lançar mensalidade' }).click()
  await expect(page.getByText(/3\.500,50/)).toBeVisible()
  await page.getByRole('button', { name: 'Registrar pagamento' }).click()
  await page.getByRole('button', { name: 'Confirmar' }).click()
  await expect(page.getByText('paga', { exact: true })).toBeVisible()
  await semRolagemLateral(page)

  expect(erros).toEqual([])
})

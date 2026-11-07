import { expect, test } from '@playwright/test'
import { entrar, seed } from './apoio'

// #275: gráficos do Início com a API real. O histórico vem do backend; as
// pendências são interceptadas porque dependem da hora em que o teste roda.
for (const largura of [360, 390, 430, 768, 1366]) {
  test(`gráficos do Início em ${largura}px, sem rolagem lateral`, async ({ page }) => {
    await page.setViewportSize({ width: largura, height: 900 })
    const emHoras = (h: number) => new Date(Date.now() + h * 3600_000 + 60_000).toISOString()
    await page.route('**/api/plantao/**', route => route.fulfill({
      json: [1, 1, 2, 4, 4, 7, 9, 11].map((h, i) => ({
        origem: i % 3 === 0 ? 'medicacao' : 'cuidado', registro_id: `p-${i}`, residente_id: seed.residenteA.id,
        descricao: 'Item sintético', previsto_em: emHoras(h), prioridade: null,
      })),
    }))
    await entrar(page, seed.ilpiA.gestora)
    await page.goto('/')

    await expect(page.getByRole('img', { name: /^Pendências com horário nas próximas 12 horas: / })).toBeVisible()
    const painel = page.getByRole('region', { name: 'Intercorrências por semana' })
    await expect(painel).toBeVisible()
    await painel.getByRole('button', { name: '12 semanas' }).click()
    await expect(painel.getByRole('button', { name: '12 semanas' })).toHaveAttribute('aria-pressed', 'true')
    // Sem o endpoint, a tela mostraria a falha; aqui a fonte precisa responder.
    await expect(painel.getByText('Não foi possível carregar o histórico')).toHaveCount(0)

    const sobra = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(sobra).toBeLessThanOrEqual(0)
    if (process.env.E2E_CAPTURAS) {
      await page.screenshot({ path: `${process.env.E2E_CAPTURAS}/inicio-${largura}.png`, fullPage: true })
    }
  })
}

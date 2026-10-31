import { expect, test } from '@playwright/test'
import { entrar, seed } from './apoio'

// Fluxo crítico: Residente → Admissão → PAIS → Rotina → Medicação →
// Intercorrências → Prontuário → Meu Plantão → Passagem. Uma história só, em
// passos, porque cada etapa depende do que a anterior gravou.
// Seletores por papel e texto: resistem ao redesenho visual.
test('fluxo crítico da gestora até a passagem recebida', async ({ page, browser }) => {
  test.setTimeout(180_000)
  const maria = seed.residenteA.nome
  const intercorrencia = 'Queda sem lesão E2E'
  const observacao = 'Maria agitada no fim da tarde (E2E)'

  await test.step('login e residente', async () => {
    await entrar(page, seed.ilpiA.gestora)
    await page.goto('/residentes')
    await page.getByRole('link', { name: new RegExp(maria) }).click()
    await expect(page.getByRole('heading', { level: 1, name: maria })).toBeVisible()
  })

  await test.step('admissão avança de etapa', async () => {
    await page.goto('/admissoes')
    await page.getByRole('link', { name: new RegExp(seed.admissaoA.residente) }).click()
    const etapa = page.getByRole('region', { name: 'Etapa atual' })
    await expect(etapa.getByRole('heading', { name: 'Pré-cadastro' })).toBeVisible()
    await etapa.getByRole('button', { name: 'Avançar para Triagem' }).click()
    await expect(etapa.getByRole('heading', { name: 'Triagem' })).toBeVisible()
  })

  await test.step('PAIS vigente', async () => {
    await page.goto('/plano')
    await page.getByRole('link', { name: new RegExp(`${maria}.*Vigente`) }).click()
    await expect(page.getByRole('region', { name: 'Intervenções' })).toContainText(seed.planoA.intervencao)
  })

  await test.step('rotina programada a partir do PAIS', async () => {
    await page.goto('/cuidados')
    await expect(page.getByRole('region', { name: maria })).toContainText(seed.planoA.intervencao)
  })

  await test.step('medicação ativa e doses de hoje', async () => {
    await page.goto(`/residentes/${seed.residenteA.id}/medicacao`)
    await expect(page.getByRole('region', { name: 'Ativas' }).getByRole('article', { name: seed.medicamento })).toBeVisible()
    await expect(page.getByRole('region', { name: 'Doses de hoje' }).getByRole('listitem')).not.toHaveCount(0)
  })

  await test.step('registrar intercorrência no prontuário', async () => {
    await page.goto(`/residentes/${seed.residenteA.id}`)
    await page.getByRole('button', { name: '+ Registrar intercorrência' }).click()
    const dialogo = page.getByRole('dialog', { name: 'Registrar intercorrência' })
    await dialogo.getByRole('textbox', { name: 'Tipo' }).fill(intercorrencia)
    await dialogo.getByRole('combobox', { name: 'Gravidade' }).selectOption({ label: 'Moderada' })
    await dialogo.getByRole('button', { name: 'Registrar' }).click()
    await expect(dialogo).toBeHidden()
    await expect(page.getByRole('status').filter({ hasText: 'Intercorrência registrada.' })).toBeVisible()
    // O cartão do resumo não se atualiza sozinho após o registro (achado do E2E,
    // fora do escopo): o recarregamento prova a persistência e a repercussão.
    await page.reload()
    await expect(page.getByRole('region', { name: 'Intercorrências abertas' })).toContainText(intercorrencia)
  })

  await test.step('prontuário: linha do tempo', async () => {
    await page.getByRole('tab', { name: 'Linha do tempo' }).click()
    await expect(page.getByRole('tabpanel', { name: 'Linha do tempo' })).toContainText(intercorrencia)
  })

  await test.step('Meu Plantão: iniciar, registrar cuidado e administração', async () => {
    await page.goto('/plantao')
    const turno = page.getByRole('region', { name: 'Meu turno' })
    const area = turno.getByRole('checkbox', { name: seed.area })
    if (await area.count()) await area.check()
    await turno.getByRole('button', { name: 'Iniciar plantão' }).click()
    await expect(turno.getByText('Você não está em plantão')).toBeHidden()

    await page.getByRole('button', { name: 'Registrar', exact: true }).first().click()
    const cuidado = page.getByRole('dialog', { name: 'Registrar cuidado' })
    await cuidado.getByRole('button', { name: 'Realizado', exact: true }).click()
    await expect(cuidado).toBeHidden()

    await page.getByRole('button', { name: 'Registrar administração' }).first().click()
    const dose = page.getByRole('dialog', { name: 'Registrar administração' })
    await expect(dose.getByRole('combobox', { name: 'Resultado' })).toHaveValue(/.+/)
    await dose.getByRole('combobox', { name: 'Resultado' }).selectOption({ label: 'Administrada' })
    // Campo de quantidade ainda sem rótulo acessível (achado do E2E): o único spinbutton do diálogo.
    await dose.getByRole('spinbutton').fill('1')
    await dose.getByRole('button', { name: 'Confirmar' }).click()
    await expect(dose).toBeHidden()
    await expect(page.getByRole('button', { name: 'Registrar administração' })).toHaveCount(1)
  })

  await test.step('passagem entregue', async () => {
    await page.goto('/passagem')
    const passar = page.getByRole('region', { name: 'Passar plantão' })
    await passar.getByRole('button', { name: 'Preparar passagem' }).click()
    await passar.getByRole('textbox', { name: 'Observação' }).fill(observacao)
    await passar.getByRole('button', { name: 'Adicionar observação' }).click()
    await expect(passar.getByRole('list', { name: 'Observações' })).toContainText(observacao)
    await passar.getByRole('button', { name: 'Entregar passagem' }).click()
    await expect(passar.getByRole('alert').or(passar.getByRole('status'))).toContainText('Passagem entregue')
  })

  await test.step('colega da mesma ILPI recebe a passagem', async () => {
    const contexto = await browser.newContext()
    const colega = await contexto.newPage()
    await entrar(colega, seed.ilpiA.colega)
    await colega.goto('/passagem')
    const receber = colega.getByRole('region', { name: 'Passagens a receber' })
    await expect(receber).toContainText(observacao)
    await receber.getByRole('button', { name: 'Confirmar recebimento' }).click()
    await expect(receber).toContainText('Nenhuma passagem aguardando recebimento.')
    await contexto.close()
  })
})

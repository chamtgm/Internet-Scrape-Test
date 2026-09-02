import { expect, test } from '@playwright/test'

test('the feed lists items and clicking one opens its full text', async ({ page }) => {
  await page.goto('/')

  const rows = page.locator('.item-row')
  await expect(rows).toHaveCount(12)

  await expect(page.locator('.health-summary')).toContainText('1 sources')

  // Seeded newest-first: day 0 is the most recent.
  await expect(rows.first().locator('.item-title')).toHaveText('Smoke test article 0')
  await rows.first().click()

  const detail = page.locator('.detail-body')
  await expect(detail).toBeVisible()
  await expect(page.locator('.detail-title')).toContainText('Smoke test article 0')
  expect((await detail.innerText()).length).toBeGreaterThan(240)
})

test('searching narrows the list and clearing restores it', async ({ page }) => {
  await page.goto('/')
  const rows = page.locator('.item-row')
  await expect(rows).toHaveCount(12)

  await page.getByLabel('search').fill('zzzznotarealterm')
  await page.getByLabel('search').press('Enter')
  // Scoped to the list: the detail pane also renders .empty when nothing is
  // selected, and an unscoped locator would match two elements and fail
  // Playwright's strict mode.
  await expect(page.locator('.item-list .empty')).toBeVisible()

  await page.getByLabel('search').fill('collecting')
  await page.getByLabel('search').press('Enter')
  await expect(rows).toHaveCount(12)

  await page.getByRole('button', { name: 'clear' }).click()
  await expect(rows).toHaveCount(12)
})

test('the health strip expands to show per-source detail', async ({ page }) => {
  await page.goto('/')
  await page.locator('.health-summary').click()
  await expect(page.locator('.health-id')).toHaveText('https://e2e/feed')
  await expect(page.locator('.health-meta')).toContainText('12 items')
})

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
  // Safe path: an ordinary http(s) URL still renders as a real link.
  await expect(page.locator('.detail-title a')).toHaveAttribute('href', 'https://e2e/0')
})

test('an item with a javascript: URL renders its title as plain text, not a link', async ({ page }) => {
  // seed_e2e.py's fixture is asserted elsewhere as an exact 12 items/1
  // source (README.md), so a hostile item is injected here by mocking the
  // item-detail response instead of adding a 13th seeded row.
  await page.route('**/api/items/*', (route) =>
    route.fulfill({
      json: {
        id: 999999,
        title: 'Hostile item',
        url: 'javascript:alert(1)',
        author_handle: null,
        published_at: null,
        source_id: 1,
        source_kind: 'rss',
        source_identifier: 'https://e2e/feed',
        excerpt: 'hostile',
        content_text: 'hostile content',
        fetched_at: '2026-09-02T12:00:00Z',
      },
    })
  )
  await page.goto('/')
  await page.locator('.item-row').first().click()

  await expect(page.locator('.detail-title')).toContainText('Hostile item')
  await expect(page.locator('.detail-title a')).toHaveCount(0)
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

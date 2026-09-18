import fs from 'node:fs'
import { expect, test } from '@playwright/test'

const EMAIL = 'e2e-admin@example.test'
const PASSWORD = 'e2e-password-1234'

// seed_e2e.py re-issues this invite on every run and deletes the account the
// previous run's setup test created, so the link below is always unspent.
// Read rather than hardcoded: create_invite stores only the token's SHA-256
// and hands back the raw value once.
const INVITE_TOKEN = fs
  .readFileSync(new URL('.e2e-invite-token', import.meta.url), 'utf8')
  .trim()

test('an anonymous visit shows the login form, not the feed', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.auth')).toBeVisible()
  await expect(page.locator('.item-row')).toHaveCount(0)
})

test('a wrong password is rejected with one generic message', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password', { exact: true }).fill('definitely-not-it')
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page.locator('.auth .error')).toHaveText('Email or password is incorrect.')
  await expect(page.locator('.item-row')).toHaveCount(0)
})

test('an unknown email gives the same message as a wrong password', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Email').fill('nobody@example.test')
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page.locator('.auth .error')).toHaveText('Email or password is incorrect.')
})

test('signing in and out round-trips', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page.locator('.item-row')).toHaveCount(12)
  await expect(page.locator('.whoami')).toContainText('E2E Admin')
  await expect(page.locator('.badge')).toHaveText('admin')

  await page.getByRole('button', { name: 'sign out' }).click()
  await expect(page.locator('.auth')).toBeVisible()
})

test('the session survives a reload without a login flash', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.locator('.item-row')).toHaveCount(12)

  await page.reload()
  await expect(page.locator('.item-row')).toHaveCount(12)
  await expect(page.locator('.auth')).toHaveCount(0)
})

test('an invalid setup token is reported, not silently accepted', async ({ page }) => {
  await page.goto('/#setup=this-token-was-never-issued')

  await expect(page.locator('.auth h1')).toHaveText('Choose a password')
  await page.getByLabel('Password', { exact: true }).fill('a-good-password')
  await page.getByLabel('Confirm password').fill('a-good-password')
  await page.getByRole('button', { name: 'Create account' }).click()

  await expect(page.locator('.auth .error')).toContainText('invalid, expired, or already used')
})

test('mismatched setup passwords are caught before the request', async ({ page }) => {
  await page.goto('/#setup=whatever')

  await page.getByLabel('Password', { exact: true }).fill('a-good-password')
  await page.getByLabel('Confirm password').fill('a-different-password')
  await page.getByRole('button', { name: 'Create account' }).click()

  await expect(page.locator('.auth .error')).toHaveText('The two passwords do not match.')
})

test('subscribing from the strip filters a subscribed-only search', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.locator('.item-row')).toHaveCount(12)

  // With nothing subscribed, a subscribed-only search returns nothing.
  await page.getByLabel('subscribed only').check()
  await page.getByLabel('search').fill('collecting')
  await page.getByLabel('search').press('Enter')
  await expect(page.locator('.item-list .empty')).toBeVisible()

  // Subscribe to the one seeded source, then re-run the same search.
  await page.locator('.subs-summary').click()
  const checkbox = page.locator('.subs-list input[type="checkbox"]').first()
  // .check() clicks and then asserts `checked` immediately, with no retry.
  // This checkbox is controlled by state that only flips after the PUT round
  // -trip and a catalog reload complete (~15-20ms locally), so .check() loses
  // that race and fails "did not change its state" even though the click and
  // the subsequent subscribe both succeed. .click() + a polling
  // expect(...).toBeChecked() waits out the same async gap the `subscribed
  // only` search below already depends on.
  await checkbox.click()
  await expect(checkbox).toBeChecked()
  await page.getByLabel('search').press('Enter')
  await expect(page.locator('.item-row')).toHaveCount(12)
})

test('a valid setup link creates the account and lands in the store', async ({ page }) => {
  await page.goto(`/#setup=${INVITE_TOKEN}`)
  await expect(page.locator('.auth h1')).toHaveText('Choose a password')

  await page.getByLabel('Password', { exact: true }).fill('a-good-password')
  await page.getByLabel('Confirm password').fill('a-good-password')
  await page.getByRole('button', { name: 'Create account' }).click()

  // Straight into the store, already signed in -- no second trip through login.
  await expect(page.locator('.item-row')).toHaveCount(12)
  await expect(page.locator('.whoami')).toContainText('E2E Invitee')
  // Invited as a normal user, so no operator surface.
  await expect(page.locator('.badge')).toHaveCount(0)

  // The token is gone from the address bar, so a reload cannot retry a link
  // that is now spent.
  expect(new URL(page.url()).hash).toBe('')
  await page.reload()
  await expect(page.locator('.item-row')).toHaveCount(12)
})

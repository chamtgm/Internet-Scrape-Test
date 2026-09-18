import fs from 'node:fs'
import { defineConfig } from '@playwright/test'

// @playwright/test is pinned to 1.61.1 in package.json (not a caret range
// left to float) because that is the newest release whose bundled
// playwright-core expects Chromium revision 1228, the revision already
// cached in ~/Library/Caches/ms-playwright on dev machines here. A bare
// `npm install -D @playwright/test` grabs latest, which can want a newer
// revision that isn't cached and fails with "Executable doesn't exist".
// Bumping this version is fine, but run `npx playwright install chromium`
// (or confirm the target revision is already cached) when you do. See
// web/README.md's "End-to-end test" section for the recovery steps.

// The API reads its URL from settings, which prefer a real environment
// variable over .env. Point DATABASE_URL at the test database so the smoke
// test asserts against seeded data rather than whatever the dev database
// happens to hold.
const dotenv = Object.fromEntries(
  fs
    .readFileSync('../.env', 'utf8')
    .split('\n')
    .filter((line) => line.includes('=') && !line.trim().startsWith('#'))
    .map((line) => {
      const i = line.indexOf('=')
      return [line.slice(0, i).trim(), line.slice(i + 1).trim()]
    })
)
const TEST_DB = dotenv.TEST_DATABASE_URL
if (!TEST_DB) throw new Error('TEST_DATABASE_URL is missing from .env')

export default defineConfig({
  testDir: './tests',
  use: { baseURL: 'http://localhost:5173' },
  // Both servers, so `npm run test:e2e` is one command. reuseExistingServer
  // is false for the API: an already-running dev server would be pointed at
  // the development database and would silently invalidate the test.
  webServer: [
    {
      command: 'cd .. && .venv/bin/python -c "from reachstore.api.app import serve; serve()"',
      url: 'http://127.0.0.1:8000/api/sources',
      // Returns 401 now that every endpoint requires a session. Playwright
      // treats 401/403 as "the server is up", which is the only thing this
      // probe needs to establish. Verified: the suite does not hang waiting
      // on this webServer entry.
      env: { DATABASE_URL: TEST_DB },
      reuseExistingServer: false,
      timeout: 30000,
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
      timeout: 30000,
    },
  ],
})

import fs from 'node:fs'
import { defineConfig } from '@playwright/test'

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

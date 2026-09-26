// End-to-end tests (Playwright).
//
// Runs against the system Google Chrome (`channel: 'chrome'`) rather than a
// Playwright-downloaded Chromium: Playwright no longer ships browser builds
// for macOS 12, so `npx playwright install chromium` fails there.
//
// E2E specs live in ./e2e as *.spec.js, kept apart from the Vitest unit tests
// in ./tests (*.test.jsx) so neither runner picks up the other's files.

import { defineConfig, devices } from '@playwright/test';

// Matches server.host/port in vite.config.js. 127.0.0.1, not localhost, for
// the same reason Vite pins it: localhost may resolve to [::1] first.
const BASE_URL = 'http://127.0.0.1:5173';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'github' : 'list',

  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chrome',
      use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    },
  ],

  // Starts Vite for the run, or reuses one you already have open locally.
  // Only the frontend is started; specs that need the API must start the
  // Flask backend themselves or stub /api with page.route().
  webServer: {
    command: 'npm run dev',
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});

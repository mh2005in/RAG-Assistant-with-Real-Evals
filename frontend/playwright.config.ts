import { defineConfig, devices } from '@playwright/test';

/**
 * Mocked E2E: fast, offline UI flows. Every backend call is stubbed with
 * page.route() in the specs, so no backend (or Ollama) is needed — this is the
 * default gate, mirroring the fast/offline pytest suite.
 *
 * The webServer starts `ng serve` (or reuses an app already serving :4200
 * locally, e.g. the compose frontend). In CI it always starts a fresh one.
 *
 * Stack (real-backend) E2E lives in a separate config: playwright.stack.config.ts.
 */
export default defineConfig({
  testDir: './e2e/mocked',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: 'http://localhost:4200',
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm start',
    url: 'http://localhost:4200',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});

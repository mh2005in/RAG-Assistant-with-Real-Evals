import { defineConfig, devices } from '@playwright/test';

/**
 * Stack E2E: runs against the real deployed frontend (nginx serving the built
 * SPA and reverse-proxying to the backend), not mocks. It verifies things only
 * the deployment can prove — the nginx SPA fallback on deep links and the live
 * proxy hop to FastAPI — so it needs the compose stack up.
 *
 * This is the integration tier (cf. @pytest.mark.integration). No webServer:
 * the stack is expected to be running already. Point it elsewhere with
 * E2E_BASE_URL. The deploy-verify agent runs this after the stack is healthy.
 */
export default defineConfig({
  testDir: './e2e/stack',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list']],
  timeout: 60_000,
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:4200',
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});

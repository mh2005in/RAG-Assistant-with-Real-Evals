import { expect, test } from '@playwright/test';

/**
 * Runs against the real deployed stack (nginx + FastAPI + Postgres + Ollama).
 * These assert behaviour that only the deployment provides — the nginx SPA
 * fallback and the live reverse-proxy hop — so they need the compose stack up.
 */
test.describe('deployed stack', () => {
  test('deep-linking a client route falls back to the SPA (nginx try_files)', async ({
    page,
  }) => {
    const res = await page.goto('/admin');
    expect(res?.status()).toBe(200);
    await expect(page.getByRole('heading', { name: /Upload & process/ })).toBeVisible();
  });

  test('/retrieve proxies through nginx to FastAPI', async ({ request }) => {
    const res = await request.post('/retrieve', {
      data: { query: 'hello', access_role: 'public', top_k: 1 },
    });
    // A 200 from the app (even with no stored docs → count 0) proves the proxy
    // hop reached FastAPI rather than being served/blocked by nginx.
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty('query', 'hello');
    expect(body).toHaveProperty('results');
  });

  test('/answer reaches the app and generates through the proxy', async ({ request }) => {
    test.setTimeout(180_000); // real local LLM generation can be slow
    const res = await request.post('/answer', {
      data: { query: 'hello', access_role: 'public', top_k: 1 },
    });
    expect(res.ok()).toBeTruthy();
    expect(await res.json()).toHaveProperty('answer');
  });
});

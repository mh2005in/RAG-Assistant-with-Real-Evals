import { expect, test, type Route } from '@playwright/test';

const chunk = (over: Record<string, unknown> = {}) => ({
  document_id: 1,
  document_name: 'Handbook',
  chunking_strategy: 'semantic',
  chunk_index: 0,
  page_number: 3,
  text: 'Refunds are available within 30 days of purchase.',
  score: 0.87,
  ...over,
});

test.describe('Ask tab (mocked backend)', () => {
  test('Answer mode renders the answer and its sources', async ({ page }) => {
    await page.route('**/answer', async (route: Route) => {
      expect(route.request().method()).toBe('POST');
      await route.fulfill({
        json: {
          query: 'refunds?',
          answer: 'You can get a refund within 30 days. [1]',
          sources: [chunk()],
        },
      });
    });

    await page.goto('/user');
    await page.getByTestId('query').fill('refunds?');
    await page.getByRole('button', { name: 'Answer', exact: true }).click();

    await expect(page.getByTestId('answer-text')).toContainText('within 30 days');
    await expect(page.getByTestId('chunk')).toHaveCount(1);
  });

  test('Retrieve mode renders the ranked chunks', async ({ page }) => {
    await page.route('**/retrieve', async (route: Route) => {
      await route.fulfill({
        json: {
          query: 'refunds',
          count: 2,
          results: [chunk(), chunk({ chunk_index: 1, score: 0.71 })],
        },
      });
    });

    await page.goto('/user');
    await page.getByRole('tab', { name: 'Retrieve' }).click();
    await page.getByTestId('query').fill('refunds');
    await page.getByRole('button', { name: 'Retrieve', exact: true }).click();

    await expect(page.getByRole('heading', { name: /Retrieved chunks \(2\)/ })).toBeVisible();
    await expect(page.getByTestId('chunk')).toHaveCount(2);
  });

  test('surfaces a FastAPI validation error', async ({ page }) => {
    await page.route('**/answer', async (route: Route) => {
      await route.fulfill({
        status: 422,
        json: { detail: [{ loc: ['body', 'query'], msg: 'field required' }] },
      });
    });

    await page.goto('/user');
    await page.getByTestId('query').fill('x');
    await page.getByRole('button', { name: 'Answer', exact: true }).click();

    await expect(page.getByRole('alert')).toContainText('body.query: field required');
  });
});

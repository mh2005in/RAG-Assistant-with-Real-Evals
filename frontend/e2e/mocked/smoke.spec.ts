import { expect, test } from '@playwright/test';

test.describe('smoke', () => {
  test('loads, redirects to Ask, shows nav and default role', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/user$/);
    await expect(page.getByRole('link', { name: 'Ask' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Admin' })).toBeVisible();
    await expect(page.getByTestId('header-role')).toHaveValue('public');
    await expect(page.getByRole('heading', { name: 'Ask your documents' })).toBeVisible();
  });

  test('navigates to the Admin tab', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: 'Admin' }).click();
    await expect(page).toHaveURL(/\/admin$/);
    await expect(page.getByRole('heading', { name: /Upload & process/ })).toBeVisible();
  });
});

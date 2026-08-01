import { expect, test, type Route } from '@playwright/test';

test.describe('Admin tab (mocked backend)', () => {
  test('upload is disabled until an access role is set', async ({ page }) => {
    await page.goto('/admin');

    const uploadBtn = page.getByRole('button', { name: /Upload & process/ });
    await expect(uploadBtn).toBeEnabled(); // seeded with the default 'public'

    await page.getByTestId('admin-role').fill('');
    await expect(uploadBtn).toBeDisabled();
    await expect(page.getByText(/Set an access role above first/)).toBeVisible();
    // The role field itself stays editable so you can unlock the form.
    await expect(page.getByTestId('admin-role')).toBeEditable();

    await page.getByTestId('admin-role').fill('public');
    await expect(uploadBtn).toBeEnabled();
  });

  test('evaluate is gated on a processed document, then pre-filled from it', async ({ page }) => {
    await page.route('**/process', async (route: Route) => {
      await route.fulfill({
        json: {
          processed: true,
          doc_type: 'pdf',
          document_id: 42,
          strategies: [
            { strategy: 'fixed', chunk_count: 10 },
            { strategy: 'semantic', chunk_count: 8 },
          ],
        },
      });
    });
    await page.route('**/evaluate', async (route: Route) => {
      await route.fulfill({
        json: {
          document_id: 42,
          chunking_strategy: 'semantic',
          evaluations: [
            { strategy: 'semantic', questions: 1, answer_similarity: 0.8, hit_rate: 1, selected: true },
            { strategy: 'fixed', questions: 1, answer_similarity: 0.6, hit_rate: 0, selected: false },
          ],
        },
      });
    });

    await page.goto('/admin');

    const evalBtn = page.getByRole('button', { name: /^Evaluate/ });
    await expect(evalBtn).toBeDisabled();
    await expect(page.getByText(/Upload & process a document above first/)).toBeVisible();

    // Upload a (fake, un-read) PDF and process it.
    await page.getByLabel('Document name').fill('Handbook');
    await page.setInputFiles('input[type=file]', {
      name: 'handbook.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4 mock'),
    });
    await page.getByRole('button', { name: /Upload & process/ }).click();
    await expect(page.getByText(/Stored as document #42/)).toBeVisible();

    // Evaluation is now unlocked with the document id pre-filled and read-only.
    await expect(evalBtn).toBeEnabled();
    const docId = page.locator('input[name=documentId]');
    await expect(docId).toHaveValue('42');
    await expect(docId).not.toBeEditable();

    await page.getByPlaceholder('Question').fill('What is the refund window?');
    await page.getByPlaceholder('Expected answer').fill('30 days');
    await evalBtn.click();

    await expect(page.getByText(/Winner for document #42/)).toBeVisible();
    // The winning (selected) strategy row is the semantic one, marked with ✓.
    const winner = page.locator('tr.selected');
    await expect(winner).toContainText('semantic');
    await expect(winner).toContainText('✓');
  });
});

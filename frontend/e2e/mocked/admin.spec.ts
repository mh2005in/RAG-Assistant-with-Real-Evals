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

  test('structural options are sent as the JSON structural field', async ({ page }) => {
    let body = '';
    await page.route('**/process', async (route: Route) => {
      body = route.request().postData() ?? '';
      await route.fulfill({
        json: {
          processed: true,
          doc_type: 'pdf',
          document_id: 7,
          strategies: [{ strategy: 'structural', chunk_count: 11 }],
        },
      });
    });

    await page.goto('/admin');
    await page.getByLabel('Document name').fill('Contract');
    await page.setInputFiles('input[type=file]', {
      name: 'contract.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4 mock'),
    });
    // One regex per line, and only the bound that was filled in.
    await page.getByTestId('heading-patterns').fill('^Clause \\d+\n^Schedule [A-Z]');
    await page.locator('input[name=maxWords]').fill('300');
    await page.getByRole('button', { name: /Upload & process/ }).click();

    await expect(page.getByText(/Stored as document #7/)).toBeVisible();
    expect(body).toContain('name="structural"');
    expect(body).toContain(
      JSON.stringify({
        heading_patterns: ['^Clause \\d+', '^Schedule [A-Z]'],
        max_words: 300,
      }),
    );
  });

  test('no structural field is sent when the options are left blank', async ({ page }) => {
    let body = '';
    await page.route('**/process', async (route: Route) => {
      body = route.request().postData() ?? '';
      await route.fulfill({
        json: { processed: true, doc_type: 'pdf', document_id: 8, strategies: [] },
      });
    });

    await page.goto('/admin');
    await page.getByLabel('Document name').fill('Handbook');
    await page.setInputFiles('input[type=file]', {
      name: 'handbook.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4 mock'),
    });
    await page.getByRole('button', { name: /Upload & process/ }).click();

    await expect(page.getByText(/Stored as document #8/)).toBeVisible();
    // The backend then uses the strategy's built-in markers and bounds.
    expect(body).not.toContain('name="structural"');
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
            { strategy: 'structural', chunk_count: 11 },
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
            {
              strategy: 'semantic',
              questions: 1,
              answer_similarity: 0.8,
              hit_rate: 1,
              selected: true,
            },
            {
              strategy: 'fixed',
              questions: 1,
              answer_similarity: 0.6,
              hit_rate: 0,
              selected: false,
            },
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

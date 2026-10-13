// Shareable links: the search in the address bar, Back and Forward, Copy link, and opening a shared link.
const { test, expect } = require('./support/fixtures');
const { rows } = require('./support/data');
const { tableRows } = require('./support/page-model');

const query = page => new URL(page.url()).searchParams.get('q');
const historyLength = page => page.evaluate(() => history.length);

test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

test('a search goes into the address bar and the tab title', async ({ page, server }) => {
  await page.goto('/');
  await server.searchAndFinish('MacBook Air');
  expect(query(page)).toBe('MacBook Air');
  expect(await page.title()).toMatch(/^MacBook Air — /);
  await server.searchAndFinish('iPhone 17', rows({ base: 799 }));
  expect(query(page)).toBe('iPhone 17');
});

test('Back and Forward run the searches again; the start page is empty', async ({ page, server }) => {
  await page.goto('/');
  await server.searchAndFinish('MacBook Air');
  await server.searchAndFinish('iPhone 17', rows({ base: 799 }));
  const searches = await server.count();
  await page.goBack();
  await expect(page.locator('#productInput')).toHaveValue('MacBook Air');
  expect(await server.count()).toBe(searches + 1);                  // Back re-ran it
  await (await server.latest()).complete(rows());
  const entries = await historyLength(page);
  await page.goBack();
  await expect.poll(() => query(page)).toBe(null);
  await expect(page.locator('#productInput')).toHaveValue('');
  await expect(page.locator('#summary')).toBeHidden();
  expect(await page.locator('#results').innerHTML()).toBe('');
  await page.goForward();
  await expect(page.locator('#productInput')).toHaveValue('MacBook Air');
  await (await server.latest()).complete(rows());
  expect(await historyLength(page)).toBe(entries);                 // without adding history
  await server.searchAndFinish('MacBook Air');
  expect(await historyLength(page)).toBe(entries);                 // repeating a search adds none either
});

test('Copy link puts the address on the clipboard', async ({ page, server }) => {
  await page.goto('/');
  await server.searchAndFinish('MacBook Air');
  await page.click('#copyLinkBtn');
  await expect(page.locator('#copyLinkBtn')).toHaveText('✓ Link copied');
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(page.url());
});

test.describe('opening a shared link', () => {
  test.use({ locale: 'en-US' });

  test('starts the search at once, with the visitor\'s own home country', async ({ page, server }) => {
    await page.goto('/?q=MacBook+Air');
    await expect(page.locator('#productInput')).toHaveValue('MacBook Air');
    expect(await server.count()).toBe(1);
    expect(await (await server.latest()).url()).toMatch(/product=MacBook%20Air/);
    await (await server.latest()).complete(rows());
    await expect(page.locator('#homeSelect')).toHaveValue('United States');
    await expect.poll(async () => (await tableRows(page)).find(r => r.country === 'Japan').converted).toMatch(/\$/);
    expect(await historyLength(page)).toBeLessThanOrEqual(2);
  });
});

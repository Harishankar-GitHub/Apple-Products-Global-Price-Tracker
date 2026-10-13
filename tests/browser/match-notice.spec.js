// When the API priced a different product from the one typed, the page says which.
const { test, expect } = require('./support/fixtures');
const { rows } = require('./support/data');
const { summary } = require('./support/page-model');

const NOTE = 'Showing prices for Apple Watch Ultra 4 — the closest match found for "Apple Watch Ultra 2".';
const ULTRA_4 = { slug: 'apple-watch-ultra-4', matchedName: 'Apple Watch Ultra 4', substituted: true };
const EXACT = { slug: 'macbook-air', matchedName: 'MacBook Air', substituted: false };

const note = page => page.evaluate(() => {
  const n = document.getElementById('matchNote');
  return { shown: !n.hidden && n.getBoundingClientRect().height > 0, text: n.textContent, html: n.innerHTML, role: n.getAttribute('role') };
});
const csvName = async page => {
  const [download] = await Promise.all([page.waitForEvent('download'), page.click('#exportCsvBtn')]);
  return download.suggestedFilename();
};

test.beforeEach(async ({ page }) => { await page.goto('/'); });

test('a different product: the notice, the heading and the title name what was priced', async ({ page, server }) => {
  const stream = await server.search('Apple Watch Ultra 2');
  await stream.searching('Apple Watch Ultra 2');
  await stream.meta({ product: 'Apple Watch Ultra 2', ...ULTRA_4 });
  expect(await note(page)).toMatchObject({ shown: true, text: NOTE });                // before any price arrives
  await expect(page.locator('#progressLabel')).toHaveText('Fetching prices for "Apple Watch Ultra 4"…');
  await stream.results(rows());
  await stream.done({ product: 'Apple Watch Ultra 2' });
  await expect(page.locator('#searchBtn')).toHaveText('Search');
  const n = await note(page);
  expect(n).toMatchObject({ shown: true, text: NOTE, role: 'status' });
  expect(n.html).toContain('<strong>Apple Watch Ultra 4</strong>');
  expect((await summary(page)).product).toBe('🍎 Apple Watch Ultra 4');
  expect(await page.title()).toMatch(/^Apple Watch Ultra 4 — /);
  // what was typed stays in the box, the link and recent searches
  await expect(page.locator('#productInput')).toHaveValue('Apple Watch Ultra 2');
  expect(new URL(page.url()).searchParams.get('q')).toBe('Apple Watch Ultra 2');
  await expect(page.locator('#recentWrap [data-recent]').first()).toHaveText('Apple Watch Ultra 2');
  expect(await csvName(page)).toMatch(/^apple-watch-ultra-4-prices-\d{4}-\d\d-\d\d\.csv$/);
  const box = await page.evaluate(() => {
    const n = document.getElementById('matchNote').getBoundingClientRect(), s = document.querySelector('.summary-bar').getBoundingClientRect();
    return { below: n.top >= s.bottom, above: n.bottom <= document.getElementById('controls').getBoundingClientRect().top, width: n.width, summaryWidth: s.width };
  });
  expect(box.below && box.above).toBe(true);
  expect(Math.abs(box.width - box.summaryWidth)).toBeLessThan(2);
});

test('the same product, however it is spelled: no notice', async ({ page, server }) => {
  await server.searchAndFinish('Apple Watch Ultra 2', rows(), { meta: ULTRA_4 });
  await server.searchAndFinish('MacBook Air', rows(), { meta: EXACT });
  expect((await note(page)).shown).toBe(false);
  expect((await summary(page)).product).toBe('🍎 MacBook Air');
  await server.searchAndFinish('macbook  air', rows(), { meta: EXACT });
  expect((await note(page)).shown).toBe(false);
  await expect(page.locator('#summaryProduct')).toHaveText('🍎 macbook  air', { useInnerText: false });
  expect(await csvName(page)).toMatch(/^macbook-air-prices-/);
});

test('Back re-runs the earlier search without showing its old notice early; the start page has none', async ({ page, server }) => {
  await server.searchAndFinish('Apple Watch Ultra 2', rows(), { meta: ULTRA_4 });
  await server.searchAndFinish('MacBook Air', rows(), { meta: EXACT });
  await page.goBack();
  await expect(page.locator('#productInput')).toHaveValue('Apple Watch Ultra 2');
  expect((await note(page)).shown).toBe(false);
  await (await server.latest()).complete(rows(), { meta: { product: 'Apple Watch Ultra 2', ...ULTRA_4 } });
  await expect.poll(async () => (await note(page)).text).toBe(NOTE);
  for (let i = 0; i < 4 && new URL(page.url()).searchParams.get('q'); i++) await page.goBack();
  expect(new URL(page.url()).searchParams.get('q')).toBe(null);
  expect(await note(page)).toMatchObject({ shown: false, text: '' });
});

test('a cached result shows both the notice and the cache badge', async ({ page, server }) => {
  await server.searchAndFinish('Apple Watch Ultra', rows(), {
    meta: { cached: true, ageSeconds: 7500, expiresInSeconds: 14_100, ...ULTRA_4 }, done: { cached: true } });
  expect((await note(page)).text).toBe('Showing prices for Apple Watch Ultra 4 — the closest match found for "Apple Watch Ultra".');
  await expect(page.locator('#cacheBadge')).toHaveClass(/visible/);
});

for (const [label, meta] of [
  ['an older API without match information', { slug: 'apple-watch-ultra-3', matchedName: undefined, substituted: undefined }],
  ['the flag without a name', { slug: 'x', matchedName: undefined, substituted: true }],
  ['an empty name', { slug: 'x', substituted: true, matchedName: '   ' }],
  ['a name that is not text', { slug: 'x', substituted: true, matchedName: { a: 1 } }],
  ['the flag as the text "true"', { slug: 'x', substituted: 'true', matchedName: 'Other' }],
  ['the flag false with a name', { slug: 'x', substituted: false, matchedName: 'Other' }],
]) {
  test(`${label}: no notice, the page works`, async ({ page, server }) => {
    await server.searchAndFinish('Mac mini', rows(), { meta });
    expect((await note(page)).shown).toBe(false);
    expect((await summary(page)).product).toBe('🍎 Mac mini');
    await expect(page.locator('#results tbody tr[data-key]')).toHaveCount(30);
  });
}

test('a slug that is not text: the CSV is named after what was typed', async ({ page, server }) => {
  await server.searchAndFinish('Mac mini', rows(), { meta: { slug: 42 } });
  expect(await csvName(page)).toMatch(/^mac-mini-prices-/);
});

test('the search fails after the product was identified: no notice left behind', async ({ page, server }) => {
  const stream = await server.search('Apple Watch Ultra 2');
  await stream.searching('Apple Watch Ultra 2');
  await stream.meta({ product: 'Apple Watch Ultra 2', ...ULTRA_4 });
  await stream.error();
  await expect(page.locator('#status')).toContainText('Could not reach the API');
  await expect.poll(async () => (await note(page)).shown).toBe(false);
  await server.searchAndFinish('MacBook Air', rows(), { meta: EXACT });
  expect((await note(page)).shown).toBe(false);
});

test('no country returned a price: the message names the product looked up', async ({ page, server }) => {
  const none = rows().map(r => ({ country: r.country, flag: r.flag, available: false, reason: 'Price not found', url: r.url }));
  await server.searchAndFinish('Apple Watch Ultra 2', none, { meta: ULTRA_4 });
  await expect(page.locator('#results')).toContainText('No prices found for Apple Watch Ultra 4 in any country.');
  expect((await note(page)).text).toBe(NOTE);
});

test.describe('phone, dark mode', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2, colorScheme: 'dark' });

  test('a shared link to a renamed product: the notice fits and is readable', async ({ page, server }) => {
    await page.goto('/?q=' + encodeURIComponent('Apple Watch Ultra 2'));
    await (await server.latest()).complete(rows(), { meta: { product: 'Apple Watch Ultra 2', ...ULTRA_4 } });
    await expect.poll(async () => (await note(page)).text).toBe(NOTE);
    expect((await summary(page)).product).toBe('🍎 Apple Watch Ultra 4');
    const fit = await page.evaluate(() => {
      const n = document.getElementById('matchNote');
      const r = n.getBoundingClientRect();
      return { overflow: document.documentElement.scrollWidth - innerWidth, left: r.left, right: r.right, width: innerWidth, color: getComputedStyle(n).color };
    });
    expect(fit.overflow).toBeLessThanOrEqual(0);
    expect(fit.left >= 0 && fit.right <= fit.width).toBe(true);
    expect(fit.color).toBe('rgb(245, 245, 247)');                       // light text on the tinted background
  });
});

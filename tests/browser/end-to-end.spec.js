// The real page against the real API (gunicorn, production settings), with only
// apple.com faked (tests/servers/fake_api.py, which answers at uneven speeds like
// a real network). These tests share one server, so they run one after another and
// each starts from a clean server.
const fs = require('fs');
const { test, expect } = require('@playwright/test');

const API = 'http://127.0.0.1:5055';
const WAKE = 'Waking up the server… this can take up to a minute';

test.describe.configure({ mode: 'serial' });

let pageErrors = [];

test.beforeEach(async ({ page, request }) => {
  const reset = await (await request.get(`${API}/__test/reset`, { timeout: 90_000 })).json();
  test.info().annotations.push({ type: 'reset', description: `waited ${reset.waited} s for running fetches` });
  pageErrors = [];
  page.on('pageerror', e => pageErrors.push(String(e)));
});

test.afterEach(() => {
  expect(pageErrors, 'errors in the page').toEqual([]);
});

/** Search from the box and wait until the page has finished (results or a message). */
async function search(page, product) {
  await page.fill('#productInput', product);
  await page.keyboard.press('Escape');
  await page.press('#productInput', 'Enter');
  await expect(page.locator('#searchBtn')).toHaveText('Search', { timeout: 60_000 });
  return state(page);
}

const state = page => page.evaluate(() => ({
  rows: [...document.querySelectorAll('#results tbody tr[data-key]')].map(tr => tr.dataset.key),
  status: document.getElementById('status').textContent.trim(),
  cached: document.getElementById('cacheBadge').classList.contains('visible'),
  badge: document.getElementById('cacheBadge').textContent.trim().replace(/\s+/g, ' '),
  badgeTitle: document.getElementById('cacheBadge').title,
  footer: document.querySelector('.results-footer')?.textContent.trim().replace(/\s+/g, ' ') ?? '',
  progress: getComputedStyle(document.getElementById('progressWrap')).display !== 'none',
  recent: [...document.querySelectorAll('[data-recent]')].map(e => e.textContent),
  note: document.getElementById('matchNote').hidden ? null : document.getElementById('matchNote').textContent,
}));

const rowText = (page, country) => page.locator(`tr[data-key="${country}"]`).innerText().then(t => t.replace(/\s+/g, ' '));

test('a live search streams in and is shown correctly', async ({ page }) => {
  await page.goto('/');
  await page.fill('#productInput', 'iPhone 17');
  await page.press('#productInput', 'Enter');
  const counts = new Set();
  while ((await page.locator('#searchBtn').textContent()) !== 'Search') {
    counts.add(await page.locator('#results tbody tr[data-key]').count());
    await page.waitForTimeout(100);
  }
  expect(counts.size).toBeGreaterThanOrEqual(3);                    // rows arrived progressively
  const s = await state(page);
  expect(s.rows).toHaveLength(30);
  expect(s.rows[0]).toBe('Japan');
  expect(await rowText(page, 'Ireland')).toMatch(/€970\.00.*Home|Home.*€970\.00/);
  expect(await rowText(page, 'United States')).toMatch(/\$799.*≈ €735\.08/);
  expect(s.footer).toMatch(/^30 prices found · 20 countries without a price/);
  expect(new URL(page.url()).search).toBe('?q=iPhone+17');
  expect(s.recent).toEqual(['iPhone 17']);
  await expect(page.locator('#views')).toHaveClass(/split/);
  await expect(page.locator('.chart-row')).toHaveCount(30);
  // a currency only the API's rates can provide (no store here prices in KWD)
  await page.selectOption('#currencySelect', 'KWD');
  const kuwaiti = await page.locator('tr[data-key="Japan"] .price-conv').textContent();
  expect(Number(kuwaiti.replace(/[^0-9.]/g, ''))).toBeCloseTo(775.03 * 0.31, 0);
  await expect(page.locator('#summaryNote')).not.toContainText('No exchange rate');
  await page.selectOption('#currencySelect', '');
  const [download] = await Promise.all([page.waitForEvent('download'), page.click('#exportCsvBtn')]);
  const csv = fs.readFileSync(await download.path(), 'utf8');
  expect(download.suggestedFilename()).toMatch(/^iphone-17-prices-/);
  expect(csv.trim().split('\r\n')).toHaveLength(31);
});

test('the server cache: repeat searches are instant and show their real age', async ({ page, request }) => {
  await page.goto('/');
  await search(page, 'iPhone 17');
  let s = await search(page, 'iPhone 17');
  expect(s).toMatchObject({ cached: true, badge: '⚡ cached · prices from under a minute ago' });
  expect(s.footer).toMatch(/Updated just now$/);
  await request.get(`${API}/__test/advance?seconds=7500`);          // 2 h 5 min later
  const started = Date.now();
  s = await search(page, 'iPhone 17');
  expect(Date.now() - started).toBeLessThan(3000);
  expect(s).toMatchObject({ cached: true, badge: '⚡ cached · prices from 2 h 5 min ago' });
  expect(s.footer).toMatch(/Updated 2 h 5 min ago$/);
  expect(s.badgeTitle).toMatch(/in 3 h 5[45] min/);
  await request.get(`${API}/__test/advance?seconds=14400`);         // past 6 hours
  s = await search(page, 'iPhone 17');
  expect(s.cached).toBe(false);
  expect(s.rows).toHaveLength(30);
  expect(s.footer).toMatch(/Updated just now$/);
});

test('names: an unknown product, a renamed one, and one without any price', async ({ page }) => {
  await page.goto('/?q=iPad+Neo');
  await expect(page.locator('.error-msg')).toContainText('Could not find "iPad Neo"', { timeout: 60_000 });
  let s = await search(page, 'Apple Watch Ultra 2');
  expect(s.note).toBe('Showing prices for Apple Watch Ultra 4 — the closest match found for "Apple Watch Ultra 2".');
  expect(s.rows).toHaveLength(30);
  await expect(page.locator('#summaryProduct')).toHaveText('🍎 Apple Watch Ultra 4');
  expect(await page.title()).toMatch(/^Apple Watch Ultra 4/);
  const links = await page.locator('.store-link').evaluateAll(as => as.map(a => a.href));
  expect(links.every(h => h.includes('apple-watch-ultra-4'))).toBe(true);
  s = await search(page, 'MacBook Air');
  expect(s.note).toBe(null);
  s = await search(page, 'AirTag');
  expect(await page.locator('#results').innerText()).toMatch(/^No prices found for AirTag in any country\./);
  expect(s.status).toBe('');
  await expect(page.locator('#summaryFound')).toHaveText('0');
  await expect(page.locator('#chartView')).toBeHidden();
  await page.check('#showUnavail');
  await expect(page.locator('#results tbody tr[data-key]')).toHaveCount(50);
});

test('apple.com not answering: "try again", cached products still work, then recovery', async ({ page, request }) => {
  await page.goto('/');
  await search(page, 'iPhone 17');
  await request.get(`${API}/__test/outage?mode=timeout`);
  let s = await search(page, 'MacBook Air');
  expect(s.status).toMatch(/^⚠️ Apple did not respond while looking up "MacBook Air", so it could not be checked\. Please try again in \d+ seconds\.$/);
  expect(s).toMatchObject({ rows: [], progress: false });
  await expect(page.locator('#summary')).toBeHidden();
  expect(s.recent).not.toContain('MacBook Air');
  s = await search(page, 'iPhone 17');
  expect(s).toMatchObject({ cached: true, status: '' });
  expect(s.rows).toHaveLength(30);
  await request.get(`${API}/__test/outage?mode=off`);
  s = await search(page, 'MacBook Air');
  expect(s.status).toMatch(/Apple did not respond/);               // held for a minute: no hammering
  await request.get(`${API}/__test/advance?seconds=61`);
  s = await search(page, 'MacBook Air');
  expect(s.rows).toHaveLength(30);
  expect(s.recent[0]).toBe('MacBook Air');
  s = await search(page, 'Nonexistent Thing');
  expect(s.status).toMatch(/^⚠️ Could not find "Nonexistent Thing" on apple\.com\./);
});

test('rate limits: the page explains them and cached products keep working', async ({ page, request }) => {
  await request.get(`${API}/__test/limits?lookups=2`);
  await page.goto('/');
  expect((await search(page, 'MacBook Air')).rows).toHaveLength(30);
  expect((await search(page, 'iPhone 17')).rows).toHaveLength(30);
  let s = await search(page, 'Mac mini');
  expect(s.status).toMatch(/^⚠️ You have looked up a lot of products in a short time\. Please try again in \d+ minutes\.$/);
  expect(s).toMatchObject({ rows: [], progress: false });
  await expect(page.locator('#summary')).toBeHidden();
  expect(s.recent).not.toContain('Mac mini');
  s = await search(page, 'MacBook Air');
  expect(s).toMatchObject({ cached: true, status: '' });
  const fromPage = await page.evaluate(api => fetch(`${api}/api/cache/status`).then(r => r.text()), API);
  expect(fromPage).not.toMatch(/macbook|iphone|mac mini/i);
  const admin = await (await request.get(`${API}/api/cache/status`, { headers: { 'X-Admin-Token': 'browser-test-token' } })).json();
  expect(admin.slug_cache.keys).toContain('macbook air');
  const json = await page.evaluate(api => fetch(`${api}/api/prices?product=Apple+Watch`)
    .then(async r => ({ status: r.status, body: await r.json() })), API);
  expect(json.status).toBe(429);
  expect(json.body).toMatchObject({ rateLimited: true });
});

test('an exchange rate the service left out', async ({ page, request }) => {
  await request.get(`${API}/__test/rates?drop=INR`);
  await page.goto('/');
  for (const pass of ['fetched', 'cached']) {
    const s = await search(page, 'MacBook Air');
    expect(s.cached, pass).toBe(pass === 'cached');
    expect(s.rows.at(-1)).toBe('India');
    expect(await rowText(page, 'India')).toMatch(/₹.*No exchange rate/);
    await expect(page.locator('tr[data-key="India"] .rank')).toHaveText('—');
    await expect(page.locator('#summaryNote')).toContainText('No exchange rate for India');
    expect(s.footer).toMatch(/1 without an exchange rate/);
    expect(await page.evaluate(() => document.body.innerText)).not.toMatch(/[$€]0\.00/);
  }
});

test('a cold server: the wait is explained, then the search completes', async ({ page }) => {
  let hold = 4000;
  await page.route(`${API}/**`, async route => {
    await new Promise(resolve => setTimeout(resolve, hold));
    await route.continue().catch(() => {});
  });
  await page.goto('/');
  await page.waitForTimeout(1000);
  await page.fill('#productInput', 'MacBook Air');
  await page.press('#productInput', 'Enter');
  await expect(page.locator('#progressLabel')).toHaveText(WAKE, { timeout: 5000 });
  await expect(page.locator('#progressCount')).toHaveText(/^\d+s$/);
  await expect(page.locator('#searchBtn')).toHaveText('Search', { timeout: 60_000 });
  expect((await state(page)).rows).toHaveLength(30);
  hold = 0;                                                         // awake now
  await page.reload();
  await page.fill('#productInput', 'iPhone 17');
  await page.press('#productInput', 'Enter');
  const labels = new Set();
  while ((await page.locator('#searchBtn').textContent()) !== 'Search') {
    labels.add(await page.locator('#progressLabel').textContent());
    await page.waitForTimeout(100);
  }
  expect([...labels]).not.toContain(WAKE);
});

test('several visitors at once: two fetch, the third waits its turn, cached results never wait', async ({ browser }) => {
  test.slow();                                                        // three searches of up to ~12 s each
  const visitor = async () => {
    const page = await (await browser.newContext()).newPage();
    await page.goto('/');
    return page;
  };
  const start = async (page, product) => {
    await page.fill('#productInput', product);
    await page.keyboard.press('Escape');
    await page.press('#productInput', 'Enter');
  };
  const [a, b, c, d] = await Promise.all([visitor(), visitor(), visitor(), visitor()]);
  await search(d, 'iPhone 17');                                       // in the cache
  await Promise.all([start(a, 'prod904'), start(b, 'prod907')]);      // two slow new products…
  for (const page of [a, b]) {                                        // …take both fetch slots
    await expect(page.locator('#progressLabel')).toHaveText(/^Fetching prices/, { timeout: 30_000 });
  }
  await start(c, 'prod905');
  await expect(c.locator('#progressLabel')).toHaveText('Busy with other searches — yours starts in a moment…');
  const cachedStart = Date.now();
  const cached = await search(d, 'iPhone 17');
  expect(Date.now() - cachedStart).toBeLessThan(2000);
  expect(cached.cached).toBe(true);
  await expect(a.locator('#searchBtn')).toHaveText('Searching…');      // still fetching meanwhile
  for (const page of [b, c, a]) {
    await expect(page.locator('#searchBtn')).toHaveText('Search', { timeout: 60_000 });
    expect((await state(page)).rows).toHaveLength(30);
    expect((await state(page)).status).toBe('');
  }
  for (const page of [a, b, c, d]) await page.context().close();
});

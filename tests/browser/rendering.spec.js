// How results appear while they stream in (first row at once, then a redraw every
// half second, the final table the moment the search ends), and how cached results
// show their age. Time is controlled with Playwright's clock.
const { test, expect, openPaused } = require('./support/fixtures');
const { rows } = require('./support/data');
const { footer } = require('./support/page-model');

const ROWS = Array.from({ length: 50 }, (_, i) => ({ country: `Country ${i}`, flag: '🏳', available: true, currency: 'USD',
  symbol: '$', localPrice: 900 + (i * 7) % 300, localPriceFormatted: `$${900 + (i * 7) % 300}`, usdPrice: 900 + (i * 7) % 300,
  url: 'https://www.apple.com/' }));

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.__draws = [];
    addEventListener('DOMContentLoaded', () => {           // record every redraw of the results
      const draw = window.renderAll;
      window.renderAll = function (...args) {
        draw.apply(this, args);
        window.__draws.push({ t: performance.now(), rows: document.querySelectorAll('#results tbody tr[data-key]').length });
      };
    });
  });
  await openPaused(page);
});

/** Stream `n` results `every` ms apart, then the end of the search `doneAfter` ms later. Returns arrivals and redraws. */
async function streamResults(page, server, { n = 50, every = 60, doneAfter = 300 } = {}) {
  const stream = await server.search('MacBook Air');
  await page.evaluate(() => { window.__draws = []; });
  const t0 = await page.evaluate(() => performance.now());
  await stream.searching();
  await stream.meta({ total: n, rates: { USD: 1 } });
  const arrivals = [];
  for (let i = 0; i < n; i++) {
    arrivals.push(await page.evaluate(() => performance.now()) - t0);
    await stream.results([ROWS[i]]);
    await page.clock.runFor(every);          // 0: back to back, as a cached answer arrives
  }
  await page.clock.runFor(doneAfter);
  const finished = await page.evaluate(() => performance.now()) - t0;
  await stream.done();
  const draws = (await page.evaluate(() => window.__draws)).map(d => ({ t: d.t - t0, rows: d.rows }));
  return { arrivals, finished, draws, during: draws.filter(d => d.t < finished), after: draws.filter(d => d.t >= finished) };
}

test.describe('streaming results', () => {
  test('a fast search: first row at once, then a redraw every half second, the full table at the end', async ({ page, server }) => {
    const r = await streamResults(page, server);
    expect(r.during[0]).toMatchObject({ t: 0 });
    expect(r.during[0].rows).toBeGreaterThanOrEqual(1);
    const gaps = r.during.slice(1).map((d, i) => d.t - r.during[i].t);
    expect(gaps.length).toBeGreaterThanOrEqual(4);
    for (const gap of gaps) expect(gap).toBeGreaterThanOrEqual(480), expect(gap).toBeLessThanOrEqual(560);
    expect(r.during.every((d, i) => i === 0 || d.rows > r.during[i - 1].rows)).toBe(true);
    for (const arrival of r.arrivals) {                                  // nothing waits much more than half a second
      const shown = r.draws.find(d => d.t >= arrival);
      expect(shown.t - arrival).toBeLessThanOrEqual(560);
    }
    expect(r.after).toEqual([{ t: r.finished, rows: 50 }]);
  });

  test('a slow trickle: every result is drawn as it arrives', async ({ page, server }) => {
    const r = await streamResults(page, server, { n: 5, every: 800, doneAfter: 200 });
    expect(r.during.map(d => d.t)).toEqual(r.arrivals);
  });

  test('a cached answer (everything at once): two redraws, the first row and the full table', async ({ page, server }) => {
    const r = await streamResults(page, server, { n: 50, every: 0, doneAfter: 0 });
    expect(r.draws).toEqual([{ t: 0, rows: 1 }, { t: 0, rows: 50 }]);
  });

  test('a burst, then one slow store: everything that arrived is shown within half a second', async ({ page, server }) => {
    const r = await streamResults(page, server, { n: 49, every: 0, doneAfter: 1500 });
    expect(r.draws[0]).toEqual({ t: 0, rows: 1 });
    expect(r.draws.find(d => d.rows === 49).t).toBeLessThanOrEqual(500);
  });

  test('a search that ends during a wait is drawn at once, with no late extra redraw', async ({ page, server }) => {
    const r = await streamResults(page, server, { n: 12, every: 120, doneAfter: 0 });
    expect(r.after).toEqual([{ t: r.finished, rows: 12 }]);
    await page.clock.runFor(1000);
    expect(await page.evaluate(() => window.__draws.length)).toBe(r.draws.length);
    expect(await page.evaluate(() => renderTimer)).toBe(null); // eslint-disable-line no-undef -- the page's own variable
  });

  test('a new search cancels the redraw booked for the old one and draws its own first row at once', async ({ page, server }) => {
    const old = await server.search('MacBook Air');
    await old.meta({ total: 50 });
    await old.results(ROWS.slice(0, 6));
    await page.clock.runFor(100);
    const fresh = await server.search('iPhone 17');
    expect(await page.evaluate(() => renderTimer)).toBe(null); // eslint-disable-line no-undef
    await page.clock.runFor(700);
    await expect(page.locator('#results tbody tr[data-key]')).toHaveCount(0);
    await expect(page.locator('#results tbody[data-skeleton]')).toHaveCount(1);           // loading rows
    await page.evaluate(() => { window.__draws = []; });
    await fresh.meta({ product: 'iPhone 17', total: 50 });
    await fresh.results(ROWS.slice(0, 1));
    await page.clock.runFor(0);
    expect(await page.evaluate(() => window.__draws.length)).toBe(1);
  });

  test('going Back to the start page cancels a booked redraw', async ({ page, server }) => {
    const stream = await server.search('MacBook Air');
    await stream.meta({ total: 50 });
    await stream.results(ROWS.slice(0, 6));
    await page.goBack();
    await page.clock.runFor(700);
    expect(await page.evaluate(() => renderTimer === null && document.getElementById('results').innerHTML === '')).toBe(true); // eslint-disable-line no-undef
    await expect(page.locator('#summary')).toBeHidden();
  });

  test('typing a country filter mid-search applies straight away', async ({ page, server }) => {
    const stream = await server.search('MacBook Air');
    await stream.meta({ total: 50 });
    await stream.results(ROWS.slice(0, 20));
    await page.fill('#filterInput', 'Country 1');
    const shown = await page.locator('#results tbody tr[data-key]').evaluateAll(trs => trs.map(t => t.dataset.key));
    expect(shown.length).toBeGreaterThan(0);
    expect(shown.every(k => k.startsWith('Country 1'))).toBe(true);
  });
});

test.describe('cached results show their age', () => {
  const badge = page => page.evaluate(() => {
    const b = document.getElementById('cacheBadge');
    return { visible: b.classList.contains('visible'), text: b.textContent.trim().replace(/\s+/g, ' '), title: b.title };
  });
  const search = async (server, meta, done = {}) => server.searchAndFinish('MacBook Air', rows(), { meta, done });

  test('2 h 5 min old: badge, tooltip and footer; the age keeps counting', async ({ page, server }) => {
    await search(server, { cached: true, ageSeconds: 7500, expiresInSeconds: 14_100 }, { cached: true });
    const b = await badge(page);
    expect(b).toMatchObject({ visible: true, text: '⚡ cached · prices from 2 h 5 min ago' });
    expect(b.title).toMatch(/again from Apple in 3 h 5[45] min/);
    expect(await footer(page)).toMatch(/ · Updated 2 h 5 min ago$/);
    await page.clock.runFor(10 * 60_000);
    await page.selectOption('#sortSelect', 'usd-desc');                          // any redraw
    await expect.poll(() => footer(page)).toMatch(/ · Updated 2 h 15 min ago$/);
  });

  for (const [age, badgeText, footerText] of [
    [0, 'prices from under a minute ago', 'Updated just now'],
    [30, 'prices from under a minute ago', 'Updated just now'],
    [720, 'prices from 12 min ago', 'Updated 12 min ago'],
    [3600, 'prices from 1 h ago', 'Updated 1 h ago'],
    [21_599, 'prices from 5 h 59 min ago', 'Updated 5 h 59 min ago'],
  ]) {
    test(`${age} s old → "${badgeText}"`, async ({ page, server }) => {
      await search(server, { cached: true, ageSeconds: age, expiresInSeconds: 21_600 - age }, { cached: true });
      expect(await badge(page)).toMatchObject({ visible: true, text: `⚡ cached · ${badgeText}` });
      expect(await footer(page)).toMatch(new RegExp(` · ${footerText}$`));
    });
  }

  for (const [label, meta, text] of [
    ['an older API that sends no age', { cached: true }, '⚡ cached · refreshes in 5m'],
    ['nonsense values', { cached: true, ageSeconds: 'abc', expiresInSeconds: null }, '⚡ cached · refreshes in 5m'],
    ['negative values', { cached: true, ageSeconds: -50, expiresInSeconds: -1 }, '⚡ cached · prices from under a minute ago'],
  ]) {
    test(`${label} do not break the badge`, async ({ page, server }) => {
      await search(server, meta, { cached: true });
      expect(await badge(page)).toMatchObject({ visible: true, text });
      await expect(page.locator('#results tbody tr[data-key]')).toHaveCount(30);
    });
  }

  test('a fresh search has no badge, and clears one left by a cached search', async ({ page, server }) => {
    await search(server, { cached: true, ageSeconds: 7500, expiresInSeconds: 14_100 }, { cached: true });
    await search(server, {});
    expect((await badge(page)).visible).toBe(false);
    expect(await footer(page)).toMatch(/ · Updated just now$/);
  });
});

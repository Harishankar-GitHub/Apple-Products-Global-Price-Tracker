// Table and chart: side by side, one at a time, on narrow screens and phones; what the chart shows.
const { test, expect } = require('./support/fixtures');
const { rows, usdOf } = require('./support/data');
const { tableRows, sidewaysScroll } = require('./support/page-model');

const layout = page => page.evaluate(() => {
  const visible = el => getComputedStyle(el).display !== 'none';
  const table = document.getElementById('results'), chart = document.getElementById('chartView');
  const t = table.getBoundingClientRect(), c = chart.getBoundingClientRect();
  const wrap = document.querySelector('.table-wrap'), card = document.querySelector('.chart-card');
  const currency = document.querySelector('#results thead th.hide-split');
  return {
    split: document.getElementById('views').classList.contains('split'),
    table: visible(table), chart: visible(chart),
    tableLeft: t.left, tableRight: t.right, chartLeft: c.left, chartRight: c.right, tableTop: t.top, chartTop: c.top,
    tableWidth: t.width, chartWidth: c.width, viewport: innerWidth,
    wrapHeight: wrap ? wrap.getBoundingClientRect().height : 0, cardHeight: card ? card.getBoundingClientRect().height : 0,
    wrapOverflow: wrap ? wrap.scrollWidth - wrap.clientWidth : 0,
    pressed: [...document.querySelectorAll('#viewToggle .seg-btn[aria-pressed="true"]')].map(b => b.dataset.view),
    bothButton: visible(document.querySelector('#viewToggle [data-view="both"]')),
    currencyColumn: currency ? visible(currency) : null,
  };
});

const chartRows = page => page.evaluate(() => [...document.querySelectorAll('.chart-row')].map(r => {
  const bar = r.querySelector('.chart-bar');
  return { name: r.querySelector('.chart-name').textContent, cls: bar.className, left: parseFloat(bar.style.left),
    width: parseFloat(bar.style.width), axis: parseFloat(r.querySelector('.chart-axis').style.left),
    delta: r.querySelector('.chart-delta').textContent, home: r.classList.contains('is-home'), tip: r.title };
}));

test.describe('desktop', () => {
  test.beforeEach(async ({ page, server }) => {
    await page.goto('/');
    await server.searchAndFinish('MacBook Air');
  });

  test('side by side by default: table left, chart right, same countries in the same order', async ({ page }) => {
    const l = await layout(page);
    expect(l).toMatchObject({ split: true, table: true, chart: true, pressed: ['both'], currencyColumn: false });
    expect(l.tableRight).toBeLessThanOrEqual(l.chartLeft);
    expect(Math.abs(l.tableTop - l.chartTop)).toBeLessThan(2);
    expect(l.chartRight).toBeLessThanOrEqual(l.viewport);
    expect(l.wrapOverflow).toBeLessThanOrEqual(1);
    expect(await sidewaysScroll(page)).toBeLessThanOrEqual(0);
    expect(l.wrapHeight).toBeGreaterThan(300);
    expect(Math.abs(l.wrapHeight - l.cardHeight)).toBeLessThan(40);   // both capped, each scrolls on its own
    expect(await page.evaluate(() => { const r = document.querySelector('.chart-rows'); return r.scrollHeight > r.clientHeight; })).toBe(true);
    expect((await chartRows(page)).map(r => r.name)).toEqual((await tableRows(page)).map(r => r.country));
  });

  for (const [view, expected] of [['table', { table: true, chart: false, currencyColumn: true }], ['chart', { table: false, chart: true }]]) {
    test(`${view} only, full width`, async ({ page }) => {
      await page.click(`#viewToggle [data-view="${view}"]`);
      const l = await layout(page);
      expect(l).toMatchObject({ split: false, pressed: [view], ...expected });
      expect(view === 'table' ? l.tableWidth : l.chartWidth).toBeGreaterThan(1000);
    });
  }

  test('a narrow window falls back to the table; widening restores side by side', async ({ page }) => {
    await page.setViewportSize({ width: 820, height: 900 });
    await expect.poll(async () => (await layout(page)).split).toBe(false);
    expect(await layout(page)).toMatchObject({ table: true, chart: false, bothButton: false, pressed: ['table'] });
    expect(await sidewaysScroll(page)).toBeLessThanOrEqual(0);
    await page.setViewportSize({ width: 1280, height: 900 });
    await expect.poll(async () => (await layout(page)).split).toBe(true);
    expect(await layout(page)).toMatchObject({ table: true, chart: true, bothButton: true, pressed: ['both'] });
  });

  test('sorting and filtering apply to both', async ({ page }) => {
    await page.selectOption('#sortSelect', 'usd-desc');
    await page.fill('#filterInput', 'an');
    await expect.poll(async () => (await chartRows(page)).map(r => r.name)).toEqual((await tableRows(page)).map(r => r.country));
    const names = (await chartRows(page)).map(r => r.name);
    expect(names.length).toBeGreaterThan(3);
    expect(names.every(n => /an/i.test(n))).toBe(true);
  });

  test('the chart shows the extra cost over the cheapest country', async ({ page }) => {
    await page.click('#viewToggle [data-view="chart"]');
    await expect(page.locator('.chart-title')).toHaveText('Extra cost vs the cheapest (Japan)');
    const bars = await chartRows(page);
    expect(bars).toHaveLength(30);
    const by = name => bars.find(b => b.name === name);
    expect(by('Japan')).toMatchObject({ delta: 'Cheapest' });
    expect(by('Japan').cls).toMatch(/same/);
    expect(bars.every(b => b.left === 0 && b.axis === 0)).toBe(true);           // every bar starts at the baseline
    await expect(page.locator('.chart-legend')).toHaveCount(0);
    const over = c => (usdOf(c) - usdOf('Japan')) / usdOf('Japan');
    expect(by('Brazil').width).toBeCloseTo(100, 1);                             // the largest difference fills the width
    expect(by('Ireland').width / by('Brazil').width).toBeCloseTo(over('Ireland') / over('Brazil'), 2);
    expect(by('Brazil').delta).toMatch(/^\+€[\d,.]+ \(\+101%\)$/);
    expect(by('Ireland').home).toBe(true);
    await expect(page.locator('.chart-row.is-home .badge-home')).toHaveCount(1);
    expect(by('Japan').tip).toMatch(/^Japan: €/);
    await page.click('#regionChips [data-region="Asia Pacific"]');
    await expect(page.locator('.chart-row')).toHaveCount(12);
  });

  test('the chosen view is remembered', async ({ page, server }) => {
    await page.click('#viewToggle [data-view="chart"]');
    await page.reload();
    await server.searchAndFinish('MacBook Air');
    expect(await layout(page)).toMatchObject({ chart: true, table: false, pressed: ['chart'] });
  });

  test('home country without a price: the chart is unchanged and nothing is marked Home', async ({ page, server }) => {
    await server.searchAndFinish('MacBook Air', rows({ noPrice: ['Ireland'] }));
    await page.click('#viewToggle [data-view="chart"]');
    await expect(page.locator('.chart-title')).toHaveText('Extra cost vs the cheapest (Japan)');
    await expect(page.locator('.chart-row.is-home')).toHaveCount(0);
  });
});

test.describe('phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });

  test('table and chart fit the screen without sideways scrolling', async ({ page, server }) => {
    await page.goto('/');
    await server.searchAndFinish('MacBook Air');
    expect(await sidewaysScroll(page)).toBeLessThanOrEqual(0);
    const table = await page.evaluate(() => {
      const wrap = document.querySelector('.table-wrap');
      return { scroll: wrap.scrollWidth - wrap.clientWidth, link: document.querySelector('.store-link').getBoundingClientRect().right, width: innerWidth };
    });
    expect(table.scroll).toBeLessThanOrEqual(1);
    expect(table.link).toBeLessThanOrEqual(table.width);                        // the store link is on screen
    await page.click('#viewToggle [data-view="chart"]');
    await expect(page.locator('.chart-row').first()).toBeVisible();
    expect(await sidewaysScroll(page)).toBeLessThanOrEqual(0);
  });
});

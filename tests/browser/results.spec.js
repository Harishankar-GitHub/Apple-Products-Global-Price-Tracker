// The results: ranking, differences from the cheapest, sorting and filtering,
// home country and display currency, pins, missing exchange rates and the summary.
const { test, expect } = require('./support/fixtures');
const { RATES, rows, usdOf, ratesWithout } = require('./support/data');
const { tableRows, row, summary, footer, amount, percent } = require('./support/page-model');

const EUROPE = ['United Kingdom', 'Germany', 'France', 'Netherlands', 'Spain', 'Italy', 'Ireland', 'Sweden', 'Norway',
  'Denmark', 'Poland', 'Turkey', 'Switzerland'];
const countries = async page => (await tableRows(page)).map(r => r.country);

test.describe('ranking (home Ireland, prices in EUR)', () => {
  test.beforeEach(async ({ page, server }) => {
    await page.goto('/');
    await server.searchAndFinish('MacBook Air');
  });

  test('home and currency are guessed from the browser', async ({ page }) => {
    await expect(page.locator('#homeSelect')).toHaveValue('Ireland');
    await expect(page.locator('#currencySelect option').first()).toHaveText('EUR (home)');
  });

  test('cheapest first, unavailable countries hidden', async ({ page }) => {
    const shown = await countries(page);
    expect(shown).toHaveLength(30);
    expect(shown.slice(0, 3)).toEqual(['Japan', 'Hong Kong', 'United States']);
  });

  test('the cheapest country has the badge and gold medal and no difference line', async ({ page }) => {
    const japan = await row(page, 'Japan');
    expect(japan).toMatchObject({ cheapest: true, medal: '1', diff: null });
    expect(japan.converted).toMatch(/^≈ €/);
    expect(amount(japan.converted)).toBeCloseTo(usdOf('Japan') * RATES.EUR, 0);
  });

  test('every difference is measured against the cheapest, in money and percent', async ({ page }) => {
    const cheapest = usdOf('Japan');
    for (const country of ['Brazil', 'Germany', 'Ireland', 'Hong Kong']) {
      const r = await row(page, country);
      const extra = usdOf(country) - cheapest;
      expect(r.diff).toMatch(/^€.* more than the cheapest \(\+[\d.]+%\)$/);
      expect(amount(r.diff)).toBeCloseTo(extra * RATES.EUR, 0);
      expect(percent(r.diff)).toBeCloseTo(extra / cheapest * 100, 0);   // Brazil +101%, not 50%
    }
  });

  test('difference colours: small gap green, middle amber, large red', async ({ page }) => {
    expect((await row(page, 'Hong Kong')).diffClass).toMatch(/cheap/);
    expect((await row(page, 'India')).diffClass).toMatch(/mid/);
    expect((await row(page, 'Brazil')).diffClass).toMatch(/pricey/);
  });

  test('home row: Home badge, own currency without a repeated "≈" line', async ({ page }) => {
    const ireland = await row(page, 'Ireland');
    expect(ireland).toMatchObject({ home: true, converted: null });
    expect(amount(ireland.local)).toBeCloseTo(usdOf('Ireland') * RATES.EUR, 0);
  });

  test('prices are compared as listed: nothing is added for sales tax', async ({ page }) => {
    expect(amount((await row(page, 'United States')).converted)).toBeCloseTo(999 * RATES.EUR, 0);
    await expect(page.locator('#taxSelect, .tax-note')).toHaveCount(0);
    expect(await page.evaluate(() => document.body.innerText)).not.toMatch(/\btax\b|VAT|GST/i);
  });

  test('summary', async ({ page }) => {
    const s = await summary(page);
    expect(s.found).toBe('30');
    expect(s.cheapest).toMatch(/^🇯🇵 Japan — €/);
    expect(s.priciest).toMatch(/^🇧🇷 Brazil — €/);
    expect(s.home).toMatch(/^🇮🇪 Ireland — €/);
  });

  for (const [sort, first] of [['usd-desc', 'Brazil'], ['country-asc', 'Australia'], ['country-desc', 'Vietnam'], ['usd-asc', 'Japan']]) {
    test(`sorted ${sort}: ${first} first, the badge, medal and ranks stay with the real cheapest`, async ({ page }) => {
      await page.selectOption('#sortSelect', sort);
      await expect.poll(async () => (await countries(page))[0]).toBe(first);
      const all = await tableRows(page);
      expect(all.filter(r => r.cheapest).map(r => r.country)).toEqual(['Japan']);
      expect(all.filter(r => r.medal === '1').map(r => r.country)).toEqual(['Japan']);
      expect(all.find(r => r.country === 'Brazil').rank).toBe('30');
      expect(Math.max(...all.map(r => r.bar))).toBeLessThanOrEqual(100);
    });
  }

  test('filtered to one country: no badge, real rank and difference kept', async ({ page }) => {
    await page.fill('#filterInput', 'ire');
    await expect.poll(() => countries(page)).toEqual(['Ireland']);
    const ireland = await row(page, 'Ireland');
    expect(ireland.cheapest).toBe(false);
    expect(Number(ireland.rank)).toBeGreaterThan(3);
    expect(ireland.diff).toMatch(/more than the cheapest/);
    expect(await footer(page)).toMatch(/^Showing 1 of 30 prices · 5 countries without a price/);
  });

  for (const [region, expected] of [
    ['Europe', EUROPE],
    ['Americas', ['Brazil', 'Canada', 'Mexico', 'United States']],
  ]) {
    test(`region filter: ${region}`, async ({ page }) => {
      await page.click(`#regionChips [data-region="${region}"]`);
      await expect.poll(async () => (await countries(page)).sort()).toEqual([...expected].sort());
      await expect(page.locator(`#regionChips [data-region="${region}"]`)).toHaveAttribute('aria-pressed', 'true');
      expect((await tableRows(page)).some(r => r.cheapest)).toBe(false);
    });
  }

  test('region filter with unavailable countries shown', async ({ page }) => {
    await page.check('#showUnavail');
    await page.click('#regionChips [data-region="Middle East & Africa"]');
    await expect.poll(async () => (await countries(page)).sort()).toEqual(['Israel', 'Kuwait', 'South Africa', 'United Arab Emirates']);
  });

  test('"Show unavailable" lists the countries without a price, after the rest', async ({ page }) => {
    await page.check('#showUnavail');
    await expect.poll(async () => (await tableRows(page)).length).toBe(35);
    const all = await tableRows(page);
    expect(all.slice(30).every(r => r.unavailable === 'Price not found')).toBe(true);
    expect(await footer(page)).toMatch(/^30 prices found · 5 countries without a price/);
  });

  test('pins: pinned countries on top, by price, with their real rank; they persist', async ({ page, server }) => {
    await page.click('[data-pin="Germany"]');
    await page.click('[data-pin="Australia"]');
    await expect.poll(async () => (await countries(page)).slice(0, 3)).toEqual(['Australia', 'Germany', 'Japan']);
    const top = await tableRows(page);
    expect(top[0].pinned && top[1].pinned).toBe(true);
    expect(Number(top[1].rank)).toBeGreaterThan(3);
    expect(top[2].cheapest).toBe(true);
    await expect(page.locator('[data-pin="Germany"]')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('[data-pin="Germany"]')).toHaveAttribute('aria-label', 'Unpin Germany');
    await page.selectOption('#sortSelect', 'usd-desc');
    await expect.poll(async () => (await countries(page)).slice(0, 3)).toEqual(['Germany', 'Australia', 'Brazil']);
    await page.selectOption('#sortSelect', 'usd-asc');
    await page.reload();
    await server.searchAndFinish('MacBook Air');
    expect((await tableRows(page)).map(r => r.pinned).slice(0, 3)).toEqual([true, true, false]);
  });

  test('changing home country and currency; both are remembered', async ({ page }) => {
    await page.selectOption('#homeSelect', 'India');
    await expect.poll(async () => (await row(page, 'India')).home).toBe(true);
    expect((await row(page, 'Ireland')).home).toBe(false);
    expect((await row(page, 'Hong Kong')).diff).toMatch(/^₹.* more than the cheapest/);
    await expect(page.locator('#currencySelect option').first()).toHaveText('INR (home)');
    await page.selectOption('#currencySelect', 'GBP');
    await expect.poll(async () => (await row(page, 'Japan')).converted).toMatch(/£/);
    expect(amount((await row(page, 'Japan')).converted)).toBeCloseTo(usdOf('Japan') * RATES.GBP, 0);
    await page.reload();
    await expect(page.locator('#homeSelect')).toHaveValue('India');
    await expect(page.locator('#currencySelect')).toHaveValue('GBP');
  });
});

test.describe('exchange rates', () => {
  test.beforeEach(async ({ page }) => { await page.goto('/'); });

  test('an API without a rates table: rates are worked out from the rows', async ({ page, server }) => {
    await server.searchAndFinish('MacBook Air', rows(), { meta: { rates: undefined } });
    expect(amount((await row(page, 'Japan')).converted)).toBeCloseTo(usdOf('Japan') * RATES.EUR, 0);
  });

  test('a display currency without a rate falls back to USD and says so', async ({ page, server }) => {
    await server.searchAndFinish('MacBook Air', rows(), { meta: { rates: undefined } });
    await page.selectOption('#currencySelect', 'KWD');
    await expect.poll(async () => (await row(page, 'Japan')).converted).toMatch(/\$/);
    expect((await summary(page)).note).toMatch(/No exchange rate for KWD/);
  });

  test('one country without a rate: listed with its own price, not ranked, explained', async ({ page, server }) => {
    await server.searchAndFinish('MacBook Air', rows({ usd: { India: null } }), { meta: { rates: ratesWithout('INR') } });
    const all = await tableRows(page);
    const india = all.find(r => r.country === 'India');
    expect(india).toMatchObject({ rank: '—', medal: null, cheapest: false, bar: 0 });
    expect(india.local).toMatch(/^₹/);
    expect(india.converted).toBe('No exchange rate');
    expect(all.at(-1).country).toBe('India');                        // after every converted price
    expect(all.filter(r => r.cheapest).map(r => r.country)).toEqual(['Japan']);
    const s = await summary(page);
    expect(s.found).toBe('30');
    expect(s.note).toBe('No exchange rate for India, so it is not ranked.');
    expect(await footer(page)).toMatch(/^30 prices found · 1 without an exchange rate \(not ranked\) · 5 countries without a price/);
    expect(await page.evaluate(() => document.body.innerText)).not.toMatch(/[$€]0\.00/);
    await page.selectOption('#sortSelect', 'usd-desc');
    await expect.poll(async () => (await countries(page))[0]).toBe('Brazil');
    expect((await countries(page)).at(-1)).toBe('India');
    await page.fill('#filterInput', 'ind');
    await expect.poll(() => footer(page)).toMatch(/^Showing 1 of 30 prices · 1 without an exchange rate/);
  });

  test('home country without a rate: its price as listed, not "no price"', async ({ page, server }) => {
    await server.searchAndFinish('MacBook Air', rows({ usd: { India: null } }), { meta: { rates: ratesWithout('INR') } });
    await page.selectOption('#homeSelect', 'India');
    await expect.poll(async () => (await summary(page)).home).toMatch(/^🇮🇳 India — ₹[\d,]+ · no exchange rate$/);
  });

  test('no rates at all: every price listed, nothing ranked, the reason given', async ({ page, server }) => {
    const unconverted = Object.fromEntries(rows().filter(r => r.available).map(r => [r.country, null]));
    await server.searchAndFinish('MacBook Air', rows({ usd: unconverted }), { meta: { rates: {} } });
    const all = await tableRows(page);
    expect(all).toHaveLength(30);
    expect(all.some(r => r.cheapest || r.medal)).toBe(false);
    const s = await summary(page);
    expect(s).toMatchObject({ found: '30', cheapest: '—', priciest: '—' });
    expect(s.note).toMatch(/Exchange rates are unavailable right now, so prices can't be compared/);
    await expect(page.locator('#chartView')).toBeHidden();
    await expect(page.locator('.no-prices')).toHaveCount(0);
    await page.fill('#filterInput', 'zzz');
    await expect(page.locator('.no-prices')).toHaveCount(0);
  });

  for (const [label, usd] of [['0', 0], ['negative', -5], ['missing', undefined]]) {
    test(`a conversion that is ${label} counts as no rate (never "$0.00", never cheapest)`, async ({ page, server }) => {
      await server.searchAndFinish('MacBook Air', rows({ usd: { India: usd } }));
      const all = await tableRows(page);
      expect(all.filter(r => r.cheapest).map(r => r.country)).toEqual(['Japan']);
      expect(all.find(r => r.country === 'India')).toMatchObject({ rank: '—', converted: 'No exchange rate' });
      expect((await summary(page)).found).toBe('30');
    });
  }
});

test.describe('home country without a price', () => {
  test('differences still against the cheapest; the summary says so', async ({ page, server }) => {
    await page.goto('/');
    await server.searchAndFinish('MacBook Air', rows({ noPrice: ['Ireland'] }));
    expect((await row(page, 'Japan')).diff).toBe(null);
    expect((await row(page, 'Brazil')).diff).toMatch(/^€.* more than the cheapest \(\+/);
    expect(await summary(page)).toMatchObject({ home: 'Ireland — no price', note: '' });
  });
});

test.describe('no country returned a price', () => {
  const none = ['United States', 'Japan', 'Ireland', 'India', 'United Kingdom'].map((country, i) => ({
    country, flag: '🏳', available: false, reason: i % 2 ? 'Not available in this country' : 'Price not found', url: 'https://www.apple.com/' }));
  const message = /^No prices found for Mac mini in any country\./;
  const panelText = page => page.locator('#results').innerText();

  test.beforeEach(async ({ page, server }) => {
    await page.goto('/');
    await server.searchAndFinish('Mac mini', none);
  });

  test('one clear message instead of an empty table and chart', async ({ page }) => {
    expect(await panelText(page)).toMatch(message);
    expect(await panelText(page)).toMatch(/Show unavailable/);
    await expect(page.locator('#chartView')).toBeHidden();
    await expect(page.locator('#views')).not.toHaveClass(/split/);
    expect(await summary(page)).toMatchObject({ found: '0', cheapest: '—' });
  });

  test('"Show unavailable" lists what each country returned; filtering them away brings the message back', async ({ page }) => {
    await page.check('#showUnavail');
    await expect(page.locator('#results tbody tr[data-key]')).toHaveCount(5);
    expect((await tableRows(page)).map(r => r.unavailable).sort()).toEqual(
      ['Not available in this country', 'Not available in this country', 'Price not found', 'Price not found', 'Price not found']);
    await page.fill('#filterInput', 'zzz');
    await expect.poll(() => panelText(page)).toMatch(message);
    await page.fill('#filterInput', '');
    await page.uncheck('#showUnavail');
    await expect.poll(() => panelText(page)).toMatch(message);
  });

  test('chart-only view shows the message too', async ({ page }) => {
    await page.click('#viewToggle [data-view="chart"]');
    await expect.poll(() => panelText(page)).toMatch(message);
    await expect(page.locator('#chartView')).toBeHidden();
  });
});

test.describe('filters that match nothing', () => {
  test('say so, in the table and the chart', async ({ page, server }) => {
    await page.goto('/');
    await server.searchAndFinish('MacBook Air');
    await page.fill('#filterInput', 'zzz');
    await expect(page.locator('#results')).toHaveText('No countries match these filters.');
    await expect(page.locator('#chartView')).toHaveText('No prices to chart for these filters.');
    expect((await summary(page)).found).toBe('30');
  });
});

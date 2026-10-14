// What the page shows while a search runs: the wake-up ping, progress, the
// "waking up the server" message, waiting for a fetch slot, and errors.
// Time is controlled with Playwright's clock, so waits are exact and instant.
const { test, expect, openPaused } = require('./support/fixtures');
const { progress, tableRows, WAKE, fourSecondsLater, NOT_WAITING } = require('./support/page-model');
const ROWS = [['United States', '🇺🇸', 'USD', '$', 1, 999], ['Japan', '🇯🇵', 'JPY', '¥', 150, 969],
  ['Ireland', '🇮🇪', 'EUR', '€', 0.92, 1318], ['India', '🇮🇳', 'INR', '₹', 84, 1189]]
  .map(([country, flag, currency, symbol, rate, usd]) => ({ country, flag, available: true, currency, symbol,
    localPrice: Math.round(usd * rate), localPriceFormatted: symbol + Math.round(usd * rate), usdPrice: usd, url: 'https://www.apple.com/' }));
const seconds = s => Number(String(s).replace('s', ''));

test.describe('wake-up ping', () => {
  test('is sent once as soon as the page loads, and the page stays usable meanwhile', async ({ page, server, health }) => {
    health.mode = 'hang';
    const loaded = Date.now();
    await openPaused(page, '/');
    await expect.poll(() => health.pings.length).toBe(1);
    expect(health.pings[0]).toMatchObject({ method: 'GET', url: expect.stringMatching(/\/api\/health$/) });
    expect(health.pings[0].at - loaded).toBeLessThan(2000);
    expect((await progress(page)).shown).toBe(false);                // nothing shown while it is in flight
    await page.type('#productInput', 'mac');
    await expect(page.locator('#suggestList .suggest-item')).not.toHaveCount(0);
    const answered = page.waitForResponse('**/api/health');
    health.release();
    await answered;
    await server.search('MacBook Air');                              // the server answered, so a slow search
    await page.clock.runFor(2_000);                                  // is given the full 3 s before the message
    expect((await progress(page)).label).toBe('Resolving "MacBook Air"…');
    await page.clock.runFor(1_600);
    expect((await progress(page)).label).toBe(WAKE);
    await page.reload();
    await expect.poll(() => health.pings.length).toBe(2);
  });

  for (const [searchAt, stillWaiting] of [[88_500, true], [91_000, false]]) {
    test(`is given up after 90 seconds (search at ${searchAt / 1000} s)`, async ({ page, server, health }) => {
      health.mode = 'hang';
      await openPaused(page, '/');
      await page.clock.runFor(searchAt);
      await server.search('MacBook Air');
      await page.clock.runFor(1_600);
      // While the ping is unanswered the server is taken to be asleep, so the message comes at once;
      // once the ping is given up, a search waits the usual 3 s.
      expect((await progress(page)).label).toBe(stillWaiting ? WAKE : 'Resolving "MacBook Air"…');
    });
  }
});

test.describe('progress', () => {
  test('server awake: resolving, fetching, then real progress, never the wake-up message', async ({ page, server }) => {
    await openPaused(page, '/');
    await page.clock.runFor(500);
    const stream = await server.search('MacBook Air');
    let p = await progress(page);
    expect(p).toMatchObject({ shown: true, moving: true, label: 'Resolving "MacBook Air"…' });
    expect(p.animation).toMatch(/progressSlide/);
    expect(p.fillWidth / p.barWidth).toBeCloseTo(0.30, 1);           // a moving bar, not an empty track
    await page.clock.runFor(300);
    await stream.searching();
    for (let i = 0; i < 9; i++) {
      await page.clock.runFor(500);
      expect((await progress(page)).label).toBe('Resolving "MacBook Air" on apple.com…');
    }
    p = await progress(page);
    expect(p).toMatchObject({ moving: true, count: '', countHidden: null });
    await stream.meta({ total: 4, rates: { EUR: 0.92 } });
    expect((await progress(page))).toMatchObject({ label: 'Fetching prices for "MacBook Air"…', moving: true });
    await stream.results(ROWS.slice(0, 1));
    p = await progress(page);
    expect(p).toMatchObject({ moving: false, width: '25%', count: '1 / 4', countHidden: null });
    expect(p.animation).not.toMatch(/progressSlide/);
    await stream.results(ROWS.slice(1));
    await stream.done();
    await page.clock.runFor(600);
    p = await progress(page);
    expect(p).toMatchObject({ shown: false, moving: false });
    await expect(page.locator('#results tbody tr[data-key]')).toHaveCount(4);
    await expect(page.locator('#searchBtn')).toHaveText('Search');
    expect(await fourSecondsLater(page)).toEqual(NOT_WAITING);
  });

  test('cached answer leaves no waiting state behind', async ({ page, server }) => {
    await openPaused(page, '/');
    const stream = await server.search('MacBook Air');
    await stream.complete(ROWS, { meta: { cached: true, ageSeconds: 600, expiresInSeconds: 21_000 }, done: { cached: true } });
    await page.clock.runFor(600);
    expect(await progress(page)).toMatchObject({ shown: false, moving: false, countHidden: null });
    expect(await tableRows(page)).toHaveLength(4);
    expect(await fourSecondsLater(page)).toEqual(NOT_WAITING);
  });
});

test.describe('waking up the server', () => {
  test('ping unanswered: the wait is explained with a seconds counter until the search replies', async ({ page, server, health }) => {
    health.mode = 'hang';
    await openPaused(page, '/');
    await page.clock.runFor(2_000);
    const stream = await server.search('MacBook Air');
    await page.clock.runFor(600);
    let p = await progress(page);
    expect(p).toMatchObject({ shown: true, label: WAKE, countHidden: 'true', moving: true });
    expect(p.count).toMatch(/^\d+s$/);
    const first = seconds(p.count);
    await page.clock.runFor(2_300);
    p = await progress(page);
    expect(seconds(p.count)).toBeGreaterThanOrEqual(first + 2);
    expect(await server.count()).toBe(1);                            // the search was sent straight away
    expect(await stream.url()).toMatch(/product=MacBook%20Air/);
    health.release();                                                // the ping answers, the search not yet
    await page.clock.runFor(400);
    expect((await progress(page)).label).toBe(WAKE);
    await stream.searching();
    p = await progress(page);
    expect(p).toMatchObject({ label: 'Resolving "MacBook Air" on apple.com…', count: '', countHidden: null });
    expect(await fourSecondsLater(page)).toEqual(NOT_WAITING);
    expect((await progress(page)).label).toBe('Resolving "MacBook Air" on apple.com…');
    await stream.complete(ROWS);
    await page.clock.runFor(600);
    expect((await progress(page)).shown).toBe(false);
    expect(await tableRows(page)).toHaveLength(4);
  });

  test('searching right after opening: too early to tell, then the message once the ping is 1.5 s late', async ({ page, server, health }) => {
    health.mode = 'hang';
    await openPaused(page, '/');
    await server.search('MacBook Air');
    await page.clock.runFor(500);
    expect((await progress(page)).label).toBe('Resolving "MacBook Air"…');
    await page.clock.runFor(1_500);
    const p = await progress(page);
    expect(p.label).toBe(WAKE);
    expect(seconds(p.count)).toBeLessThanOrEqual(3);
  });

  test('ping answered earlier but the search gets no reply: the message after 3 s', async ({ page, server }) => {
    await openPaused(page, '/');
    await page.clock.runFor(600);
    await server.search('MacBook Air');
    await page.clock.runFor(2_300);
    expect(await progress(page)).toMatchObject({ label: 'Resolving "MacBook Air"…', moving: true, count: '' });
    await page.clock.runFor(1_300);
    const p = await progress(page);
    expect(p.label).toBe(WAKE);
    expect([3, 4]).toContain(seconds(p.count));
  });

  for (const mode of [503, 'html', 'abort']) {
    test(`ping fails (${mode}): no error, the search still works, the message only after 3 s`, async ({ page, server, health }) => {
      health.mode = mode;
      await openPaused(page, '/');
      await page.clock.runFor(600);
      expect((await progress(page)).shown).toBe(false);
      await expect(page.locator('#status')).toHaveText('');
      const stream = await server.search('MacBook Air');
      await page.clock.runFor(1_200);
      expect((await progress(page)).label).toBe('Resolving "MacBook Air"…');
      await page.clock.runFor(2_400);
      expect((await progress(page)).label).toBe(WAKE);
      await stream.complete(ROWS);
      await expect(page.locator('#results tbody tr[data-key]')).toHaveCount(4);
    });
  }

  test('browser without fetch: no ping, and the message still appears after 3 s', async ({ page, server, health }) => {
    await page.addInitScript(() => { window.fetch = undefined; });
    await openPaused(page, '/');
    await server.search('MacBook Air');
    await page.clock.runFor(3_600);
    expect(health.pings).toHaveLength(0);
    expect((await progress(page)).label).toBe(WAKE);
  });

  test('shared link: awake server never shows the message', async ({ page, server, health }) => {
    await openPaused(page, '/?q=iPhone+17');
    const stream = await server.latest();
    await stream.searching('iPhone 17');
    for (let i = 0; i < 8; i++) {
      await page.clock.runFor(500);
      expect((await progress(page)).label).toBe('Resolving "iPhone 17" on apple.com…');
    }
    expect(health.pings).toHaveLength(1);
    expect(await server.count()).toBe(1);
  });

  test('shared link: sleeping server shows the message about 2 s after it opens', async ({ page, server, health }) => {
    health.mode = 'hang';
    await openPaused(page, '/?q=iPhone+17');
    await page.clock.runFor(2_100);
    const p = await progress(page);
    expect(p.label).toBe(WAKE);
    expect(p.count).toMatch(/^\d+s$/);
    expect(await server.count()).toBe(1);
  });

  test('a new search while waiting restarts the counter and cancels the first', async ({ page, server, health }) => {
    health.mode = 'hang';
    await openPaused(page, '/');
    await page.clock.runFor(1_700);
    const first = await server.search('MacBook Air');
    await page.clock.runFor(2_600);
    expect(seconds((await progress(page)).count)).toBeGreaterThanOrEqual(2);
    const second = await server.search('Mac mini');
    await page.clock.runFor(500);
    const p = await progress(page);
    expect(p.label).toBe(WAKE);
    expect(seconds(p.count)).toBeLessThanOrEqual(1);
    expect(await first.closed()).toBe(true);
    expect(await second.closed()).toBe(false);
    await first.searching('MacBook Air');                            // a late reply to the old search is ignored
    await second.searching('Mac mini');
    expect(await progress(page)).toMatchObject({ label: 'Resolving "Mac mini" on apple.com…', count: '' });
    expect(await fourSecondsLater(page)).toEqual(NOT_WAITING);
  });

  test('the search fails while waiting: error shown, waiting stopped, a new search works', async ({ page, server, health }) => {
    health.mode = 'hang';
    await openPaused(page, '/');
    await page.clock.runFor(1_700);
    let stream = await server.search('MacBook Air');
    await page.clock.runFor(700);
    expect((await progress(page)).label).toBe(WAKE);
    await stream.error();
    await expect(page.locator('#status')).toContainText('Could not reach the API');
    let p = await progress(page);
    expect(p).toMatchObject({ shown: false, moving: false, countHidden: null });
    await expect(page.locator('#searchBtn')).toHaveText('Search');
    expect(await fourSecondsLater(page)).toEqual(NOT_WAITING);
    stream = await server.search('MacBook Air');
    await stream.complete(ROWS);
    await expect(page.locator('#results tbody tr[data-key]')).toHaveCount(4);
    await expect(page.locator('#status')).toHaveText('');
  });

  test('going Back while waiting returns to the start page cleanly', async ({ page, server, health }) => {
    health.mode = 'hang';
    await openPaused(page, '/');
    await page.clock.runFor(1_700);
    await server.search('MacBook Air');
    await page.clock.runFor(700);
    await page.goBack();
    await page.clock.runFor(1_500);
    expect(await progress(page)).toMatchObject({ shown: false, count: '', countHidden: null });
    expect(await fourSecondsLater(page)).toEqual(NOT_WAITING);
  });

});

test.describe('reduced motion', () => {
  test.use({ contextOptions: { reducedMotion: 'reduce' } });

  test('a still bar instead of a sliding one', async ({ page, server, health }) => {
    health.mode = 'hang';
    await openPaused(page, '/');
    await page.clock.runFor(1_700);
    await server.search('MacBook Air');
    await page.clock.runFor(600);
    const p = await progress(page);
    expect(p.label).toBe(WAKE);
    expect(p.animation).toBe('none');
    expect(Math.abs(p.fillWidth - p.barWidth)).toBeLessThan(1);
  });
});

test.describe('waiting for a fetch slot', () => {
  test('busy: the message, then the search starts as usual', async ({ page, server }) => {
    await openPaused(page, '/');
    const stream = await server.search('MacBook Pro');
    await stream.searching('MacBook Pro');
    await stream.queued();
    expect(await progress(page)).toMatchObject({ shown: true, label: 'Busy with other searches — yours starts in a moment…' });
    await expect(page.locator('#searchBtn')).toBeDisabled();
    await page.clock.runFor(3_600);
    expect(await progress(page)).toMatchObject({ label: 'Busy with other searches — yours starts in a moment…', count: '' });
    await stream.meta({ product: 'MacBook Pro', total: 4 });
    expect((await progress(page)).label).toBe('Fetching prices for "MacBook Pro"…');
    await stream.results(ROWS);
    await stream.done({ product: 'MacBook Pro' });
    await expect(page.locator('#results tbody tr[data-key]')).toHaveCount(4);
    await expect(page.locator('#status')).toHaveText('');
  });

  test('no slot came free: the busy message and nothing left half-drawn', async ({ page, server }) => {
    await openPaused(page, '/');
    const stream = await server.search('iPad Air');
    await stream.searching('iPad Air');
    await stream.queued();
    await stream.error({ error: 'The service is busy fetching prices for other visitors. Please try again in a few seconds.',
      temporary: true, retryAfterSeconds: 10 });
    await expect(page.locator('#status')).toHaveText('⚠️ The service is busy fetching prices for other visitors. Please try again in a few seconds.');
    expect((await progress(page)).shown).toBe(false);
    await expect(page.locator('#searchBtn')).toBeEnabled();
    expect(await stream.closed()).toBe(true);
    await expect(page.locator('#results tbody tr[data-key]')).toHaveCount(0);
    await page.clock.runFor(400);                                    // the summary fades out
    await expect(page.locator('#summary')).toBeHidden();
  });
});

test.describe('connection problems', () => {
  test('lost mid-search: the rows that arrived stay, with a message', async ({ page, server }) => {
    await openPaused(page, '/');
    const stream = await server.search('MacBook Air');
    await stream.meta({ total: 35 });
    await stream.results(ROWS);
    await page.clock.runFor(600);
    await expect(page.locator('.results-footer')).toContainText('Loading more');
    await stream.error();
    await expect(page.locator('#status')).toContainText('Connection lost before all results arrived.');
    await expect(page.locator('#results tbody tr[data-key]')).toHaveCount(4);
    await expect(page.locator('.results-footer')).not.toContainText('Loading more');
  });

  test('a fetch that broke off: "try again" and the countries that did arrive', async ({ page, server }) => {
    await openPaused(page, '/');
    const stream = await server.search('iMac');
    await stream.searching('iMac');
    await stream.meta({ product: 'iMac', total: 50 });
    await stream.results(ROWS);
    await stream.error({ error: 'Something went wrong while fetching prices. Please try again in a few seconds.', temporary: true, retryAfterSeconds: 10 });
    await expect(page.locator('#status')).toHaveText('⚠️ Something went wrong while fetching prices. Please try again in a few seconds.');
    await expect(page.locator('#results tbody tr[data-key]')).toHaveCount(4);
    expect((await progress(page)).shown).toBe(false);
  });
});

test.describe('phone, dark mode', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2, colorScheme: 'dark' });

  test('the waiting message fits the screen', async ({ page, server, health }) => {
    health.mode = 'hang';
    await openPaused(page, '/');
    await page.clock.runFor(1_700);
    await server.search('MacBook Air');
    await page.clock.runFor(900);
    expect((await progress(page)).label).toBe(WAKE);
    const fit = await page.evaluate(() => ({ overflow: document.documentElement.scrollWidth - innerWidth,
      right: document.querySelector('.progress-header').getBoundingClientRect().right, width: innerWidth }));
    expect(fit.overflow).toBeLessThanOrEqual(0);
    expect(fit.right).toBeLessThanOrEqual(fit.width);
  });
});

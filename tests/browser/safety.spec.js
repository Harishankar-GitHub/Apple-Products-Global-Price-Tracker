// Untrusted text stays text, and the page copes with blocked or damaged saved settings.
const { test, expect, PREFS_KEY } = require('./support/fixtures');
const { rows } = require('./support/data');
const { tableRows } = require('./support/page-model');

test.describe('text from the address bar, the API and the product name is never run as HTML', () => {
  test('an error message echoing the query', async ({ page, server }) => {
    await page.goto('/?q=' + encodeURIComponent('<img src=x onerror=window.__xss=1>'));
    const stream = await server.latest();
    await stream.searching('<img src=x onerror=window.__xss=1>');
    await stream.error({ error: 'Could not find "<img src=x onerror=window.__xss=1>" on apple.com.' });
    await expect(page.locator('.error-msg')).toContainText('<img src=x');
    await expect(page.locator('.error-msg img')).toHaveCount(0);
    expect(await page.evaluate(() => window.__xss)).toBeUndefined();
    const saved = await page.evaluate(key => JSON.parse(localStorage.getItem(key) || '{}'), PREFS_KEY);
    expect((saved.recent || []).some(r => r.includes('<img'))).toBe(false);         // a failed search is not remembered
  });

  test('fields from the API and the product name, in the table, chart, summary and recent searches', async ({ page, server }) => {
    await page.goto('/');
    const evil = rows().slice(0, 3);
    evil[0].country = '<img src=x onerror=window.__xss=2>';
    evil[1].localPriceFormatted = '<b id=inj>1</b>';
    evil[2].url = 'javascript:window.__xss=3';
    await server.searchAndFinish('<svg onload=window.__xss=4>', evil, {
      meta: { product: '<svg onload=window.__xss=4>', substituted: true, matchedName: '<svg onload=window.__xss=5><b id=inj2>Bold</b>' } });
    await page.click('#viewToggle [data-view="chart"]');
    await page.click('#viewToggle [data-view="table"]');
    expect(await page.evaluate(() => ({
      xss: window.__xss,
      injected: !!document.getElementById('inj') || !!document.getElementById('inj2'),
      elements: document.querySelectorAll('#results img, #recentWrap svg, #summary svg, #matchNote svg, #matchNote b, #summaryProduct *').length,
      javascriptLinks: [...document.querySelectorAll('.store-link')].filter(a => a.href.startsWith('javascript')).length,
    }))).toEqual({ xss: undefined, injected: false, elements: 0, javascriptLinks: 0 });
    await expect(page.locator('#matchNote')).toContainText('<svg onload=window.__xss=5>');
  });

  test('the product name in the "no prices" message', async ({ page, server }) => {
    await page.goto('/');
    const none = rows().map(r => ({ country: r.country, flag: r.flag, available: false, reason: 'Price not found', url: r.url }));
    await server.searchAndFinish('<img src=x onerror=window.__y=1>', none, { meta: { slug: 'x' } });
    await expect(page.locator('#results')).toContainText('<img src=x');
    await expect(page.locator('#results img')).toHaveCount(0);
    expect(await page.evaluate(() => window.__y)).toBeUndefined();
  });
});

test.describe('storage blocked (private browsing and the like)', () => {
  test('everything still works for the visit', async ({ page, server }) => {
    await page.addInitScript(() => {
      Object.defineProperty(window, 'localStorage', { get() { throw new Error('blocked'); } });
    });
    await page.goto('/');
    await server.searchAndFinish('MacBook Air');
    await page.selectOption('#homeSelect', 'Japan');
    await page.click('[data-pin="Brazil"]');
    await expect.poll(async () => (await tableRows(page))[0].country).toBe('Brazil');
    expect((await tableRows(page)).find(r => r.country === 'Japan').home).toBe(true);
    expect(await tableRows(page)).toHaveLength(30);
  });
});

test.describe('damaged saved settings', () => {
  test.use({ savedPrefs: '{"home":"Atlantis","currency":"XXX","taxMode":"lol","pinned":"no","recent":[1,null,"ok"],"view":"3d"}' });

  test('fall back to defaults, and old keys are dropped on the next save', async ({ page, server }) => {
    await page.goto('/');
    await server.searchAndFinish('MacBook Air');
    await expect(page.locator('#homeSelect')).toHaveValue('Ireland');
    await expect(page.locator('#views')).toHaveClass(/split/);
    expect(await page.locator('#recentWrap [data-recent]').allTextContents()).toContain('ok');
    expect(await tableRows(page)).toHaveLength(30);
    await page.click('[data-pin="Japan"]');
    expect(await page.evaluate(key => Object.keys(JSON.parse(localStorage.getItem(key))).sort(), PREFS_KEY))
      .toEqual(['currency', 'home', 'pinned', 'recent', 'view']);
  });
});

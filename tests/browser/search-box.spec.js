// The search box: suggestions, recent searches, the ✕ clear button and the keyboard.
const { test, expect } = require('./support/fixtures');
const { rows } = require('./support/data');

const suggestions = page => page.locator('#suggestList .suggest-item').allTextContents();

test.beforeEach(async ({ page }) => {
  await page.goto('/');
});

test.describe('suggestions', () => {
  test('typing suggests matching products', async ({ page }) => {
    await page.type('#productInput', 'mac');
    await expect.poll(async () => (await suggestions(page)).length).toBeGreaterThanOrEqual(5);
    expect((await suggestions(page)).every(s => /mac/i.test(s))).toBe(true);
    await expect(page.locator('#productInput')).toHaveAttribute('aria-expanded', 'true');
  });

  test('words match in any order', async ({ page }) => {
    await page.type('#productInput', 'pro ipad');
    await expect.poll(() => suggestions(page)).toEqual(['iPad Pro']);
  });

  test('arrow keys move the highlight and Enter searches for it', async ({ page, server }) => {
    await page.type('#productInput', 'watch');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowDown');
    const active = page.locator('.suggest-item.active');
    await expect(active).toHaveText('Apple Watch Ultra 4');
    await expect(active).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('#productInput')).toHaveAttribute('aria-activedescendant', 'suggest-1');
    await page.keyboard.press('Enter');
    await expect(page.locator('#productInput')).toHaveValue('Apple Watch Ultra 4');
    expect(await server.count()).toBe(1);
    await expect(page.locator('#suggestList')).toBeHidden();
  });

  test('clicking a suggestion searches for it', async ({ page, server }) => {
    await page.type('#productInput', 'airp');
    await page.locator('#suggestList .suggest-item', { hasText: 'AirPods Pro' }).click();
    await expect(page.locator('#productInput')).toHaveValue('AirPods Pro');
    expect(await server.count()).toBe(1);
    expect(new URL(page.url()).searchParams.get('q')).toBe('AirPods Pro');
  });

  test('Escape closes them', async ({ page }) => {
    await page.type('#productInput', 'air');
    await page.keyboard.press('Escape');
    await expect(page.locator('#suggestList')).toBeHidden();
    await expect(page.locator('#productInput')).toHaveAttribute('aria-expanded', 'false');
  });

  test('unknown text: no suggestions, and Enter still searches', async ({ page, server }) => {
    await page.type('#productInput', 'zzzz');
    await expect(page.locator('#suggestList')).toBeHidden();
    await page.keyboard.press('Enter');
    expect(await server.count()).toBe(1);
  });
});

test.describe('recent searches', () => {
  test('newest first, no duplicates (any case), at most 6, remembered', async ({ page, server }) => {
    await expect(page.locator('#recentWrap')).toBeHidden();
    for (const product of ['MacBook Air', 'iPhone 17', 'Mac mini', 'iPad Pro', 'AirTag', 'iMac', 'macbook air']) {
      await server.searchAndFinish(product, rows());
    }
    const recent = () => page.locator('#recentWrap [data-recent]').allTextContents();
    expect(await recent()).toEqual(['macbook air', 'iMac', 'AirTag', 'iPad Pro', 'Mac mini', 'iPhone 17']);
    await page.reload();
    expect(await recent()).toHaveLength(6);
  });

  test('a product Apple did not recognise is not remembered', async ({ page, server }) => {
    const stream = await server.search('nonsense');
    await stream.searching('nonsense');
    await stream.error({ error: 'Could not find "nonsense" on apple.com.' });
    await expect(page.locator('#status')).toContainText('Could not find');
    await expect(page.locator('#recentWrap [data-recent]')).toHaveCount(0);
  });

  test('clicking one searches again; Clear forgets them', async ({ page, server }) => {
    await server.searchAndFinish('AirTag', rows());
    await server.searchAndFinish('iMac', rows());
    await page.click('#recentWrap [data-recent="AirTag"]');
    await expect(page.locator('#productInput')).toHaveValue('AirTag');
    expect(await server.count()).toBe(3);
    await page.click('#clearRecentBtn');
    await expect(page.locator('#recentWrap')).toBeHidden();
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('apgt:prefs:v1')).recent)).toEqual([]);
  });
});

test.describe('the ✕ clear button', () => {
  const look = page => page.evaluate(() => {
    const style = el => { const s = getComputedStyle(el), r = el.getBoundingClientRect();
      return { bg: s.backgroundColor, color: s.color, radius: s.borderTopLeftRadius, width: Math.round(r.width), height: Math.round(r.height), display: s.display }; };
    const button = document.getElementById('clearBtn');
    return { button: style(button), circle: style(button.querySelector('span') || button), search: style(document.getElementById('searchBtn')) };
  });
  const isBlue = rgb => { const [r, , b] = rgb.match(/\d+/g).map(Number); return b > 180 && r < 60; };

  for (const [name, options] of [
    ['desktop, light', {}],
    ['desktop, dark', { colorScheme: 'dark' }],
    ['phone, light', { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }],
    ['phone, dark', { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, colorScheme: 'dark' }],
  ]) {
    test.describe(name, () => {
      test.use(options);

      test('a small grey circle, not a second blue Search button; it clears the box', async ({ page }) => {
        expect((await look(page)).button.display).toBe('none');            // hidden while the box is empty
        await page.type('#productInput', 'MacBook');
        const shown = await look(page);
        expect(isBlue(shown.circle.bg) || isBlue(shown.button.bg)).toBe(false);
        expect(shown.circle).toMatchObject({ radius: '50%', width: 20, height: 20 });
        expect(shown.circle.color).not.toBe(shown.circle.bg);
        expect(shown.button.width).toBeGreaterThanOrEqual(24);                 // easy to hit
        expect(shown.button.height).toBeGreaterThanOrEqual(24);
        expect(isBlue(shown.search.bg)).toBe(true);
        await page.hover('#clearBtn');
        expect(isBlue((await look(page)).circle.bg)).toBe(false);
        await page.hover('#searchBtn');
        await expect.poll(async () => (await look(page)).search.bg).not.toBe(shown.search.bg);   // Search still darkens
        await page.click('#clearBtn');
        await expect(page.locator('#productInput')).toHaveValue('');
        await expect(page.locator('#productInput')).toBeFocused();
        expect((await look(page)).button.display).toBe('none');
        await expect(page.locator('#suggestList')).toBeHidden();
      });
    });
  }

  test('works from the keyboard and is labelled for screen readers', async ({ page }) => {
    await page.focus('#productInput');
    await page.keyboard.type('iPad');
    await page.keyboard.press('Escape');
    await page.keyboard.press('Tab');
    const clear = page.locator('#clearBtn');
    await expect(clear).toBeFocused();
    await expect(clear).toHaveAccessibleName('Clear search');
    expect(await clear.evaluate(el => getComputedStyle(el).outlineStyle)).not.toBe('none');
    await page.keyboard.press('Enter');
    await expect(page.locator('#productInput')).toHaveValue('');
    await expect(page.locator('#productInput')).toBeFocused();
  });
});

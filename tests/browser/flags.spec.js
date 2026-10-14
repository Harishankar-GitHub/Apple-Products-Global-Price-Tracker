// Country flags. They are emoji, which Windows does not draw (it shows "IE" for 🇮🇪), so
// there the page uses the flag font in docs/fonts/; everywhere else the system's own flags
// are kept and the font is never downloaded. These tests stand in for Windows by making
// the browser's canvas draw the letters instead of the flag, as Windows does.
const { test, expect } = require('./support/fixtures');
const { rows } = require('./support/data');

const LIKE_WINDOWS = () => {
  const draw = CanvasRenderingContext2D.prototype.fillText;
  CanvasRenderingContext2D.prototype.fillText = function (text, ...rest) {
    const letters = [...text].map(c => {
      const n = c.codePointAt(0);
      return n >= 0x1F1E6 && n <= 0x1F1FF ? String.fromCharCode(n - 0x1F1E6 + 65) : c;   // 🇮 → I
    }).join('');
    return draw.call(this, letters, ...rest);
  };
};

async function open(page, server) {
  const fontRequests = [];
  page.on('request', r => { if (new URL(r.url()).pathname.includes('/fonts/')) fontRequests.push(r.url()); });
  await page.goto('/');
  await server.searchAndFinish('MacBook Air', rows());
  return page.evaluate(() => ({
    flagFont: document.documentElement.classList.contains('flag-font'),
    family: getComputedStyle(document.querySelector('#results .flag')).fontFamily,
    loaded: document.fonts.check('16px "Country Flags"', '🇮🇪'),
  })).then(state => ({ ...state, fontRequests }));
}

test('where the system draws flags, its own are kept and the flag font is never downloaded', async ({ page, server }) => {
  const state = await open(page, server);
  expect(state.flagFont).toBe(false);
  expect(state.family).not.toContain('Country Flags');
  expect(state.fontRequests).toEqual([]);
});

test('on Windows the flags come from the flag font, downloaded once', async ({ page, server }) => {
  await page.addInitScript(LIKE_WINDOWS);
  const state = await open(page, server);
  expect(state.flagFont).toBe(true);
  expect(state.family).toMatch(/^"Country Flags", -apple-system/);          // the flags first, the page's fonts after
  expect(state.loaded).toBe(true);
  expect(state.fontRequests).toHaveLength(1);
  expect(state.fontRequests[0]).toMatch(/\/fonts\/twemoji-country-flags\.woff$/);
  // Only the flags use it: text is still in the page's own font.
  const text = await page.evaluate(() => getComputedStyle(document.querySelector('#results .country-name')).fontFamily);
  expect(text).toContain('-apple-system');
});

test('a canvas that cannot be read leaves the page as it is', async ({ page, server }) => {
  await page.addInitScript(() => { HTMLCanvasElement.prototype.getContext = () => null; });
  const state = await open(page, server);
  expect(state.flagFont).toBe(false);
  expect(state.fontRequests).toEqual([]);
});

test('the flag artwork is credited', async ({ page }) => {
  await page.goto('/');
  const credit = page.locator('footer .flag-credit');
  await expect(credit).toContainText('Twemoji');
  await expect(credit.getByRole('link', { name: 'CC-BY 4.0' })).toHaveAttribute('href', 'https://creativecommons.org/licenses/by/4.0/');
});

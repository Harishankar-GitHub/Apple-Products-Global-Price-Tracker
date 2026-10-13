// The preview shown when a link to the site is shared: read the way link previewers
// read it (no JavaScript), and the image it points to.
const fs = require('fs');
const path = require('path');
const { test, expect } = require('@playwright/test');

const ROOT = path.resolve(__dirname, '../..');
const SITE = 'https://harishankar-github.github.io/Apple-Products-Global-Price-Tracker/';
const IMAGE = path.join(ROOT, 'docs/og.png');

test.use({ javaScriptEnabled: false, userAgent: 'facebookexternalhit/1.1' });

const tags = page => page.evaluate(() => Object.fromEntries(
  [...document.querySelectorAll('head meta[property^="og:"], head meta[name^="twitter:"]')]
    .map(m => [m.getAttribute('property') || m.getAttribute('name'), m.content])));

test('a shared search link carries a complete preview', async ({ page }) => {
  await page.goto('/?q=MacBook+Air');
  const t = await tags(page);
  expect(t).toMatchObject({
    'og:site_name': 'Apple Global Price Tracker', 'og:title': 'Apple Global Price Tracker', 'og:type': 'website',
    'og:image': `${SITE}og.png`, 'og:image:type': 'image/png', 'og:image:width': '1200', 'og:image:height': '630',
    'twitter:card': 'summary_large_image',
  });
  expect(t['og:description'].length).toBeGreaterThan(20);
  expect(t['og:image:alt'].length).toBeGreaterThan(30);
  expect(t['twitter:image:alt']).toBe(t['og:image:alt']);
  // og:url or a canonical link would send every shared search back to the home page
  expect(t['og:url']).toBeUndefined();
  await expect(page.locator('link[rel="canonical"]')).toHaveCount(0);
});

test('the tags are at the very top of the page (some previewers read only the start)', () => {
  const html = fs.readFileSync(path.join(ROOT, 'docs/index.html'), 'utf8');
  const last = Math.max(...['og:image', 'og:title', 'og:description', 'twitter:card'].map(k => html.indexOf(`"${k}"`)));
  expect(last).toBeGreaterThan(0);
  expect(last).toBeLessThan(4096);
});

test('the image is a 1200 × 630 PNG small enough for every app', () => {
  const png = fs.readFileSync(IMAGE);
  expect(png.subarray(0, 8)).toEqual(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
  expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([1200, 630]);
  expect(png.length).toBeLessThan(300 * 1024);
  expect(fs.existsSync(path.join(ROOT, 'assets/og-image.html'))).toBe(true);           // its source
});

test('the address in the tags serves that image', async ({ page, baseURL }) => {
  await page.goto('/');
  const local = (await tags(page))['og:image'].replace(SITE, `${baseURL}/`);
  const response = await page.goto(local);
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toBe('image/png');
  expect(await response.body()).toEqual(fs.readFileSync(IMAGE));
});

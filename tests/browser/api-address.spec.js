// Which API the page talks to: the one on this computer when the page is opened from it
// (the tests serve it from 127.0.0.1, with LOCAL_API pointed at the test API), the live
// one anywhere else, such as GitHub Pages.
const fs = require('fs');
const path = require('path');
const { test, expect } = require('./support/fixtures');

const CONFIG = fs.readFileSync(path.resolve(__dirname, '../../docs/js/config.js'), 'utf8');
const LIVE_API = CONFIG.match(/export const LIVE_API = "([^"]+)";/)[1];
const TEST_API = 'http://127.0.0.1:5055';
const SITE = 'http://127.0.0.1:8088';

/** Serve the site (from the test server) at another address, as if it were hosted there. */
async function hostAt(page, origin, base = '/') {
  await page.route(`${origin}/**`, async route => {
    const { pathname } = new URL(route.request().url());
    if (!pathname.startsWith(base)) return route.fulfill({ status: 404 });
    const response = await route.fetch({ url: SITE + '/' + pathname.slice(base.length) });
    return route.fulfill({ response });
  });
}

async function addressesUsed(page, health, server) {
  await expect.poll(() => health.pings.length).toBeGreaterThan(0);
  await page.fill('#productInput', 'MacBook Air');
  await page.press('#productInput', 'Enter');
  return { ping: health.pings[0].url, search: await (await server.latest()).url() };
}

test('the live address is the API on Render', () => {
  expect(LIVE_API).toBe('https://apple-products-global-price-tracker.onrender.com');
});

test('on GitHub Pages the page uses the live API', async ({ page, health, server }) => {
  const origin = 'https://harishankar-github.github.io';
  await hostAt(page, origin, '/Apple-Products-Global-Price-Tracker/');
  await page.goto(`${origin}/Apple-Products-Global-Price-Tracker/`);
  const used = await addressesUsed(page, health, server);
  expect(used.ping).toBe(`${LIVE_API}/api/health`);
  expect(used.search).toBe(`${LIVE_API}/api/prices/stream?product=MacBook%20Air`);
});

for (const origin of [SITE, 'http://localhost:8000']) {
  test(`opened from this computer (${new URL(origin).hostname}) the page uses the API on this computer`,
    async ({ page, health, server }) => {
      if (origin !== SITE) await hostAt(page, origin);
      await page.goto(`${origin}/`);
      const used = await addressesUsed(page, health, server);
      expect(used.ping).toBe(`${TEST_API}/api/health`);
      expect(used.search).toBe(`${TEST_API}/api/prices/stream?product=MacBook%20Air`);
    });
}

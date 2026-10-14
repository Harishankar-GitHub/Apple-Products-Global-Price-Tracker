// How the page is put together: a stylesheet and JavaScript modules in docs/, no inline
// script, every module preloaded so the browser fetches them all at once, and the
// countries taken from the table the API uses.
const fs = require('fs');
const path = require('path');
const { test, expect } = require('./support/fixtures');
const { rows } = require('./support/data');

const DOCS = path.resolve(__dirname, '../../docs');
const html = () => fs.readFileSync(path.join(DOCS, 'index.html'), 'utf8');
const modules = () => fs.readdirSync(path.join(DOCS, 'js')).filter(f => f.endsWith('.js')).sort();

test('every module is preloaded, and every preload is a module that exists', () => {
  const preloaded = [...html().matchAll(/<link rel="modulepreload" href="js\/([\w-]+\.js)" \/>/g)].map(m => m[1]).sort();
  expect(preloaded).toEqual(modules());
  expect(html()).toContain('<script type="module" src="js/main.js"></script>');
});

test('no inline script or event-handler attribute, in the page or in what the modules write', () => {
  expect(html()).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>/);        // every <script> loads a file
  expect(html()).not.toMatch(/<style\b/);                              // the styles are in styles.css
  for (const file of ['index.html', ...modules().map(m => `js/${m}`)]) {
    expect(fs.readFileSync(path.join(DOCS, file), 'utf8'), file).not.toMatch(/\son[a-z]+\s*=\s*["'`]/);
  }
});

test('every font size is in rem, so all text follows the page\'s text size', () => {
  const css = fs.readFileSync(path.join(DOCS, 'styles.css'), 'utf8');
  const sizes = [...css.matchAll(/font-size:\s*([^;}]+)/g)].map(m => m[1].trim());
  expect(sizes.length).toBeGreaterThan(40);
  expect(sizes.filter(v => /^[\d.]+px$/.test(v))).toEqual([]);                    // none set in plain px
  expect(css).toMatch(/html \{ font-size: clamp\(100%, [^;]+, 112\.5%\); \}/);
});

test('each file is fetched once and found', async ({ page }) => {
  const fetched = [];
  page.on('response', r => {
    const file = new URL(r.url()).pathname.slice(1);                     // "js/main.js", "styles.css"
    if (/^(js\/[\w-]+\.js|styles\.css)$/.test(file)) fetched.push([file, r.status()]);
  });
  await page.goto('/');
  await expect(page.locator('#homeSelect option')).not.toHaveCount(0);     // the modules have run
  expect(fetched.map(([file]) => file).sort()).toEqual(['styles.css', ...modules().map(m => `js/${m}`)].sort());
  expect(fetched.every(([, status]) => status === 200)).toBe(true);
});

test('works under a Content-Security-Policy that allows only its own scripts', async ({ page, server }) => {
  await page.route(url => new URL(url).pathname === '/', async route => {
    const response = await route.fetch();
    await route.fulfill({ response, headers: { ...response.headers(), 'content-security-policy': "script-src 'self'; object-src 'none'" } });
  });
  await page.goto('/');
  await page.click('#quickSearches [data-quick="Mac mini"]');            // a chip: a listener, not an onclick
  const stream = await server.latest();
  await stream.complete(rows({ base: 599 }), { meta: { product: 'Mac mini' } });
  await expect(page.locator('#results tbody tr[data-key]')).toHaveCount(30);
  await page.click('#results th[data-sort="country-asc country-desc"]');
  await expect(page.locator('#results tbody tr[data-key]').first()).toHaveAttribute('data-key', 'Australia');
  // A script blocked by the policy would be reported as a page error, which fails the test.
});

test('the countries are the API\'s: home countries, currencies and regions come from api/tracker/countries.json', async ({ page }) => {
  const table = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../api/tracker/countries.json'), 'utf8'));
  await page.goto('/');
  const options = sel => page.locator(`${sel} option`).evaluateAll(os => os.map(o => o.value));
  expect(await options('#homeSelect')).toEqual(table.countries.map(c => c.name).sort((a, b) => a.localeCompare(b)));
  expect((await options('#currencySelect')).slice(1)).toEqual([...new Set(table.countries.map(c => c.currency))].sort());
  expect(await page.locator('#regionChips [data-region]').evaluateAll(bs => bs.map(b => b.dataset.region)))
    .toEqual(['all', ...table.regions]);
});

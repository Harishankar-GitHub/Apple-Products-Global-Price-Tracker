// Light and dark mode: every colour that changes between them is a token on :root in
// docs/styles.css, with all the dark values in one block, and the page uses them.
const fs = require('fs');
const path = require('path');
const { test, expect } = require('./support/fixtures');
const { rows } = require('./support/data');

const CSS = fs.readFileSync(path.resolve(__dirname, '../../docs/styles.css'), 'utf8');

/** The custom properties set in a block of CSS: { '--bg': '#000000', … } */
const tokens = block => Object.fromEntries([...block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map(m => [m[1], m[2].trim()]));

test('dark mode is one block, and it only sets colour tokens', () => {
  const darkBlocks = [...CSS.matchAll(/@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{([^}]*)\}\s*\}/g)];
  expect(CSS.match(/prefers-color-scheme/g)).toHaveLength(1);
  expect(darkBlocks).toHaveLength(1);
  const dark = darkBlocks[0][1];
  expect(dark.replace(/(--[\w-]+)\s*:\s*([^;]+);/g, '').replace(/\/\*[\s\S]*?\*\//g, '').trim()).toBe('');   // nothing else in it
  const light = tokens(CSS.slice(0, darkBlocks[0].index).match(/:root\s*\{([^}]*)\}/)[1]);
  for (const name of Object.keys(tokens(dark))) expect(light, `${name} has a light value`).toHaveProperty(name);
});

const LOOKS = {
  light: { header: 'rgba(255, 255, 255, 0.72)', glow: 'rgba(0, 113, 227, 0.13)', cheapest: 'rgba(26, 158, 92, 0.07)',
    cheapestHover: 'rgba(26, 158, 92, 0.12)', page: 'rgb(245, 245, 247)' },
  dark: { header: 'rgba(28, 28, 30, 0.72)', glow: 'rgba(0, 113, 227, 0.22)', cheapest: 'rgba(26, 158, 92, 0.12)',
    cheapestHover: 'rgba(26, 158, 92, 0.18)', page: 'rgb(0, 0, 0)' },
};

for (const [scheme, look] of Object.entries(LOOKS)) {
  test.describe(`${scheme} mode`, () => {
    test.use({ colorScheme: scheme });

    test('the page, header, hero and cheapest row take the colours of this mode', async ({ page, server }) => {
      await page.goto('/');
      const style = (selector, property, pseudo = null) =>
        page.locator(selector).first().evaluate((el, [p, ps]) => getComputedStyle(el, ps).getPropertyValue(p), [property, pseudo]);
      expect(await style('body', 'background-color')).toBe(look.page);
      expect(await style('header', 'background-color')).toBe(look.header);
      expect(await style('.hero-wrap', 'background-image', '::before')).toContain(look.glow);
      await server.searchAndFinish('MacBook Air', rows());
      const cheapest = page.locator('#results tbody tr.cheapest-row');
      await expect(cheapest).toHaveCount(1);
      await page.mouse.move(0, 0);
      await expect.poll(() => style('#results tbody tr.cheapest-row', 'background-color')).toBe(look.cheapest);
      await cheapest.hover();
      await expect.poll(() => style('#results tbody tr.cheapest-row', 'background-color')).toBe(look.cheapestHover);
    });
  });
}

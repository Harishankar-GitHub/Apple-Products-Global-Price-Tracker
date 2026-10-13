// CSV export: the rows shown, in the order shown, with prices a spreadsheet can use.
const fs = require('fs');
const { test, expect } = require('./support/fixtures');
const { RATES, rows, usdOf, ratesWithout } = require('./support/data');
const { tableRows } = require('./support/page-model');

const HEADER = 'Rank,Country,Region,Pinned,Local currency,Listed local price,Price (EUR),Listed price (USD),'
  + 'More than cheapest (EUR),More than cheapest (%),Status,Store URL';

async function exportCsv(page) {
  const [download] = await Promise.all([page.waitForEvent('download'), page.click('#exportCsvBtn')]);
  const text = fs.readFileSync(await download.path(), 'utf8');
  const lines = text.replace(/^﻿/, '').trim().split('\r\n');
  const header = lines[0].split(',');
  const records = lines.slice(1).map(l => Object.fromEntries(l.split(',').map((v, i) => [header[i], v])));
  return { name: download.suggestedFilename(), text, lines, records };
}

test.beforeEach(async ({ page }) => { await page.goto('/'); });

test('the rows shown, with a byte-order mark for Excel', async ({ page, server }) => {
  await server.searchAndFinish('MacBook Air');
  await page.click('[data-pin="Germany"]');
  await page.click('#regionChips [data-region="Europe"]');
  await expect.poll(async () => (await tableRows(page)).length).toBe(13);
  const csv = await exportCsv(page);
  expect(csv.name).toMatch(/^macbook-air-prices-\d{4}-\d{2}-\d{2}\.csv$/);
  expect(csv.text.charCodeAt(0)).toBe(0xfeff);
  expect(csv.lines[0]).toBe(HEADER);
  expect(csv.records.map(r => r.Country)).toEqual((await tableRows(page)).map(r => r.country));
  const germany = csv.records.find(r => r.Country === 'Germany');
  expect(germany).toMatchObject({ Region: 'Europe', Pinned: 'yes', 'Local currency': 'EUR', Status: 'Available' });
  expect(Number(germany['Price (EUR)'])).toBeCloseTo(usdOf('Germany') * RATES.EUR, 1);
  expect(Number(germany['More than cheapest (EUR)'])).toBeCloseTo((usdOf('Germany') - usdOf('Japan')) * RATES.EUR, 1);
});

test('a price without an exchange rate: empty price columns, never 0, and the reason', async ({ page, server }) => {
  await server.searchAndFinish('MacBook Air', rows({ usd: { India: null } }), { meta: { rates: ratesWithout('INR') } });
  const india = (await exportCsv(page)).records.find(r => r.Country === 'India');
  expect(india).toMatchObject({ Rank: '', 'Price (EUR)': '', 'Listed price (USD)': '', 'More than cheapest (EUR)': '',
    'More than cheapest (%)': '', Status: 'Available (no exchange rate)' });
  expect(Number(india['Listed local price'])).toBeGreaterThan(0);
});

for (const usd of [0, -5]) {
  test(`a conversion of ${usd} is not exported as a price`, async ({ page, server }) => {
    await server.searchAndFinish('MacBook Air', rows({ usd: { India: usd } }));
    const india = (await exportCsv(page)).records.find(r => r.Country === 'India');
    expect([india['Price (EUR)'], india['Listed price (USD)']]).toEqual(['', '']);
  });
}

// Reads what the page shows, in plain values the tests can compare.

const text = s => (s ?? '').trim().replace(/\s+/g, ' ');

/** Every row in the table, top to bottom. */
const tableRows = page => page.evaluate(() => [...document.querySelectorAll('#results tbody tr[data-key]')].map(tr => {
  const t = sel => tr.querySelector(sel)?.textContent.trim().replace(/\s+/g, ' ') ?? null;
  return {
    country: tr.dataset.key,
    rank: t('.rank'),
    medal: tr.querySelector('.rank')?.className.match(/rank-(\d)/)?.[1] ?? null,
    local: t('.price-local'),
    converted: t('.price-conv'),
    diff: t('.badge-saving'),
    diffClass: tr.querySelector('.badge-saving')?.className ?? null,
    cheapest: !!tr.querySelector('.badge-cheap'),
    home: !!tr.querySelector('.badge-home'),
    pinned: tr.classList.contains('pinned-row'),
    bar: parseFloat(tr.querySelector('.price-bar-fill')?.style.width ?? 'NaN'),
    unavailable: t('.unavail-badge'),
  };
}));

const row = async (page, country) => (await tableRows(page)).find(r => r.country === country);

const summary = page => page.evaluate(() => {
  const t = id => document.getElementById(id).textContent.trim().replace(/\s+/g, ' ');
  return { product: t('summaryProduct'), found: t('summaryFound'), cheapest: t('summaryCheapest'),
    priciest: t('summaryMostExp'), home: t('summaryHome'), note: t('summaryNote'),
    shown: getComputedStyle(document.getElementById('summary')).display !== 'none' };
});

const progress = page => page.evaluate(() => {
  const bar = document.getElementById('progressBar'), fill = document.getElementById('progressFill');
  const count = document.getElementById('progressCount');
  return { shown: getComputedStyle(document.getElementById('progressWrap')).display !== 'none',
    label: document.getElementById('progressLabel').textContent, count: count.textContent,
    countHidden: count.getAttribute('aria-hidden'), moving: bar.classList.contains('indeterminate'),
    animation: getComputedStyle(fill).animationName, fillWidth: fill.getBoundingClientRect().width,
    barWidth: bar.getBoundingClientRect().width, width: fill.style.width };
});

const WAKE = 'Waking up the server… this can take up to a minute';

/**
 * The progress counter 4 s later: past the 3 s after which a search still waiting
 * for the server's first reply shows a seconds counter ("4s", hidden from screen
 * readers) next to the waking-up message. Compare with NOT_WAITING to check that
 * nothing is waiting any more. (Runs the page's clock.)
 */
async function fourSecondsLater(page) {
  await page.clock.runFor(4_000);
  const p = await progress(page);
  return { secondsCounter: /^\d+s$/.test(p.count), countHidden: p.countHidden };
}
const NOT_WAITING = { secondsCounter: false, countHidden: null };

const footer = async page => text(await page.locator('.results-footer').textContent());

/** Number from a price text such as "≈ €1,213.08" or "€120 more than…" (first number). */
const amount = s => Number(String(s).match(/-?[\d,]+(\.\d+)?/)[0].replace(/,/g, ''));

/** Percentage in "(+13%)". */
const percent = s => Number(String(s).match(/\(\+([\d.]+)%\)/)[1]);

/** The page's horizontal overflow (0 when nothing scrolls sideways). */
const sidewaysScroll = page => page.evaluate(() => document.documentElement.scrollWidth - innerWidth);

module.exports = { text, tableRows, row, summary, progress, WAKE, fourSecondsLater, NOT_WAITING, footer, amount, percent,
  sidewaysScroll };

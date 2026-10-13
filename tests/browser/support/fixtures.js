// Fixtures for the page tests. The page's EventSource is replaced by a stand-in, so a
// test decides exactly what "the server" sends and when; /api/health answers as the
// test says. Every test fails if the page logs an error.
const { test: base, expect } = require('@playwright/test');
const { RATES, rows } = require('./data');

const PREFS_KEY = 'apgt:prefs:v1';

const FAKE_EVENT_SOURCE = () => {
  window.__sources = [];
  window.EventSource = class {
    constructor(url) { this.url = url; this.listeners = {}; this.closed = false; window.__sources.push(this); }
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
    emit(type, data) {
      if (this.closed) return;
      (this.listeners[type] || []).forEach(fn => fn({ data: data === undefined ? undefined : JSON.stringify(data) }));
    }
    close() { this.closed = true; }
  };
};

/** One search as the page sees it: send it events from "the server". */
class Stream {
  constructor(page, index) { this.page = page; this.index = index; }

  async emit(type, data) {
    await this.page.evaluate(([i, type, data]) => window.__sources[i].emit(type, data), [this.index, type, data]);
  }

  searching(product = 'MacBook Air') { return this.emit('searching', { product }); }
  queued() { return this.emit('queued', { message: 'Waiting for other searches to finish', maxWaitSeconds: 45 }); }
  error(payload) { return this.emit('error', payload); }

  meta(fields = {}) {
    const product = fields.product ?? 'MacBook Air';
    const slug = product.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    return this.emit('meta', { product, slug, matchedName: product, substituted: false, category: 'mac', total: 35, rates: RATES, ...fields });
  }

  async results(list) {
    await this.page.evaluate(([i, list]) => list.forEach(r => window.__sources[i].emit('result', r)), [this.index, list]);
  }

  done(fields = {}) { return this.emit('done', { product: 'MacBook Air', ...fields }); }

  /** The whole search in one go: searching → meta → every row → done. */
  async complete(list = rows(), { meta = {}, done = {} } = {}) {
    const product = meta.product ?? 'MacBook Air';
    await this.searching(product);
    await this.meta({ total: list.length, ...meta });
    await this.results(list);
    await this.done({ product, ...done });
  }

  url() { return this.page.evaluate(i => window.__sources[i].url, this.index); }
  closed() { return this.page.evaluate(i => window.__sources[i].closed, this.index); }
}

class FakeServer {
  constructor(page) { this.page = page; }

  /** Searches opened so far. */
  count() { return this.page.evaluate(() => window.__sources.length); }

  async latest() { return new Stream(this.page, (await this.count()) - 1); }

  /** Type a product and press Enter (closing the suggestions first); returns its stream. */
  async search(product) {
    await this.page.fill('#productInput', product);
    await this.page.keyboard.press('Escape');
    await this.page.press('#productInput', 'Enter');
    return this.latest();
  }

  /** Search and answer it completely; waits until the page has drawn the final table. */
  async searchAndFinish(product = 'MacBook Air', list = rows(), options = {}) {
    const stream = await this.search(product);
    await stream.complete(list, { ...options, meta: { product, ...(options.meta || {}) } });
    await expect(this.page.locator('#searchBtn')).toHaveText('Search');
    return stream;
  }
}

const test = base.extend({
  /** Preferences already saved in the browser (set once, before the first page load). */
  savedPrefs: [null, { option: true }],

  /** How /api/health answers: 'ok' | 'hang' | a status code | 'html' | 'abort'. Can be changed during a test. */
  health: async ({ context }, use) => {
    const control = { mode: 'ok', pings: [], held: [],
      release() { this.held.splice(0).forEach(answer => answer()); } };
    await context.route('**/api/health', async route => {
      control.pings.push({ url: route.request().url(), method: route.request().method(), at: Date.now() });
      const ok = () => route.fulfill({ status: 200, contentType: 'application/json',
        headers: { 'access-control-allow-origin': '*' }, body: '{"status":"ok"}' }).catch(() => {});
      if (control.mode === 'ok') return ok();
      if (control.mode === 'hang') { control.held.push(ok); return undefined; }
      if (control.mode === 'abort') return route.abort();
      if (control.mode === 'html') {
        return route.fulfill({ status: 200, contentType: 'text/html', headers: { 'access-control-allow-origin': '*' },
          body: '<html>Service waking up</html>' });
      }
      return route.fulfill({ status: control.mode, headers: { 'access-control-allow-origin': '*' }, body: 'unavailable' });
    });
    await use(control);
  },

  page: async ({ page, savedPrefs, health }, use) => {
    void health;                                       // its route must exist before the page loads
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    // Script errors fail the test; the browser's own "Failed to load resource" notes for
    // requests a test makes fail on purpose do not.
    page.on('console', m => { if (m.type() === 'error' && !/^Failed to load resource/.test(m.text())) errors.push(m.text()); });
    await page.addInitScript(FAKE_EVENT_SOURCE);
    if (savedPrefs) {
      await page.addInitScript(([key, prefs]) => {
        if (sessionStorage.getItem('__prefsSaved')) return;          // only before the first load
        try { localStorage.setItem(key, typeof prefs === 'string' ? prefs : JSON.stringify(prefs)); } catch { /* blocked */ }
        sessionStorage.setItem('__prefsSaved', '1');
      }, [PREFS_KEY, savedPrefs]);
    }
    await page.route('**/api/prices**', route => route.abort());      // nothing real is fetched
    await use(page);
    expect(errors, 'errors in the page').toEqual([]);
  },

  server: async ({ page }, use) => { await use(new FakeServer(page)); },
});

/**
 * Load a page with its clock stopped: time only moves when the test calls
 * page.clock.runFor(), so timings are exact on any machine.
 */
async function openPaused(page, url = '/') {
  const start = Date.now();
  await page.clock.install({ time: start });
  await page.clock.pauseAt(start + 1000);
  await page.goto(url);
}

module.exports = { test, expect, openPaused, PREFS_KEY };

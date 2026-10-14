# 🍎 Apple Products Global Price Tracker

Compare official Apple prices across 50+ country storefronts in real time. Results stream in as they arrive — no waiting for all countries to finish.

## 🌐 Live Demo

Frontend (GitHub Pages): https://harishankar-github.github.io/Apple-Products-Global-Price-Tracker/  
Backend API (Render): https://apple-products-global-price-tracker.onrender.com

![UI](https://img.shields.io/badge/UI-GitHub%20Pages-blue?style=flat-square)
![API](https://img.shields.io/badge/API-Python%20Flask-green?style=flat-square)
![Backend](https://img.shields.io/badge/Backend-Render-black?style=flat-square)
![Async](https://img.shields.io/badge/HTTP-aiohttp%20async-orange?style=flat-square)

---

## How It Works

1. You type a product name (e.g. "MacBook Air", "iPhone 17", "Mac mini")
2. The API resolves the correct apple.com slug — checking a known-good override table first, then probing apple.com live if needed
3. All 50 country requests fire **simultaneously** via `aiohttp`, on one event loop and connection pool that every search shares (no worker pool)
4. Each country result is pushed to the browser via **Server-Sent Events (SSE)** the moment it arrives — the table updates live
5. Prices are extracted from Apple's embedded JSON-LD `"lowPrice"` field — no JavaScript execution needed
6. Prices are converted to USD using live exchange rates from [open.er-api.com](https://open.er-api.com)
7. Results are ranked cheapest-first with animated FLIP transitions as the sort order changes

---

## Features

- **Home country and currency** — pick your home country and every price is also shown in your currency and your home row is marked. Each row says how much more it costs than the cheapest country. The home country is guessed from the browser language the first time and saved in the browser.
- **Shareable links** — the search lives in the URL (`?q=MacBook+Air`), works with back/forward, and there is a *Copy link* button.
- **Recent searches and autocomplete** — the last 6 successful searches are kept in the browser; product names are suggested as you type.
- **Region filters and pinned countries** — filter by Americas / Europe / Asia Pacific / Middle East & Africa; star a country to keep it at the top.
- **Table and chart** — on wide screens the table and a bar chart of how much more each country costs than the cheapest sit side by side; a switch shows only the table or only the chart. Narrow screens show one at a time.
- **CSV export** — downloads the rows currently shown.
- **Clear empty states** — if no country returns a price the page says "No prices found for … in any country" (tick *Show unavailable* to see what each country returned); "No countries match these filters" is used only when a filter is the reason.
- **Closest-match notice** — if the prices are for a different product than the one typed (for example a retired model mapped to the current one), the page says which product it is showing.

The countries are one table, `api/tracker/countries.json`: name, ISO code, region, the store's URL prefix on apple.com, currency and symbol (flags are worked out from the ISO code). The API reads it; the page gets a copy, `docs/js/countries.js`, because GitHub Pages serves only `docs/` and Render only `api/`. To add or change a store, edit the table and run `python3 scripts/sync_countries.py`, which also updates the list under [Supported Countries](#supported-countries); the tests fail if a copy is out of date. The product names offered as you type are in `docs/js/data.js` (`PRODUCTS`) — update them when Apple's line-up changes. All prices are compared exactly as Apple lists them; note that the US and Canada list prices before sales tax while most other stores include VAT/GST. Preferences are stored in `localStorage` under `apgt:prefs:v1`.

---

## Project Structure

```
apple-global-price-tracker/
├── docs/                   # The website (GitHub Pages), no build step
│   ├── index.html          # The page's markup
│   ├── styles.css          # All of its styles
│   ├── js/                 # Its script, as native JavaScript modules
│   │   ├── main.js         #   Starts the page and connects the controls to the code
│   │   ├── config.js       #   The API's address
│   │   ├── search.js       #   A search: the stream of events from the API
│   │   ├── wake.js         #   Waking the API, and the "waking up the server" message
│   │   ├── render.js       #   Drawing the results as they stream in
│   │   ├── table.js        #   The results table
│   │   ├── chart.js        #   The chart
│   │   ├── summary.js      #   The summary bar
│   │   ├── view.js         #   Ranks, differences and filters, worked out from the results
│   │   ├── controls.js     #   Home country, currency, regions, sorting, pins
│   │   ├── search-box.js   #   Suggestions and recent searches
│   │   ├── links.js        #   Shareable links and history
│   │   ├── csv.js          #   CSV export
│   │   ├── prefs.js        #   Preferences saved in the browser
│   │   ├── state.js        #   The search on screen
│   │   ├── data.js         #   Countries, regions and currencies (from countries.js), product names
│   │   ├── countries.js    #   Copy of api/tracker/countries.json, written by scripts/sync_countries.py
│   │   ├── format.js       #   Money, durations, percentages
│   │   └── dom.js          #   Small DOM helpers
│   └── og.png              # Image shown when a link to the site is shared
├── assets/
│   └── og-image.html       # Source of og.png
├── api/
│   ├── app.py              # Entry point that gunicorn loads (app:app)
│   ├── tracker/            # The Flask API
│   │   ├── routes.py       #   HTTP endpoints
│   │   ├── search.py       #   One search, start to finish, for both price endpoints
│   │   ├── limits.py       #   Rate limits, telling visitors apart, the admin token
│   │   ├── lookup.py       #   Product name → Apple's page for it, with its cache
│   │   ├── prices.py       #   Reading a price off a page; fetching all 50 stores at once
│   │   ├── results_cache.py #  Finished result sets per product
│   │   ├── exchange.py     #   Exchange rates, kept for 30 minutes
│   │   ├── web.py          #   One event loop and connection pool for apple.com
│   │   ├── countries.json  #   The one table of countries, for the API and (copied) the page
│   │   ├── countries.py    #   Reads it: the 50 stores, their URL prefix, currency, flag
│   │   └── config.py       #   Every setting, including the environment variables
│   ├── gunicorn.conf.py    # Server settings: threads and timeouts
│   ├── requirements.txt
│   └── render.yaml         # Render deployment config
├── tests/
│   ├── api/                # API tests (pytest)
│   ├── browser/            # Page and end-to-end tests (Playwright)
│   ├── fakes/apple.py      # Stand-in for apple.com and the exchange-rate service
│   └── servers/fake_api.py # The API with apple.com faked, for gunicorn and browser tests
├── scripts/
│   └── sync_countries.py   # Copies the country table to the page and the README
├── .github/                # CI workflow and Dependabot settings
├── pyproject.toml          # pytest and ruff settings
├── requirements-dev.txt    # Test and lint tools
├── package.json            # Playwright (browser tests)
├── playwright.config.js
└── README.md
```

---

## Deployment

### Step 1 — Deploy the API (Render free tier)

1. Fork or push this repo to GitHub
2. Go to [render.com](https://render.com) → **New → Web Service** → select this repo
3. Set **Root Directory** to `api`
4. Render auto-detects `render.yaml` → click **Deploy**
5. Copy your service URL, e.g. `https://apple-products-global-price-tracker.onrender.com`

> **Free tier note:** Render spins down the service after ~15 min of inactivity. The first request after a cold start takes 30–60 s to wake up. In-memory caches (exchange rates, slug resolutions, price results) are cleared on each cold start.
>
> To soften this, the page sends a request to `/api/health` as soon as it loads, so the service starts waking while the visitor is still typing. If a search is still waiting for the service's first reply (the ping has gone unanswered for 1.5 s, or the search for 3 s), the progress area shows "Waking up the server… this can take up to a minute" with a seconds counter and a moving bar.

**Start command.** `render.yaml` starts the API with `gunicorn -c gunicorn.conf.py app:app`. If your service was created by hand with `gunicorn app:app` as the start command, that works too: gunicorn reads `gunicorn.conf.py` by itself when it starts in the `api` folder (the Root Directory). The file sets how many visitors are served at once — see [Serving several visitors at once](#serving-several-visitors-at-once).

### Step 2 — Configure the Frontend

In `docs/js/config.js`, set your deployed API URL:

```js
export const API_BASE = "https://YOUR-API-URL.onrender.com"; // production
// export const API_BASE = "http://localhost:5000";           // local dev
```

Comment out the production line for local development, uncomment before pushing.

### Step 3 — Enable GitHub Pages

1. Repo → **Settings → Pages**
2. Source: **Deploy from a branch** → Branch: `main` / Folder: `/docs`
3. Click **Save**

Your site: `https://<your-username>.github.io/<repo-name>/`

GitHub Pages lets browsers keep each file for up to 10 minutes. A visitor who reloads within minutes of a deploy can briefly get some of the old files with some of the new; reloading again once those minutes have passed fixes it.

**Link previews.** When a link to the site is shared (WhatsApp, Slack, X, LinkedIn, iMessage…), the preview shows `docs/og.png`. Link previewers need the image's full address, so `og:image` in `docs/index.html` names this site's address on GitHub Pages; if you deploy your own copy, change it to `https://<your-username>.github.io/<repo-name>/og.png`. To change the picture, edit `assets/og-image.html` and save a 1200 × 630 screenshot of it over `docs/og.png`:

```bash
npx playwright screenshot --viewport-size "1200,630" assets/og-image.html docs/og.png
```

Apps keep a copy of a preview once they have shown it, so a link shared before a change can keep its old preview for a while. Facebook's [Sharing Debugger](https://developers.facebook.com/tools/debug/) and LinkedIn's [Post Inspector](https://www.linkedin.com/post-inspector/) can fetch it again.

---

## Local Development

```bash
cd api
pip install -r requirements.txt
python app.py
# API at http://localhost:5000
# or, as on Render (threads and timeouts from gunicorn.conf.py):
# PORT=5000 gunicorn app:app
```

Serve the `docs` folder and open it in a browser:

```bash
python3 -m http.server 8000 --directory docs
# open http://localhost:8000
```

The page's script is made of JavaScript modules, which browsers load only over `http://`, so opening `docs/index.html` straight from the disk shows the page without anything working. VS Code Live Server works too. Make sure `API_BASE` in `docs/js/config.js` points to `http://localhost:5000`.

---

## Tests

The tests never contact apple.com: `tests/fakes/apple.py` stands in for it (and for the exchange-rate service), with switches for timeouts, outages, missing rates, retired products and so on.

| Suite | What it covers | Run it |
|-------|----------------|--------|
| API (`tests/api`, pytest) | Prices and the sanity floor, product look-up, caches, exchange rates, rate limits, the private status page, serving visitors in parallel, and a real gunicorn server with the production settings | `pytest` |
| Page (`tests/browser`, Playwright) | The page with the server's events played by the test: progress and wake-up messages, ranking and differences, sorting and filters, table and chart, links and history, the search box, CSV export, link previews, and how the page is put together (every module preloaded, no inline script, works under a strict Content-Security-Policy) | `npx playwright test` |
| End to end (`tests/browser/end-to-end.spec.js`) | The real page against the real API under gunicorn, with only apple.com faked | part of `npx playwright test` |

```bash
pip install -r requirements-dev.txt     # the API's packages plus pytest and ruff
pytest                                  # API tests (about 30 s)
ruff check .                            # lint

npm install                             # Playwright
npx playwright install chromium
npx playwright test                     # page and end-to-end tests; starts the servers it needs
npx playwright show-report              # after a failure: screenshots and a trace of each step
```

GitHub Actions runs lint, the API tests and the browser tests on every pull request and on every push to `main` (`.github/workflows/ci.yml`); a pull request shows a ✓ or ✗ for each. Dependabot opens a weekly pull request when a pinned package or action has a newer version.

---

## API Reference

### `GET /api/prices/stream?product=<name>` ⭐ Primary endpoint

Server-Sent Events stream. Pushes each country result as it completes — the browser receives and renders rows one by one without waiting for all 50 countries.

**Events:**

| Event | When | Payload |
|-------|------|---------|
| `searching` | Immediately on request | `{ product }` |
| `queued` | Only when the server is already fetching other searches; this one waits for a free slot (up to 45 s) | `{ message, maxWaitSeconds }` |
| `meta` | After slug is resolved | `{ product, slug, matchedName, substituted, category, total, rates, cached?, ageSeconds?, expiresInSeconds? }` — `rates` maps each listed currency to units per 1 USD; `matchedName` / `substituted` say which product was priced and whether it differs from the one asked for (see Slug Resolution); on a cache hit `ageSeconds` is how long ago the prices were fetched from Apple and `expiresInSeconds` is when they will be fetched again |
| `result` | As each country finishes | Full country price object (see below) |
| `done` | All countries complete | `{ product, cached? }` |
| `error` | Bad product name / API error / rate limit / Apple unreachable / server busy | `{ error: "message" }`, plus `rateLimited: true` and `retryAfterSeconds` when a limit was hit, or `temporary: true` and `retryAfterSeconds` when Apple could not be checked, no fetch slot came free in time, or the fetch broke off part-way |

**Example (curl):**
```bash
curl -N "https://apple-products-global-price-tracker.onrender.com/api/prices/stream?product=MacBook+Air"
```

---

### `GET /api/prices?product=<name>`

Blocking JSON endpoint. Waits for all countries to finish, then returns the full sorted result set. Useful for scripting/automation.

It runs the same search as the stream, so it makes the same checks and ends with the same messages. An error is `{ "error": "message" }` with these statuses:

| Status | When | Also in the body |
|--------|------|------------------|
| `400` | The `product` parameter is missing or longer than 80 characters | |
| `404` | Apple has no page for the product | |
| `429` | A rate limit was hit | `rateLimited: true`, `retryAfterSeconds` (also sent as `Retry-After`) |
| `503` | Apple did not answer the look-up, no fetch slot came free in time, or the fetch broke off part-way | `temporary: true`, `retryAfterSeconds` (also sent as `Retry-After`) |

**Example response:**
```json
{
  "product": "MacBook Air",
  "slug": "macbook-air",
  "matchedName": "MacBook Air",
  "substituted": false,
  "category": "mac",
  "ratesDate": "live",
  "rates": { "EUR": 0.92, "GBP": 0.78, "INR": 84.1 },
  "cached": false,
  "ageSeconds": 0,
  "expiresInSeconds": 21600,
  "results": [
    {
      "country": "United States",
      "flag": "🇺🇸",
      "available": true,
      "currency": "USD",
      "symbol": "$",
      "localPrice": 1099.0,
      "localPriceFormatted": "$1,099",
      "usdPrice": 1099.0,
      "url": "https://www.apple.com/macbook-air/"
    },
    {
      "country": "Belgium",
      "flag": "🇧🇪",
      "available": false,
      "reason": "Not available in this country",
      "url": "https://www.apple.com/be/macbook-air/"
    }
  ]
}
```

Results: available countries sorted cheapest-first, then unavailable countries alphabetically.

**No exchange rate.** If the exchange-rate service leaves a currency out (or sends a value that is not a positive number), that country is still listed with its own price, but `usdPrice` is `null` and it comes after the converted ones. It is never converted to $0.00. The page shows "No exchange rate" next to its price and does not rank it, chart it or count it as the cheapest. The summary, footer and CSV export say which countries this applies to. If the service is down altogether, every store's own price is shown and the page says prices can't be compared right now.

---

### `GET /api/health`

Returns `{"status": "ok"}` — for uptime monitoring.

---

### `GET /api/cache/status`

Returns the state of the three in-memory caches and the rate limits. The public view has totals only — it does not show what anyone searched for:

```json
{
  "details": "hidden — send the admin token to see search terms and product slugs",
  "exchange_rates": { "cached": true, "age_seconds": 142, "ttl_seconds": 1800, "expires_in": 1658 },
  "slug_cache": { "entries": 3, "max_entries": 500 },
  "results_cache": { "entries": 1, "max_entries": 200, "ttl_seconds": 21600, "ttl_seconds_incomplete": 300 },
  "rate_limits": {
    "requests_per_minute": 60,
    "apple_lookups_per_10_minutes": 20,
    "apple_lookups_per_10_minutes_all_visitors": 60,
    "apple_lookups_used_all_visitors": 4,
    "visitors_tracked": 2
  }
}
```

To see the search terms (`slug_cache.keys`), the cached products (`results_cache.slugs`) and how the server identified you (`you`), set an `ADMIN_TOKEN` environment variable on the server and send it with the request:

```bash
curl -H "X-Admin-Token: <your token>" https://apple-products-global-price-tracker.onrender.com/api/cache/status
```

`Authorization: Bearer <your token>` works too. If `ADMIN_TOKEN` is not set, the detailed view is never available.

---

## Abuse protection

One uncached search makes 100+ requests to apple.com from the server, so the price endpoints are rate limited:

| Limit | Default | Environment variable |
|-------|---------|----------------------|
| Requests per visitor (cached or not) | 60 per minute | `RATE_LIMIT_REQUESTS_PER_MIN` |
| Apple look-ups per visitor (a new product, or a name not seen before) | 20 per 10 minutes | `RATE_LIMIT_FETCHES_PER_10MIN` |
| Apple look-ups for all visitors together | 60 per 10 minutes | `RATE_LIMIT_GLOBAL_FETCHES_PER_10MIN` |

Set a variable to `0` to switch that limit off. Cached results never count as a look-up, so a visitor who is over the look-up limit can still open products that are already cached.

- `/api/prices` answers `429` with `{ "error", "rateLimited": true, "retryAfterSeconds" }` and a `Retry-After` header.
- `/api/prices/stream` sends an `error` event with the same payload, which the page shows as a message.
- `/api/health` is not limited (the page calls it on every load).

Visitors are told apart by the `CF-Connecting-IP` header (set by Cloudflare, which fronts Render), falling back to the first `X-Forwarded-For` address, then the connection address. The all-visitors limit does not depend on this, so it holds even if someone disguises their address. Counters are in memory, per process, and reset on restart.

Also capped: product names longer than 80 characters are rejected, the slug cache holds at most 500 names and the results cache at most 200 products (oldest dropped first).

### Configuring it (optional)

Nothing has to be configured: the limits above are on by default and `/api/cache/status` shows totals only. Everything below is optional and is done with environment variables on the server.

| Variable | What it does | If not set |
|----------|--------------|------------|
| `ADMIN_TOKEN` | Secret that unlocks the detailed view of `/api/cache/status` | Details are never shown, to anyone |
| `RATE_LIMIT_REQUESTS_PER_MIN` | Requests per visitor per minute | `60` |
| `RATE_LIMIT_FETCHES_PER_10MIN` | Apple look-ups per visitor per 10 minutes | `20` |
| `RATE_LIMIT_GLOBAL_FETCHES_PER_10MIN` | Apple look-ups for all visitors together per 10 minutes | `60` |
| `APPLE_MAX_CONNECTIONS` | Requests one search has open to apple.com at once, i.e. how many stores it fetches in parallel | `50` |
| `MAX_PARALLEL_FETCHES` | Searches that fetch from apple.com at the same time; others wait for a free slot (minimum 1) | `2` |
| `WEB_THREADS` | Requests the server handles at the same time (minimum 1) | `16` |

**Setting a variable on Render**

1. Open the service in the Render dashboard and go to **Environment**.
2. Add the variable name and value, then save. Render redeploys the service with the new value.
3. To undo, delete the variable and save again.

A limit set to `0` is switched off. A value that is not a whole number is ignored and the default is used.

**Choosing an `ADMIN_TOKEN`**

Use a long random value and keep it out of the repository. One way to make one:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Seeing the detailed status**

```bash
curl -H "X-Admin-Token: <your token>" https://apple-products-global-price-tracker.onrender.com/api/cache/status
```

With the right token the response also contains `slug_cache.keys` (what was searched for), `results_cache.slugs` (which products are cached and for how long) and `you`. Send the token in a header, not in the URL, so it does not end up in logs.

**Checking that visitors are told apart (do this once after deploying)**

The per-visitor limits only work if the server sees each visitor's own address. In the detailed status, look at `you`:

```json
"you": { "address": "203.0.113.24", "identified_by": "CF-Connecting-IP" }
```

- `address` should be your own public IP address (search the web for "what is my IP" to compare).
- `identified_by` should be `CF-Connecting-IP` on Render.
- If `address` is not yours, or `identified_by` is `connection`, every visitor is being counted as one and `client_id()` in `api/tracker/limits.py` needs adjusting for the host. Until then the all-visitors limit still protects the server.

---

## Caching

Three in-memory caches reduce latency and external HTTP calls:

| Cache | Key | TTL | What it stores |
|-------|-----|-----|----------------|
| Exchange rates | global | 30 min | USD conversion rates from open.er-api.com |
| Slug resolution | product name | depends on the answer (see below) | Resolved apple.com slug per product name |
| Price results | slug | 6 hours (5 min if incomplete) | Full 50-country result set |

On a cache hit for price results, the SSE stream replays cached rows as rapid-fire events — the browser still sees the same `searching → meta → result × N → done` flow, just near-instantly.

Price results are kept for 6 hours (`RESULTS_TTL` in `api/tracker/config.py`) because Apple changes prices rarely. Two safeguards go with the long lifetime:

- **Incomplete fetches are not kept for long.** If any country failed for a temporary reason (timeout, network error, rate limit, server error), any store's currency had no exchange rate, or no country returned a price at all, the result set is kept for only 5 minutes (`RESULTS_TTL_SHORT`) so it is retried soon. A clean "not sold in this country" (404) does not count as a failure.
- **Currency conversion does not age with the cache.** On a cache hit the USD prices and the `rates` table are recalculated from the current exchange rates (themselves refreshed every 30 min); only the local prices come from the cache.

The page shows how old cached prices are ("⚡ cached · prices from 2 h 5 min ago").

**How long a name look-up is remembered** depends on how sure the answer is, so that one Apple timeout cannot make a product "not found" (or pin it to the wrong page) until the server restarts:

| Outcome of the look-up | Kept for | Constant |
|------------------------|----------|----------|
| Found, and every check Apple was asked answered | life of the process | — |
| Found a fallback page while one of the checks failed | 5 minutes, then looked up again | `SLUG_TTL_UNSURE` |
| Not found, and every check answered | 1 hour (Apple adds products) | `SLUG_TTL_NOT_FOUND` |
| Could not tell — Apple timed out, errored or blocked the check | 1 minute, only to stop retry storms | `SLUG_TTL_FAILED` |

The last case is never reported as "not found". `/api/prices` answers `503` with `{ "error", "temporary": true, "retryAfterSeconds" }` and a `Retry-After` header; the stream sends the same payload as an `error` event, which the page shows as "Apple did not respond while looking up … Please try again in 60 seconds." Products that are already known keep working during such an outage, and their cached prices are still served. A failure of Apple's search-suggestions service alone does not count: it is only a hint, and the page checks decide.

> These are **in-memory** caches. They are cleared when the server restarts (including Render free-tier cold starts). Redis support can be added later for persistence across restarts.

---

## Serving several visitors at once

The API runs as one gunicorn process with a pool of threads, set in `api/gunicorn.conf.py`:

- **Visitors are served side by side.** Each request gets its own thread (16 by default, `WEB_THREADS`), so a search in progress does not hold anyone else up: cached results, health checks and other searches are answered meanwhile. Gunicorn's default worker, used before, served one request at a time.
- **Slow searches are not cut off.** With threads, gunicorn's `timeout` (120 s) only checks that the process is still alive; it does not limit how long a request may take. Before, a search still streaming after 30 s was cut off mid-way.
- **One process, on purpose.** The caches and rate-limit counters live in the process's memory, and a second process would have its own separate copies.
- **Two searches fetch from Apple at a time** (`MAX_PARALLEL_FETCHES`). Each one has up to 50 requests open to apple.com and holds those pages in memory, so on a small instance a burst of new searches is let through a couple at a time. A further search waits for a free slot while the page shows "Busy with other searches — yours starts in a moment…". If none comes free within 45 s, it gets a "busy, please try again" message (`/api/prices` answers `503` with `temporary: true` and a `Retry-After` header). When a waiting search gets its slot it checks the cache again, so if it was waiting behind a search for the same product it gets those results instead of fetching them again. Cached results never wait for a slot.
- **Closing the page does not waste a fetch.** A search that has started fetching finishes and stores its results in the cache, ready for the next visitor. A search still waiting for a slot gives up as soon as the visitor leaves.

---

## Slug Resolution

Apple's product URLs don't always match a simple `name → slug` conversion. The API resolves slugs in this order:

1. **Override table** — known products with non-obvious slugs, including older models that should lead to the current one (e.g. `"apple watch ultra 2"` → `apple-watch-ultra-4`). An entry is used only while Apple still serves a page for its slug (the product page, or the US buy page). Apple redirects retired product pages to the line-up page, so a stale entry is skipped and the steps below run instead.
2. **Direct probe** — try `apple.com/<slug>/` with redirect detection (rejects silent homepage redirects)
3. **Suggestions API** — query Apple's autocomplete endpoint and verify the returned slug
4. **Variations** — try `apple-<slug>`, truncated forms, numeric suffixes (`-2`, `-3`, etc.)

If none resolve, the API returns a clear error — it will not silently return 50 rows of "Price not found".

### When the result is not the product that was typed

Steps 1, 3 and 4 can land on a different product than the one asked for: an older model mapped to the current one, a long name cut down to a page that exists, or a number added. The API reports what it priced in every response:

- `matchedName` — the product priced, written as Apple writes it (`"Apple Watch Ultra 4"`)
- `substituted` — `true` when that is not the product typed. Differences in case, spacing, hyphens or a leading "Apple" do not count.

When `substituted` is true the page puts the matched name in the heading and shows a notice: *Showing prices for **Apple Watch Ultra 4** — the closest match found for "Apple Watch Ultra 2".* The exported CSV is named after the product priced.

The same care applies per country: if a store redirects the product's page to a different page (Apple sends products a country does not sell to the line-up page), that country is reported as "Not available in this country" rather than given whatever price the other page shows.

---

## How Prices Are Extracted

Apple embeds a JSON-LD `AggregateOffer` block in their `/shop/buy-<category>/<slug>` pages:

```json
{
  "@type": "AggregateOffer",
  "lowPrice": 1099.00,
  "priceCurrency": "USD"
}
```

This `lowPrice` is the **base model starting price** — present in static HTML (no JS execution needed). It matches the "From $X" price shown on Apple's product pages.

### Requests per search

A search has at most 50 requests open to `www.apple.com` at once — one per store (`APPLE_MAX_CONNECTIONS`). If Apple starts refusing requests, lower it with the environment variable of the same name; 10 is the old value.

**One connection pool.** All requests to apple.com and to the exchange-rate service run on one event loop in a background thread and share one `aiohttp` session (`api/tracker/web.py`). Connections, with their TLS sessions and DNS answers, are reused from a product look-up to the fetch that follows it and from one search to the next. Against a local HTTPS stand-in for apple.com, three searches in a row opened about 52 new connections each before this change; now the first opens 51 and the next two open none. Fetches run as tasks on that loop, so a search no longer starts a thread of its own.

Per store, the buy page is fetched first because it normally has the price. The larger product page (`apple.com/<cc>/<slug>/`) is fetched only if the buy page had no price, and no page is downloaded twice: what the product page answered (found, 404, redirected elsewhere, or failed) also decides between "Not available in this country" and "Price not found". That is one download for a store whose buy page has the price and two otherwise — about 70 for a typical product, 100 at most.

### Sanity floor

A page can also contain smaller numbers that are not the price — a monthly instalment, an accessory, a trade-in value — so a figure is only accepted if it is at least a minimum for that product family. The minimums are in US dollars (`get_min_price` in `api/tracker/prices.py`: iPhone 500, MacBook 800, AirTag 20, …).

Each store's price is in its own currency, so the minimum is converted with the current exchange rate before comparing (`local_min_price`), and applied with 20% room under it (`PRICE_FLOOR_SLACK`) for stores that price a product below the US price. For an iPhone that is $400 in the US, about 124 KWD in Kuwait and ₹33,600 in India.

Comparing the dollar figure directly, as before, went wrong in both directions: a real iPhone price of 245 KWD was rejected because 245 < 500, and an instalment of ₹6,908 a month was accepted because 6908 > 500. If a currency has no exchange rate the dollar figure is used unchanged, and the result set is kept for only 5 minutes so it is checked again once rates are back.

---

## Supported Countries

<!-- countries:start (written by scripts/sync_countries.py from api/tracker/countries.json) -->
50 Apple stores:

| Region | Countries |
|--------|-----------|
| Americas | 🇺🇸 United States · 🇨🇦 Canada · 🇲🇽 Mexico · 🇧🇷 Brazil · 🇨🇱 Chile · 🇨🇴 Colombia |
| Europe | 🇬🇧 United Kingdom · 🇩🇪 Germany · 🇫🇷 France · 🇳🇱 Netherlands · 🇪🇸 Spain · 🇮🇹 Italy · 🇦🇹 Austria · 🇮🇪 Ireland · 🇵🇹 Portugal · 🇸🇪 Sweden · 🇳🇴 Norway · 🇩🇰 Denmark · 🇵🇱 Poland · 🇹🇷 Turkey · 🇨🇿 Czech Republic · 🇭🇺 Hungary · 🇷🇴 Romania · 🇫🇮 Finland · 🇧🇪 Belgium · 🇱🇺 Luxembourg · 🇬🇷 Greece · 🇨🇭 Switzerland |
| Asia Pacific | 🇯🇵 Japan · 🇰🇷 South Korea · 🇭🇰 Hong Kong · 🇹🇼 Taiwan · 🇨🇳 China · 🇵🇭 Philippines · 🇹🇭 Thailand · 🇮🇳 India · 🇸🇬 Singapore · 🇲🇾 Malaysia · 🇦🇺 Australia · 🇳🇿 New Zealand · 🇻🇳 Vietnam · 🇮🇩 Indonesia |
| Middle East & Africa | 🇦🇪 United Arab Emirates · 🇸🇦 Saudi Arabia · 🇮🇱 Israel · 🇿🇦 South Africa · 🇰🇼 Kuwait · 🇶🇦 Qatar · 🇧🇭 Bahrain · 🇴🇲 Oman |
<!-- countries:end -->

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vanilla HTML/CSS/JS — no framework, no build step |
| Backend | Python 3.11 · Flask · aiohttp |
| Async | `asyncio` + `aiohttp` — all 50 country requests fire simultaneously |
| Streaming | Server-Sent Events (SSE) via Flask `stream_with_context` |
| Bridge | One `asyncio` event loop in a background thread, with one shared `aiohttp` session (`api/tracker/web.py`); request threads hand it work and read the rows through a `queue.Queue`. Both price endpoints run the same search (`api/tracker/search.py`) |
| Hosting | GitHub Pages (frontend) · Render free tier (backend) |
| Exchange rates | [open.er-api.com](https://open.er-api.com) |

---

## Notes

- Prices reflect the **base/entry-level configuration** of each product
- Some countries may not carry certain products (shown as "Not available in this country")
- Exchange rates are fetched live and may fluctuate
- Not affiliated with Apple Inc. — for personal/educational use only

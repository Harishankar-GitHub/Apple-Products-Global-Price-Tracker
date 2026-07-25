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
3. All 50 country requests fire **simultaneously** via `aiohttp` (async, single thread — no worker pool)
4. Each country result is pushed to the browser via **Server-Sent Events (SSE)** the moment it arrives — the table updates live
5. Prices are extracted from Apple's embedded JSON-LD `"lowPrice"` field — no JavaScript execution needed
6. Prices are converted to USD using live exchange rates from [open.er-api.com](https://open.er-api.com)
7. Results are ranked cheapest-first with animated FLIP transitions as the sort order changes

---

## Project Structure

```
apple-global-price-tracker/
├── docs/
│   └── index.html          # Single-file frontend (HTML + CSS + JS)
├── api/
│   ├── app.py              # Flask API — async price fetching + SSE streaming
│   ├── requirements.txt
│   └── render.yaml         # Render deployment config
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

### Step 2 — Configure the Frontend

In `docs/index.html`, set your deployed API URL:

```js
const API_BASE = "https://YOUR-API-URL.onrender.com"; // production
// const API_BASE = "http://localhost:5000";           // local dev
```

Comment out the production line for local development, uncomment before pushing.

### Step 3 — Enable GitHub Pages

1. Repo → **Settings → Pages**
2. Source: **Deploy from a branch** → Branch: `main` / Folder: `/docs`
3. Click **Save**

Your site: `https://<your-username>.github.io/<repo-name>/`

---

## Local Development

```bash
cd api
pip install -r requirements.txt
python app.py
# API at http://localhost:5000
```

Open `docs/index.html` directly in a browser or with VS Code Live Server.  
Make sure `API_BASE` in the HTML points to `http://localhost:5000`.

---

## API Reference

### `GET /api/prices/stream?product=<name>` ⭐ Primary endpoint

Server-Sent Events stream. Pushes each country result as it completes — the browser receives and renders rows one by one without waiting for all 50 countries.

**Events:**

| Event | When | Payload |
|-------|------|---------|
| `searching` | Immediately on request | `{ product }` |
| `meta` | After slug is resolved | `{ product, slug, category, total, cached? }` |
| `result` | As each country finishes | Full country price object (see below) |
| `done` | All countries complete | `{ product, cached? }` |
| `error` | Bad product name / API error | `{ error: "message" }` |

**Example (curl):**
```bash
curl -N "https://apple-products-global-price-tracker.onrender.com/api/prices/stream?product=MacBook+Air"
```

---

### `GET /api/prices?product=<name>`

Blocking JSON endpoint. Waits for all countries to finish, then returns the full sorted result set. Useful for scripting/automation.

**Example response:**
```json
{
  "product": "MacBook Air",
  "slug": "macbook-air",
  "category": "mac",
  "ratesDate": "live",
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

---

### `GET /api/health`

Returns `{"status": "ok"}` — for uptime monitoring.

---

### `GET /api/cache/status`

Returns current state of all three in-memory caches — useful for debugging on free-tier hosts.

```json
{
  "exchange_rates": {
    "cached": true,
    "age_seconds": 142,
    "ttl_seconds": 1800,
    "expires_in": 1658
  },
  "slug_cache": {
    "entries": 3,
    "keys": ["macbook air", "iphone 17", "mac mini"]
  },
  "results_cache": {
    "entries": 1,
    "slugs": {
      "macbook-air": { "age_seconds": 87, "expires_in": 213 }
    }
  }
}
```

---

## Caching

Three in-memory caches reduce latency and external HTTP calls:

| Cache | Key | TTL | What it stores |
|-------|-----|-----|----------------|
| Exchange rates | global | 30 min | USD conversion rates from open.er-api.com |
| Slug resolution | product name | process lifetime | Resolved apple.com slug per product name |
| Price results | slug | 5 min | Full 50-country result set |

On a cache hit for price results, the SSE stream replays cached rows as rapid-fire events — the browser still sees the same `searching → meta → result × N → done` flow, just near-instantly.

> These are **in-memory** caches. They are cleared when the server restarts (including Render free-tier cold starts). Redis support can be added later for persistence across restarts.

---

## Slug Resolution

Apple's product URLs don't always match a simple `name → slug` conversion. The API resolves slugs in this order:

1. **Override table** — known products with non-obvious slugs (e.g. `"apple watch ultra"` → `apple-watch-ultra-3`)
2. **Direct probe** — try `apple.com/<slug>/` with redirect detection (rejects silent homepage redirects)
3. **Suggestions API** — query Apple's autocomplete endpoint and verify the returned slug
4. **Variations** — try `apple-<slug>`, truncated forms, numeric suffixes (`-2`, `-3`, etc.)

If none resolve, the API returns a clear error — it will not silently return 50 rows of "Price not found".

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

---

## Supported Countries (50)

| Region | Countries |
|--------|-----------|
| Americas | 🇺🇸 US · 🇨🇦 Canada · 🇲🇽 Mexico · 🇧🇷 Brazil · 🇨🇱 Chile · 🇨🇴 Colombia |
| Europe | 🇬🇧 UK · 🇩🇪 Germany · 🇫🇷 France · 🇮🇹 Italy · 🇪🇸 Spain · 🇳🇱 Netherlands · 🇦🇹 Austria · 🇵🇹 Portugal · 🇮🇪 Ireland · 🇸🇪 Sweden · 🇳🇴 Norway · 🇩🇰 Denmark · 🇵🇱 Poland · 🇹🇷 Turkey · 🇨🇿 Czech Republic · 🇭🇺 Hungary · 🇷🇴 Romania · 🇫🇮 Finland · 🇧🇪 Belgium · 🇱🇺 Luxembourg · 🇬🇷 Greece · 🇨🇭 Switzerland |
| Asia Pacific | 🇯🇵 Japan · 🇨🇳 China · 🇭🇰 Hong Kong · 🇹🇼 Taiwan · 🇰🇷 South Korea · 🇸🇬 Singapore · 🇲🇾 Malaysia · 🇹🇭 Thailand · 🇮🇳 India · 🇦🇺 Australia · 🇳🇿 New Zealand · 🇵🇭 Philippines · 🇮🇩 Indonesia · 🇻🇳 Vietnam |
| Middle East & Africa | 🇦🇪 UAE · 🇸🇦 Saudi Arabia · 🇶🇦 Qatar · 🇰🇼 Kuwait · 🇧🇭 Bahrain · 🇴🇲 Oman · 🇮🇱 Israel · 🇿🇦 South Africa |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vanilla HTML/CSS/JS — no framework, no build step |
| Backend | Python 3.11 · Flask · aiohttp |
| Async | `asyncio` + `aiohttp` — all 50 country requests fire simultaneously |
| Streaming | Server-Sent Events (SSE) via Flask `stream_with_context` |
| Bridge | `queue.Queue` + background thread bridges async → sync SSE generator |
| Hosting | GitHub Pages (frontend) · Render free tier (backend) |
| Exchange rates | [open.er-api.com](https://open.er-api.com) |

---

## Notes

- Prices reflect the **base/entry-level configuration** of each product
- Some countries may not carry certain products (shown as "Not available in this country")
- Exchange rates are fetched live and may fluctuate
- Not affiliated with Apple Inc. — for personal/educational use only

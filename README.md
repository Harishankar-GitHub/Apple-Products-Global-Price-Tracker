# 🍎 Apple Products Global Price Tracker

Find the cheapest official price for any Apple product across 50+ country storefronts — with live exchange rates and direct links to apple.com.

## 🌐 Live Demo

Frontend (GitHub Pages):  
https://harishankar-github.github.io/Apple-Products-Global-Price-Tracker/

Backend API (Render):  
https://apple-products-global-price-tracker.onrender.com

![Apple Products Global Price Tracker UI](https://img.shields.io/badge/UI-GitHub%20Pages-blue?style=flat-square)
![API](https://img.shields.io/badge/API-Python%20Flask-green?style=flat-square)
![Backend Hosting](https://img.shields.io/badge/Backend-Render-black?style=flat-square)

---

## How It Works

1. You type a product name (e.g. "MacBook Air", "iPhone Air", "AirPods Pro")
2. The API discovers the correct apple.com URL slug dynamically — no hardcoded product list
3. It fetches Apple's `/shop/buy-<category>/<slug>` page for each country and extracts the `"lowPrice"` field from the embedded JSON-LD structured data — the same starting price Apple shows on their site
4. Prices are converted to USD using live exchange rates from [open.er-api.com](https://open.er-api.com)
5. Results are ranked cheapest-first and displayed with direct links to each country's Apple store

---

## Project Structure

```
apple-global-price-tracker/
├── docs/                   # GitHub Pages frontend (static HTML/CSS/JS)
│   └── index.html
├── api/                    # Python Flask backend
│   ├── app.py
│   ├── requirements.txt
│   └── render.yaml         # One-click Render deployment config
├── apple_price_finder.py   # Standalone CLI script (no server needed)
└── README.md
```

---

## Deployment

The app has two parts: a **static frontend** (GitHub Pages) and a **Python API** (any free hosting service). Both deploy from this repo.

### Step 1 — Deploy the API (Render — free tier)

1. Fork or push this repo to your GitHub account
2. Go to [render.com](https://render.com) (one of the free platforms to host backend) and sign in with GitHub
3. Click **New → Web Service** → select this repo
4. Set the **Root Directory** to `api`
5. Render auto-detects the `render.yaml` — click **Deploy**
6. Once deployed, copy your service URL, e.g. `https://apple-products-global-price-tracker.onrender.com`

### Step 2 — Configure the Frontend

Open `docs/index.html` and replace the API URL on this line:

```js
const API_BASE = "https://YOUR-API-URL.onrender.com";
```

with your actual Render URL from Step 1.

### Step 3 — Enable GitHub Pages

1. Go to your repo → **Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` / Folder: `/docs`
4. Click **Save**

Your site will be live at `https://<your-username>.github.io/<repo-name>/`

---

## Local Development

### Run the API locally

```bash
cd api
pip install -r requirements.txt
python app.py
# API running at http://localhost:5000
```

### Run the frontend locally

In `docs/index.html`, temporarily change:
```js
const API_BASE = "http://localhost:5000";
```

Then open `docs/index.html` in your browser (or use Live Server in VS Code).

---

## API Reference

### `GET /api/prices?product=<name>`

Returns prices for all supported countries.

**Example:**
```
GET /api/prices?product=MacBook+Air
```

**Response:**
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

Results are sorted: available countries first (cheapest USD first), then unavailable countries alphabetically.

### `GET /api/health`

Returns `{"status": "ok"}` — use for uptime monitoring.

---

## Supported Countries (50+)

| Region | Countries |
|--------|-----------|
| Americas | 🇺🇸 US · 🇨🇦 Canada · 🇲🇽 Mexico · 🇧🇷 Brazil · 🇨🇱 Chile · 🇨🇴 Colombia |
| Europe | 🇬🇧 UK · 🇩🇪 Germany · 🇫🇷 France · 🇮🇹 Italy · 🇪🇸 Spain · 🇳🇱 Netherlands · 🇦🇹 Austria · 🇵🇹 Portugal · 🇮🇪 Ireland · 🇸🇪 Sweden · 🇳🇴 Norway · 🇩🇰 Denmark · 🇵🇱 Poland · 🇹🇷 Turkey · 🇨🇿 Czech Republic · 🇭🇺 Hungary · 🇷🇴 Romania · 🇫🇮 Finland · 🇧🇪 Belgium · 🇱🇺 Luxembourg · 🇬🇷 Greece · 🇨🇭 Switzerland |
| Asia Pacific | 🇯🇵 Japan · 🇨🇳 China · 🇭🇰 Hong Kong · 🇹🇼 Taiwan · 🇰🇷 South Korea · 🇸🇬 Singapore · 🇲🇾 Malaysia · 🇹🇭 Thailand · 🇮🇳 India · 🇦🇺 Australia · 🇳🇿 New Zealand · 🇵🇭 Philippines · 🇮🇩 Indonesia · 🇻🇳 Vietnam |
| Middle East & Africa | 🇦🇪 UAE · 🇸🇦 Saudi Arabia · 🇶🇦 Qatar · 🇰🇼 Kuwait · 🇧🇭 Bahrain · 🇴🇲 Oman · 🇮🇱 Israel · 🇿🇦 South Africa |

---

## How Prices Are Extracted

Apple's website is fully JavaScript-rendered — standard web scraping returns no prices. This tool uses a different approach:

Apple embeds a JSON-LD `AggregateOffer` block in the HTML of their `/shop/buy-<category>/<slug>` pages:

```json
{
  "@type": "AggregateOffer",
  "lowPrice": 1099.00,
  "priceCurrency": "USD"
}
```

This `lowPrice` field is the **base model starting price** — consistent, accurate, and present in the static HTML (no JS execution needed). It's the same number Apple shows as "From $X" on their product pages.

---

## Notes

- Prices reflect the **base/entry-level configuration** of each product
- Some countries may not carry certain products (shown as "Not available")
- Exchange rates are fetched live and may fluctuate
- This tool is not affiliated with Apple Inc.
- For personal/educational use only

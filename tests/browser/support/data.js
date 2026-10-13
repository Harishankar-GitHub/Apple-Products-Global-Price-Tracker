// Price data for the page tests: what the API would send for one product.

// name, flag, currency, symbol, units per USD, price relative to the US
const COUNTRIES = [
  ['United States', '🇺🇸', 'USD', '$', 1, 1.00], ['Japan', '🇯🇵', 'JPY', '¥', 150, 0.97],
  ['Canada', '🇨🇦', 'CAD', 'CA$', 1.38, 1.02], ['South Korea', '🇰🇷', 'KRW', '₩', 1380, 1.08],
  ['Hong Kong', '🇭🇰', 'HKD', 'HK$', 7.8, 0.99], ['Taiwan', '🇹🇼', 'TWD', 'NT$', 32, 1.05],
  ['United Arab Emirates', '🇦🇪', 'AED', 'AED', 3.67, 1.04], ['China', '🇨🇳', 'CNY', '¥', 7.2, 1.03],
  ['Thailand', '🇹🇭', 'THB', '฿', 35, 1.07], ['India', '🇮🇳', 'INR', '₹', 84, 1.19],
  ['Singapore', '🇸🇬', 'SGD', 'S$', 1.33, 1.09], ['Malaysia', '🇲🇾', 'MYR', 'RM', 4.4, 1.01],
  ['Australia', '🇦🇺', 'AUD', 'A$', 1.52, 1.06], ['New Zealand', '🇳🇿', 'NZD', 'NZ$', 1.66, 1.12],
  ['United Kingdom', '🇬🇧', 'GBP', '£', 0.78, 1.28], ['Germany', '🇩🇪', 'EUR', '€', 0.92, 1.30],
  ['France', '🇫🇷', 'EUR', '€', 0.92, 1.30], ['Netherlands', '🇳🇱', 'EUR', '€', 0.92, 1.31],
  ['Spain', '🇪🇸', 'EUR', '€', 0.92, 1.30], ['Italy', '🇮🇹', 'EUR', '€', 0.92, 1.33],
  ['Ireland', '🇮🇪', 'EUR', '€', 0.92, 1.32], ['Sweden', '🇸🇪', 'SEK', 'kr', 10.4, 1.36],
  ['Norway', '🇳🇴', 'NOK', 'kr', 10.8, 1.34], ['Denmark', '🇩🇰', 'DKK', 'kr', 6.9, 1.38],
  ['Poland', '🇵🇱', 'PLN', 'zł', 3.9, 1.35], ['Turkey', '🇹🇷', 'TRY', '₺', 34, 1.72],
  ['Mexico', '🇲🇽', 'MXN', 'MX$', 19, 1.22], ['Brazil', '🇧🇷', 'BRL', 'R$', 5.6, 1.95],
  ['Switzerland', '🇨🇭', 'CHF', 'CHF', 0.86, 1.16], ['Vietnam', '🇻🇳', 'VND', '₫', 25000, 1.05],
];
const UNAVAILABLE = [['Israel', '🇮🇱'], ['South Africa', '🇿🇦'], ['Romania', '🇷🇴'], ['Greece', '🇬🇷'], ['Kuwait', '🇰🇼']];

const RATES = Object.fromEntries(COUNTRIES.map(c => [c[2], c[4]]));
RATES.ILS = 3.7;
RATES.KWD = 0.31;

/**
 * Rows for every country, cheapest first as the API sends them.
 * @param {object} [options]
 * @param {number} [options.base]      US price
 * @param {object} [options.usd]       country → usdPrice to send instead (null, 0, -5, or undefined to leave it out)
 * @param {string[]} [options.noPrice] countries reported without a price
 */
function rows({ base = 999, usd = {}, noPrice = [] } = {}) {
  const out = COUNTRIES.map(([country, flag, currency, symbol, rate, mult]) => {
    if (noPrice.includes(country)) {
      return { country, flag, available: false, reason: 'Price not found', url: 'https://www.apple.com/xx/macbook-air/' };
    }
    const local = Math.round(Math.round(base * mult * 100) / 100 * rate);
    const row = { country, flag, available: true, currency, symbol, localPrice: local,
      localPriceFormatted: symbol + local.toLocaleString('en-US'), usdPrice: Math.round(local / rate * 100) / 100,
      url: `https://www.apple.com/${country.slice(0, 2).toLowerCase()}/macbook-air/` };
    if (country in usd) {
      if (usd[country] === undefined) delete row.usdPrice;
      else row.usdPrice = usd[country];
    }
    return row;
  });
  UNAVAILABLE.forEach(([country, flag]) => out.push({ country, flag, available: false, reason: 'Price not found',
    url: 'https://www.apple.com/xx/macbook-air/' }));
  return out;
}

/** The USD price the rows above give a country. */
const usdOf = (country, base = 999) => rows({ base }).find(r => r.country === country).usdPrice;

/** Rates without some currencies (as when the exchange-rate service leaves them out). */
const ratesWithout = (...currencies) => Object.fromEntries(Object.entries(RATES).filter(([c]) => !currencies.includes(c)));

module.exports = { COUNTRIES, UNAVAILABLE, RATES, rows, usdOf, ratesWithout };

// Reference data: the countries (region, currency) and the product names offered as you type.

// Country names must match the API's COUNTRIES table exactly.
const AM = "Americas", EU = "Europe", AP = "Asia Pacific", ME = "Middle East & Africa";
export const COUNTRY_INFO = {
  "United States":        { cc: "US", region: AM, cur: "USD" },
  "Canada":               { cc: "CA", region: AM, cur: "CAD" },
  "Mexico":               { cc: "MX", region: AM, cur: "MXN" },
  "Brazil":               { cc: "BR", region: AM, cur: "BRL" },
  "Chile":                { cc: "CL", region: AM, cur: "CLP" },
  "Colombia":             { cc: "CO", region: AM, cur: "COP" },

  "United Kingdom":       { cc: "GB", region: EU, cur: "GBP" },
  "Germany":              { cc: "DE", region: EU, cur: "EUR" },
  "France":               { cc: "FR", region: EU, cur: "EUR" },
  "Netherlands":          { cc: "NL", region: EU, cur: "EUR" },
  "Spain":                { cc: "ES", region: EU, cur: "EUR" },
  "Italy":                { cc: "IT", region: EU, cur: "EUR" },
  "Austria":              { cc: "AT", region: EU, cur: "EUR" },
  "Ireland":              { cc: "IE", region: EU, cur: "EUR" },
  "Portugal":             { cc: "PT", region: EU, cur: "EUR" },
  "Sweden":               { cc: "SE", region: EU, cur: "SEK" },
  "Norway":               { cc: "NO", region: EU, cur: "NOK" },
  "Denmark":              { cc: "DK", region: EU, cur: "DKK" },
  "Poland":               { cc: "PL", region: EU, cur: "PLN" },
  "Turkey":               { cc: "TR", region: EU, cur: "TRY" },
  "Czech Republic":       { cc: "CZ", region: EU, cur: "CZK" },
  "Hungary":              { cc: "HU", region: EU, cur: "HUF" },
  "Romania":              { cc: "RO", region: EU, cur: "RON" },
  "Finland":              { cc: "FI", region: EU, cur: "EUR" },
  "Belgium":              { cc: "BE", region: EU, cur: "EUR" },
  "Luxembourg":           { cc: "LU", region: EU, cur: "EUR" },
  "Greece":               { cc: "GR", region: EU, cur: "EUR" },
  "Switzerland":          { cc: "CH", region: EU, cur: "CHF" },

  "Japan":                { cc: "JP", region: AP, cur: "JPY" },
  "South Korea":          { cc: "KR", region: AP, cur: "KRW" },
  "Hong Kong":            { cc: "HK", region: AP, cur: "HKD" },
  "Taiwan":               { cc: "TW", region: AP, cur: "TWD" },
  "China":                { cc: "CN", region: AP, cur: "CNY" },
  "Philippines":          { cc: "PH", region: AP, cur: "PHP" },
  "Thailand":             { cc: "TH", region: AP, cur: "THB" },
  "India":                { cc: "IN", region: AP, cur: "INR" },
  "Singapore":            { cc: "SG", region: AP, cur: "SGD" },
  "Malaysia":             { cc: "MY", region: AP, cur: "MYR" },
  "Australia":            { cc: "AU", region: AP, cur: "AUD" },
  "New Zealand":          { cc: "NZ", region: AP, cur: "NZD" },
  "Vietnam":              { cc: "VN", region: AP, cur: "VND" },
  "Indonesia":            { cc: "ID", region: AP, cur: "IDR" },

  "United Arab Emirates": { cc: "AE", region: ME, cur: "AED" },
  "Saudi Arabia":         { cc: "SA", region: ME, cur: "SAR" },
  "Israel":               { cc: "IL", region: ME, cur: "ILS" },
  "South Africa":         { cc: "ZA", region: ME, cur: "ZAR" },
  "Kuwait":               { cc: "KW", region: ME, cur: "KWD" },
  "Qatar":                { cc: "QA", region: ME, cur: "QAR" },
  "Bahrain":              { cc: "BH", region: ME, cur: "BHD" },
  "Oman":                 { cc: "OM", region: ME, cur: "OMR" },
};
export const REGIONS = [AM, EU, AP, ME];
export const COUNTRY_NAMES = Object.keys(COUNTRY_INFO).sort((a, b) => a.localeCompare(b));
export const CURRENCIES = [...new Set(Object.values(COUNTRY_INFO).map(c => c.cur))].sort();

// Product names offered as you type (Apple's line-up, October 2026).
export const PRODUCTS = [
  "iPhone 18 Pro", "iPhone Air", "iPhone Duo", "iPhone 17", "iPhone 17e", "iPhone 16",
  "MacBook Air", "MacBook Pro", "MacBook Neo", "iMac", "Mac mini", "Mac Studio", "Studio Display",
  "iPad", "iPad mini", "iPad Air", "iPad Pro",
  "Apple Watch Series 12", "Apple Watch Ultra 4", "Apple Watch SE 3",
  "AirPods 5", "AirPods Pro", "AirPods Max",
  "Apple TV 4K", "HomePod mini", "Apple Vision Pro", "AirTag",
];

export function info(country) { return COUNTRY_INFO[country] || null; }

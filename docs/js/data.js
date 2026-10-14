// Reference data: the countries (region, currency) and the product names offered as you type.
// The countries come from docs/js/countries.js, a copy of api/tracker/countries.json.

import TABLE from "./countries.js";

// country → { cc: ISO code, region, cur: currency }, from the table the API uses too.
export const COUNTRY_INFO = Object.fromEntries(TABLE.countries.map(c =>
  [c.name, { cc: c.code, region: c.region, cur: c.currency }]));
export const REGIONS = TABLE.regions;
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

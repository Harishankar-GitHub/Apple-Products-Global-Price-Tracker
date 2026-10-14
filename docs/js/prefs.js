// Saved preferences (per browser, in localStorage): home country, currency, pinned countries,
// recent searches and the chosen view.
import { COUNTRY_INFO, COUNTRY_NAMES, CURRENCIES } from "./data.js";

const STORE_KEY = "apgt:prefs:v1";
export const MAX_RECENT = 6;

function guessHome() {
  const langs = navigator.languages && navigator.languages.length
    ? navigator.languages : [navigator.language || ""];
  for (const l of langs) {
    const cc = (String(l).split("-")[1] || "").toUpperCase();
    const hit = COUNTRY_NAMES.find(n => COUNTRY_INFO[n].cc === cc);
    if (hit) return hit;
  }
  return "United States";
}

export const VIEWS = ["both", "table", "chart"];
function loadPrefs() {
  const base = { home: guessHome(), currency: null, pinned: [], recent: [], view: "both" };
  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
    if (saved && typeof saved === "object")
      Object.keys(base).forEach(k => { if (k in saved) base[k] = saved[k]; });
  } catch (_) { /* storage blocked or corrupt — defaults are fine */ }
  if (!COUNTRY_INFO[base.home]) base.home = guessHome();
  if (base.currency && !CURRENCIES.includes(base.currency)) base.currency = null;
  if (!VIEWS.includes(base.view)) base.view = "both";
  base.pinned = Array.isArray(base.pinned) ? base.pinned.filter(n => COUNTRY_INFO[n]) : [];
  base.recent = Array.isArray(base.recent)
    ? base.recent.filter(s => typeof s === "string" && s.trim()).slice(0, MAX_RECENT) : [];
  return base;
}
export function savePrefs() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(prefs)); } catch (_) {}
}
export const prefs = loadPrefs();

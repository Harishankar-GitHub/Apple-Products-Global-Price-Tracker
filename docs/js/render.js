// Drawing the results: the table, the chart and the summary, at most every half second while
// rows stream in, plus the controls' pressed states.
import { renderChart } from "./chart.js";
import { info } from "./data.js";
import { $ } from "./dom.js";
import { prefs } from "./prefs.js";
import { state } from "./state.js";
import { updateSummary } from "./summary.js";
import { renderTable, showNoPrices } from "./table.js";
import { buildView, visibleItems } from "./view.js";

// "Side by side" needs room; on narrower screens it falls back to the table.
export const wideQuery = window.matchMedia("(min-width: 1000px)");
export function effectiveView() {
  return prefs.view === "both" && !wideQuery.matches ? "table" : prefs.view;
}

// Table redraws while results stream in. The first result is drawn at once;
// after that the table is redrawn at most every RENDER_INTERVAL_MS however
// fast results arrive. (It used to wait for a pause in results, and every new
// result restarted the wait, so a quick burst postponed the first rows.)
// The interval matches the 0.45 s row-move animation, so a re-sort finishes
// before the next one starts. `immediate` (search finished) draws straight away.
const RENDER_INTERVAL_MS = 500;
let renderTimer  = null;
let lastRenderAt = 0;
export function scheduleRender(immediate) {
  if (immediate) { cancelScheduledRender(); drawNow(); return; }
  if (renderTimer !== null) return;               // a redraw is already booked
  const wait = Math.max(0, lastRenderAt + RENDER_INTERVAL_MS - Date.now());
  renderTimer = setTimeout(() => { renderTimer = null; drawNow(); }, wait);
}
export function cancelScheduledRender() {
  clearTimeout(renderTimer);
  renderTimer = null;
}
function drawNow() {
  lastRenderAt = Date.now();
  renderAll();
}

// A new search draws its first rows at once.
export function restartRendering() {
  cancelScheduledRender();
  lastRenderAt = 0;
}

export function renderAll() {
  if (!state.allResults.length) return;
  const view = buildView();
  const rows = visibleItems(view);
  updateSummary(view);
  syncControls(view);

  // Search finished and no country returned a price: say so in one full-width
  // panel instead of an empty table next to an empty chart. With "Show
  // unavailable" ticked the table lists what each country returned.
  if (state.activeSource === null && view.priced.length === 0) {
    $("views").classList.remove("split");
    $("chartView").style.display = "none";
    $("chartView").innerHTML = "";
    $("results").style.display = "";
    if (rows.length || view.listed.length) renderTable(view, rows); else showNoPrices();
    return;
  }

  renderTable(view, rows);
  renderChart(view, rows);
  const v = effectiveView();
  $("views").classList.toggle("split", v === "both");
  $("results").style.display   = v === "chart" ? "none" : "";
  $("chartView").style.display = v === "table" ? "none" : "block";
}

export function syncControls(view) {
  const home = info(prefs.home);
  const opt  = $("currencySelect").querySelector('option[value=""]');
  if (opt && home) opt.textContent = `${home.cur} (home)`;
  document.querySelectorAll("#regionChips .seg-btn").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.region === state.regionFilter)));
  document.querySelectorAll("#viewToggle .seg-btn").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.view === effectiveView())));
}

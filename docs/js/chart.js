// The chart: how much more each country costs than the cheapest.
import { $, esc } from "./dom.js";
import { fmtMoney, fmtPct } from "./format.js";

export function renderChart(view, rows) {
  const el = $("chartView");
  const items = rows.filter(i => i.value !== null);
  const left  = rows.filter(i => i.r.available && i.value === null);   // priced, but no exchange rate
  if (!items.length || !view.cheapest) {
    // Filters hide every priced country, or no price has arrived yet.
    el.innerHTML = view.priced.length
      ? `<p class="empty-note">No prices to chart for these filters.</p>` : "";
    return;
  }
  const cheapestName = view.cheapest.r.country;
  // Bars start at the cheapest price (zero difference) and grow with the extra cost.
  const maxPct = Math.max(1, ...items.map(i => i.diffPct));

  const bars = items.map(i => {
    const width = i.isCheapest ? 0 : (i.diffPct / maxPct) * 100;
    const delta = i.isCheapest
      ? "Cheapest"
      : `+${fmtMoney(i.diff, view.cur)} (+${fmtPct(i.diffPct)})`;
    const tip = i.isCheapest
      ? `${i.r.country}: ${fmtMoney(i.value, view.cur)} — the cheapest`
      : `${i.r.country}: ${fmtMoney(i.value, view.cur)} — ${delta} vs ${cheapestName}`;
    return `
      <div class="chart-row${i.isHome ? " is-home" : ""}" role="listitem" title="${esc(tip)}">
        <div class="chart-label">
          <span class="flag">${esc(i.r.flag)}</span>
          <span class="chart-name">${esc(i.r.country)}</span>
          ${i.isHome ? '<span class="badge-home">Home</span>' : ""}
        </div>
        <div class="chart-track">
          <span class="chart-axis" style="left:0%"></span>
          <span class="chart-bar ${i.isCheapest ? "same" : "more"}" style="left:0%;width:${width}%"></span>
        </div>
        <div class="chart-value">
          <span class="chart-price">${esc(fmtMoney(i.value, view.cur))}</span>
          <span class="chart-delta">${esc(delta)}</span>
        </div>
      </div>`;
  }).join("");

  el.innerHTML = `
    <div class="chart-card">
      <div class="chart-head">
        <div class="chart-title">Extra cost vs the cheapest (${esc(cheapestName)})</div>
      </div>
      <div class="chart-rows" role="list" aria-label="Extra cost over the cheapest price, by country">${bars}</div>
      <p class="chart-foot">${items.length} countries · listed prices converted to ${esc(view.cur)}${
        left.length ? ` · not shown, no exchange rate: ${esc(left.map(i => i.r.country).join(", "))}` : ""}</p>
    </div>`;
}

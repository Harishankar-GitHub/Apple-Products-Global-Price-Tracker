// CSV export of the rows currently shown.
import { safeUrl } from "./dom.js";
import { isNum } from "./format.js";
import { state } from "./state.js";
import { buildView, visibleItems } from "./view.js";

function csvCell(v) {
  let s = v === null || v === undefined ? "" : String(v);
  if (/^[=+\-@\t\r]/.test(s) && !/^[+-]?\d+(\.\d+)?$/.test(s)) s = "'" + s; // spreadsheet formula guard
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
function buildCsv() {
  const view = buildView();
  const rows = visibleItems(view);
  const round2  = n => (isNum(n) ? Math.round(n * 100) / 100 : "");
  const header = ["Rank", "Country", "Region", "Pinned", "Local currency", "Listed local price",
    `Price (${view.cur})`, "Listed price (USD)",
    `More than cheapest (${view.cur})`, "More than cheapest (%)", "Status", "Store URL"];
  const lines = rows.map(i => [
    i.value !== null ? i.rank : "",
    i.r.country,
    i.c ? i.c.region : "",
    i.pinned ? "yes" : "",
    i.r.available ? i.r.currency : (i.c ? i.c.cur : ""),
    i.r.available ? i.r.localPrice : "",
    round2(i.value),
    i.r.available ? round2(i.usd) : "",              // null (empty) when there is no usable rate
    round2(i.diff),
    isNum(i.diffPct) ? Math.round(i.diffPct * 10) / 10 : "",
    i.r.available ? (i.value === null ? "Available (no exchange rate)" : "Available") : (i.r.reason || "Unavailable"),
    safeUrl(i.r.url),
  ]);
  return [header, ...lines].map(l => l.map(csvCell).join(",")).join("\r\n") + "\r\n";
}
export function exportCsv() {
  if (!state.allResults.length) return;
  // Named after the product that was priced, which may differ from what was typed.
  const slug = (state.productSlug || state.productName).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "apple";
  const blob = new Blob(["﻿" + buildCsv()], { type: "text/csv;charset=utf-8" }); // BOM for Excel
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${slug}-prices-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

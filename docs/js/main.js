// Starts the page: connects the controls to the code, sends the wake-up ping, and runs a
// search from a shared link.
import { initControls, setSort, togglePin } from "./controls.js";
import { exportCsv } from "./csv.js";
import { $ } from "./dom.js";
import { copyLink, queryFromUrl } from "./links.js";
import { VIEWS, prefs, savePrefs } from "./prefs.js";
import { renderAll, syncControls, wideQuery } from "./render.js";
import { clearInput, clearRecent, closeSuggest, highlightedSuggestion, moveSuggest, openSuggest, suggestionsOpen } from "./search-box.js";
import { quickSearch, resetToLanding, search } from "./search.js";
import { state } from "./state.js";
import { wakeServer } from "./wake.js";

const productInput = $("productInput");

$("clearBtn").addEventListener("click", clearInput);
$("searchBtn").addEventListener("click", () => search());
$("quickSearches").addEventListener("click", e => {
  const chip = e.target.closest("[data-quick]");
  if (chip) quickSearch(chip.dataset.quick);
});
$("copyLinkBtn").addEventListener("click", copyLink);
$("exportCsvBtn").addEventListener("click", exportCsv);
$("filterInput").addEventListener("input", renderAll);
$("sortSelect").addEventListener("change", renderAll);
$("showUnavail").addEventListener("change", renderAll);

productInput.addEventListener("input", function () {
  $("clearBtn").style.display = this.value.length ? "flex" : "none";
  openSuggest();
});
productInput.addEventListener("keydown", e => {
  if (e.key === "ArrowDown")      { e.preventDefault(); if (!suggestionsOpen()) openSuggest(); moveSuggest(1); }
  else if (e.key === "ArrowUp")   { e.preventDefault(); moveSuggest(-1); }
  else if (e.key === "Escape")    { closeSuggest(); }
  else if (e.key === "Enter") {
    const highlighted = highlightedSuggestion();
    if (highlighted) productInput.value = highlighted;
    search();
  }
});
productInput.addEventListener("blur", () => setTimeout(closeSuggest, 120));
// mousedown (not click) so the choice lands before the input's blur closes the list
$("suggestList").addEventListener("mousedown", e => {
  const li = e.target.closest("[data-suggest]");
  if (!li) return;
  e.preventDefault();
  quickSearch(li.dataset.suggest);
});

$("recentWrap").addEventListener("click", e => {
  if (e.target.id === "clearRecentBtn") { clearRecent(); return; }
  const chip = e.target.closest("[data-recent]");
  if (chip) quickSearch(chip.dataset.recent);
});

$("homeSelect").addEventListener("change", e => { prefs.home = e.target.value; savePrefs(); renderAll(); syncControls(null); });
$("currencySelect").addEventListener("change", e => { prefs.currency = e.target.value || null; savePrefs(); renderAll(); });

$("regionChips").addEventListener("click", e => {
  const b = e.target.closest("[data-region]");
  if (!b) return;
  state.regionFilter = b.dataset.region;
  renderAll();
  syncControls(null);
});
$("viewToggle").addEventListener("click", e => {
  const b = e.target.closest("[data-view]");
  if (!b) return;
  if (!VIEWS.includes(b.dataset.view)) return;
  prefs.view = b.dataset.view;
  savePrefs();
  renderAll();
  syncControls(null);
});
wideQuery.addEventListener("change", () => { renderAll(); syncControls(null); });
$("results").addEventListener("click", e => {
  const b = e.target.closest("[data-pin]");
  if (b) togglePin(b.dataset.pin);
  const th = e.target.closest("th[data-sort]");           // clicking a column heading sorts by it
  if (th) setSort(...th.dataset.sort.split(" "));
});

window.addEventListener("popstate", () => {
  const q = queryFromUrl();
  if (q) {
    productInput.value = q;
    $("clearBtn").style.display = "flex";
    search({ fromHistory: true });
  } else {
    resetToLanding();
  }
});

initControls();
wakeServer();

// A shared link (?q=MacBook+Air) runs its search straight away.
(function runSharedSearch() {
  const q = queryFromUrl();
  if (!q) return;
  productInput.value = q;
  $("clearBtn").style.display = "flex";
  search({ fromHistory: true });
})();

// A search: the stream of events from the API and what the page does with each one.
import { API_BASE } from "./config.js";
import { $ } from "./dom.js";
import { fmtDuration, isNum } from "./format.js";
import { BASE_TITLE, writeUrl } from "./links.js";
import { cancelScheduledRender, restartRendering, scheduleRender } from "./render.js";
import { closeSuggest, rememberSearch } from "./search-box.js";
import { state } from "./state.js";
import { showMatchNote } from "./summary.js";
import { clearRows, showSkeleton } from "./table.js";
import { startWaitingForServer, stopWaitingForServer } from "./wake.js";

// ── Quick search ─────────────────────────────────────────────────────────
export function quickSearch(name) {
  $("productInput").value = name;
  $("clearBtn").style.display = "flex";
  search();
}

// ── Main search ───────────────────────────────────────────────────────────
// opts.fromHistory: the search came from the URL (page load or back/forward),
// so the address bar is already right and must not get a new history entry.
export function search(opts) {
  const fromHistory = !!(opts && opts.fromHistory);
  const input = $("productInput");
  const query = input.value.trim();
  if (!query) { input.focus(); return; }

  closeSuggest();
  if (state.activeSource) { state.activeSource.close(); state.activeSource = null; }
  restartRendering();
  writeUrl(query, fromHistory);
  document.title = `${query} — ${BASE_TITLE}`;

  const btn = $("searchBtn");
  btn.disabled = true;
  btn.textContent = "Searching…";

  // Reset state
  state.allResults     = [];
  state.productName    = query;
  state.totalCountries = 0;
  state.receivedCount  = 0;
  state.cacheExpiresAt = null;
  state.cacheAgeMs     = null;
  state.fetchedAt      = null;
  state.serverRates    = null;
  clearRows();

  $("status").innerHTML        = "";
  $("results").innerHTML       = "";
  $("chartView").innerHTML     = "";
  $("chartView").style.display = "none";
  $("views").classList.remove("split");
  $("controls").style.display  = "none";
  $("progressWrap").style.display = "block";
  $("progressLabel").textContent  = `Resolving "${query}"…`;
  $("progressCount").textContent  = "";
  $("progressFill").style.width   = "0%";
  $("progressBar").classList.add("indeterminate");   // until the first price arrives

  // Reset summary — show immediately with dashes (item 6)
  $("summaryProduct").textContent = `🍎 ${query}`;
  $("summaryFound").textContent   = "—";
  $("summaryCheapest").textContent= "—";
  $("summaryMostExp").textContent = "—";
  $("summaryHome").textContent    = "—";
  $("summaryNote").textContent    = "";
  state.productSlug = "";
  state.shownName   = query;
  showMatchNote(null);
  const sumEl = $("summary");
  sumEl.style.display = "block";
  // small tick so display:block is painted before we add .visible
  requestAnimationFrame(() => sumEl.classList.add("visible"));

  // Hide cache badge
  $("cacheBadge").classList.remove("visible");

  // Show skeleton table (item 3)
  showSkeleton();

  const url = `${API_BASE}/api/prices/stream?product=${encodeURIComponent(query)}`;
  const es  = new EventSource(url);
  state.activeSource = es;
  startWaitingForServer();

  es.addEventListener("searching", () => {
    stopWaitingForServer();           // first reply: the server is awake
    $("progressLabel").textContent = `Resolving "${query}" on apple.com…`;
  });

  // The server is fetching other visitors' searches; this one starts when one finishes.
  es.addEventListener("queued", () => {
    stopWaitingForServer();
    $("progressLabel").textContent = "Busy with other searches — yours starts in a moment…";
  });

  es.addEventListener("meta", e => {
    stopWaitingForServer();
    const meta = JSON.parse(e.data);
    state.totalCountries = meta.total;
    state.productName    = meta.product;
    state.productSlug    = typeof meta.slug === "string" ? meta.slug : "";
    if (meta.rates && typeof meta.rates === "object") state.serverRates = meta.rates;

    // The API says when it priced a different product than the one typed
    // (an older model mapped to the current one, a long name cut down…).
    // Then the heading names the product actually shown and a note explains.
    const other = meta.substituted === true && typeof meta.matchedName === "string" && meta.matchedName.trim()
      ? meta.matchedName.trim() : null;
    const shown = other || meta.product;
    state.shownName = shown;
    if (other) {
      $("summaryProduct").textContent = `🍎 ${other}`;
      document.title = `${other} — ${BASE_TITLE}`;
    }
    showMatchNote(other, query);
    $("progressLabel").textContent = `Fetching prices for "${shown}"…`;
    $("controls").style.display = "block";
    rememberSearch(query);            // only searches Apple recognised are kept

    // If cached, keep its age and expiry for the badge (item 7).
    // The API reports both; an older API sends neither and cached for 5 minutes.
    if (meta.cached) {
      state.cacheAgeMs = isNum(meta.ageSeconds) ? Math.max(0, meta.ageSeconds) * 1000 : null;
      state.cacheExpiresAt = Date.now() + (isNum(meta.expiresInSeconds)
        ? Math.max(0, meta.expiresInSeconds) * 1000 : 5 * 60 * 1000);
    }
  });

  es.addEventListener("result", e => {
    stopWaitingForServer();
    $("progressBar").classList.remove("indeterminate");
    const row = JSON.parse(e.data);
    state.allResults.push(row);
    state.receivedCount++;

    const pct = state.totalCountries
      ? Math.round(state.receivedCount / state.totalCountries * 100) : 0;
    $("progressFill").style.width = pct + "%";
    $("progressCount").textContent =
      `${state.receivedCount}${state.totalCountries ? " / " + state.totalCountries : ""}`;

    scheduleRender();
  });

  es.addEventListener("done", e => {
    stopWaitingForServer();
    $("progressBar").classList.remove("indeterminate");
    const data = JSON.parse(e.data);
    es.close();
    state.activeSource = null;
    btn.disabled = false;
    btn.textContent = "Search";
    $("progressWrap").style.display = "none";

    // Show cache badge if result was served from cache (item 7)
    if (data.cached && state.cacheExpiresAt) {
      const left = state.cacheExpiresAt - Date.now();
      const mins = Math.max(1, Math.round(left / 60000));
      $("cacheExpiry").textContent = state.cacheAgeMs !== null
        ? `· prices from ${fmtDuration(state.cacheAgeMs)} ago`
        : `· refreshes in ${mins}m`;
      $("cacheBadge").title = `Served from the server's saved results. Fetched again from Apple in ${fmtDuration(left)}.`;
      $("cacheBadge").classList.add("visible");
    }

    // J — when these prices were actually fetched from Apple
    state.fetchedAt = Date.now() - (data.cached && state.cacheAgeMs ? state.cacheAgeMs : 0);
    scheduleRender(true);
  });

  es.addEventListener("error", e => {
    stopWaitingForServer();
    $("progressBar").classList.remove("indeterminate");
    let msg = null;
    try { if (e.data) msg = JSON.parse(e.data).error; } catch (_) {}
    if (!msg) {
      msg = state.allResults.length === 0
        ? "Could not reach the API. Make sure it is deployed and running."
        : "Connection lost before all results arrived.";
    }
    // textContent, never innerHTML: the message echoes what was typed.
    const box = document.createElement("div");
    box.className = "error-msg";
    box.textContent = `⚠️ ${msg}`;
    $("status").replaceChildren(box);
    es.close();
    state.activeSource = null;
    btn.disabled = false;
    btn.textContent = "Search";
    $("progressWrap").style.display = "none";
    if (state.allResults.length === 0) {
      $("results").innerHTML = "";
      $("summary").classList.remove("visible");
      setTimeout(() => $("summary").style.display = "none", 300);
      $("controls").style.display = "none";
    } else {
      scheduleRender(true);
    }
  });
}

// Back to the empty landing state (used by back/forward navigation).
export function resetToLanding() {
  if (state.activeSource) { state.activeSource.close(); state.activeSource = null; }
  cancelScheduledRender();
  stopWaitingForServer();
  state.allResults = [];
  clearRows();
  document.title = BASE_TITLE;
  $("productInput").value = "";
  $("clearBtn").style.display = "none";
  $("searchBtn").disabled = false;
  $("searchBtn").textContent = "Search";
  $("status").innerHTML = "";
  $("results").innerHTML = "";
  $("chartView").innerHTML = "";
  $("chartView").style.display = "none";
  $("views").classList.remove("split");
  $("controls").style.display = "none";
  $("progressWrap").style.display = "none";
  $("summary").classList.remove("visible");
  $("summary").style.display = "none";
  state.productSlug = "";
  showMatchNote(null);
}

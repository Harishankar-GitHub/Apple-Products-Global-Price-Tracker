// The results table: loading rows, one row per country (animated when the order changes),
// and the footer line.
import { $, esc, safeUrl } from "./dom.js";
import { fmtDuration, fmtMoney } from "./format.js";
import { state } from "./state.js";
import { diffLabel } from "./view.js";

// Persistent row elements — survive re-renders, cleared on new search
const rowEls = new Map();

export function clearRows() { rowEls.clear(); }

// ── Skeleton (item 3) ─────────────────────────────────────────────────────
export function showSkeleton() {
  const container = $("results");
  container.style.display = "";
  const skRows = Array.from({length: 6}, (_, i) => `
    <tr class="skeleton-row" style="animation-delay:${i * 80}ms">
      <td><span class="skel" style="width:18px"></span></td>
      <td><span class="skel" style="width:${90 + (i % 3)*30}px"></span></td>
      <td><span class="skel" style="width:80px"></span><br>
          <span class="skel" style="width:50px;margin-top:6px;height:10px"></span></td>
      <td class="hide-mobile"><span class="skel" style="width:32px"></span></td>
      <td><span class="skel" style="width:70px"></span></td>
    </tr>`).join("");

  container.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th class="hide-xs">#</th>
          <th>Country</th>
          <th>Price</th>
          <th class="hide-mobile">Currency</th>
          <th>Store</th>
        </tr></thead>
        <tbody data-skeleton="1">${skRows}</tbody>
      </table>
    </div>`;
}

// ── Table render — FLIP animated, with price bar + savings (items 1, 4) ──
function rowKey(r) { return r.country; }

function buildRowEl(i, view) {
  const tr = document.createElement("tr");
  tr.dataset.key = rowKey(i.r);
  updateRowEl(tr, i, view);
  tr.classList.add("row-entering");
  tr.addEventListener("animationend",
    () => tr.classList.remove("row-entering"), {once: true});
  return tr;
}

function updateRowEl(tr, i, view) {
  const r = i.r;
  const entering = tr.classList.contains("row-entering");
  tr.className = [
    r.available  ? "" : "unavailable",
    i.isCheapest ? "cheapest-row" : "",
    i.isHome     ? "home-row" : "",
    i.pinned     ? "pinned-row" : "",
    entering     ? "row-entering" : "",
  ].filter(Boolean).join(" ");

  const href = safeUrl(r.url);
  let storeLabel = "apple.com";
  try {
    const parts = new URL(href, location.href).pathname.replace(/\/$/, "").split("/").filter(Boolean);
    if (parts.length >= 2) storeLabel = `apple.com/${parts[0]}`;
  } catch (_) {}

  const priced    = i.value !== null;
  const rankClass = priced && i.rank <= 3 ? ` rank-${i.rank}` : "";
  const rankHTML  = `<td class="rank hide-xs${rankClass}">${priced ? i.rank : "—"}</td>`;

  // Price bar width (item 1) — 100% = most expensive overall, min ~8%
  const maxVal = view.priciest ? view.priciest.value : 0;
  const barPct = priced && maxVal > 0
    ? Math.min(100, Math.max(8, Math.round((i.value / maxVal) * 100))) : 0;

  const d = diffLabel(i, view);
  const diffHTML = d ? `<div class="badge-saving ${d.cls}">${esc(d.text)}</div>` : "";

  let priceHTML;
  if (!r.available) {
    priceHTML = `<td class="price-cell"><span class="unavail-badge">${esc(r.reason)}</span></td>`;
  } else {
    // No "≈" line when it would just repeat the listed price (same currency).
    const sameAsListed = priced && r.currency === view.cur && Math.abs(i.value - r.localPrice) < 0.005;
    const converted = !priced ? `<span class="price-conv">No exchange rate</span>`
      : sameAsListed ? ""
      : `<span class="price-conv">≈ ${esc(fmtMoney(i.value, view.cur))}</span>`;
    priceHTML = `<td class="price-cell">
         <div class="price-local">${esc(r.localPriceFormatted)}${i.isCheapest
           ? '<span class="badge-cheap">Cheapest</span>' : ''}</div>
         ${converted ? `<div class="price-usd">${converted}</div>` : ""}
         ${diffHTML}
         <div class="price-bar-wrap">
           <div class="price-bar-fill" style="width:${barPct}%"></div>
         </div>
       </td>`;
  }

  const pinLabel = `${i.pinned ? "Unpin" : "Pin"} ${r.country}`;
  const pinHTML  = r.available
    ? `<button type="button" class="pin-btn${i.pinned ? " on" : ""}" data-pin="${esc(r.country)}"
         aria-pressed="${i.pinned}" aria-label="${esc(pinLabel)}" title="${esc(pinLabel)}">${i.pinned ? "★" : "☆"}</button>`
    : `<span class="pin-spacer"></span>`;

  tr.innerHTML = `
    ${rankHTML}
    <td><div class="country-cell">
      ${pinHTML}
      <span class="flag">${esc(r.flag)}</span><span class="country-name">${esc(r.country)}</span>
      ${i.isHome ? '<span class="badge-home">Home</span>' : ""}
      <span class="tip">${esc(r.country)} · ${r.available ? esc(r.currency) : "N/A"}</span>
    </div></td>
    ${priceHTML}
    <td class="hide-mobile hide-split">${r.available ? esc(r.currency) : "—"}</td>
    <td class="store-cell"><a class="store-link${r.available ? "" : " dim"}" href="${esc(href)}"
      target="_blank" rel="noopener" aria-label="${esc(`Apple store page for ${r.country}`)}"><span
      class="store-text">${esc(storeLabel)}</span> ↗</a></td>`;
}

export function showNoPrices() {
  const box  = document.createElement("div");
  box.className = "empty-note no-prices";
  const head = document.createElement("strong");
  head.textContent = `No prices found for ${state.shownName} in any country.`;
  const hint = document.createElement("span");
  hint.textContent = "Apple's pages for it did not show a price. " +
    "Tick “Show unavailable” to see what each country returned.";
  box.append(head, hint);
  $("results").replaceChildren(box);
}

export function renderTable(view, rows) {
  const container = $("results");

  if (!rows.length) {
    // Empty because of the region / country filters?
    const showUnavail = $("showUnavail")?.checked ?? false;
    if (view.items.some(i => showUnavail || i.r.available)) {
      container.innerHTML =
        `<p class="empty-note">No countries match these filters.</p>`;
      return;
    }
    // Otherwise the search is still running and no country has a price yet
    // (renderAll handles the finished case): keep the loading rows.
    if (!container.querySelector("tbody[data-skeleton]")) showSkeleton();
    return;
  }

  // Build scaffold once — wipe skeleton if present, keep real scaffold
  let tableWrap = container.querySelector(".table-wrap");
  if (!tableWrap || tableWrap.querySelector("tbody[data-skeleton]")) {
    container.innerHTML = `
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th class="col-rank hide-xs" data-sort="usd-asc usd-desc" title="Sort by price">#</th>
            <th class="col-country" data-sort="country-asc country-desc">
              Country <span class="sort-icon">↕</span></th>
            <th data-sort="usd-asc usd-desc">
              Price <span class="sort-icon active">↕</span></th>
            <th class="hide-mobile hide-split">Currency</th>
            <th class="col-store">Store</th>
          </tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <p class="results-footer"></p>`;
    tableWrap = container.querySelector(".table-wrap");
    // The scaffold was rebuilt, so previously rendered rows are detached.
    rowEls.forEach(tr => { tr.style.opacity = ""; tr.style.transform = ""; });
  }
  const tbody = tableWrap.querySelector("tbody");

  // FLIP: snapshot pre-positions
  const prePos = new Map();
  tbody.querySelectorAll("tr[data-key]").forEach(tr =>
    prePos.set(tr.dataset.key, tr.getBoundingClientRect().top));

  // Create/update row elements
  const keep = new Set();
  rows.forEach(i => {
    const key = rowKey(i.r);
    keep.add(key);
    let tr = rowEls.get(key);
    if (!tr) {
      tr = buildRowEl(i, view);
      rowEls.set(key, tr);
    } else {
      tr.style.opacity = "";
      if (!tr.isConnected) tr.style.transform = "";
      updateRowEl(tr, i, view);
    }
  });

  // Append in sorted order (moves nodes, no clone)
  rows.forEach(i => tbody.appendChild(rowEls.get(rowKey(i.r))));

  // Remove filtered-out rows
  Array.from(tbody.querySelectorAll("tr[data-key]")).forEach(tr => {
    if (!keep.has(tr.dataset.key)) tr.remove();
  });

  // FLIP: animate position deltas
  tbody.querySelectorAll("tr[data-key]").forEach(tr => {
    const pre  = prePos.get(tr.dataset.key);
    if (pre === undefined) return; // new row — row-entering handles it
    const dy = pre - tr.getBoundingClientRect().top;
    if (Math.abs(dy) < 1) return;
    tr.style.transition = "none";
    tr.style.transform  = `translateY(${dy}px)`;
    requestAnimationFrame(() => {
      tr.style.transition = "transform .45s cubic-bezier(.25,.46,.45,.94)";
      tr.style.transform  = "translateY(0)";
      tr.addEventListener("transitionend", () => {
        tr.style.transition = "";
        tr.style.transform  = "";
      }, {once: true});
    });
  });

  // Footer note with J — last updated timestamp
  const footer = container.querySelector(".results-footer");
  if (footer) {
    if (state.activeSource !== null) {
      footer.innerHTML = `<span class="spinner"></span> Loading more countries…`;
    } else {
      const noPrice = state.allResults.filter(r => !r.available).length;
      const showing = rows.filter(i => i.r.available).length;
      const total   = view.listed.length;
      const scope   = showing === total
        ? `${total} prices found`
        : `Showing ${showing} of ${total} prices`;
      const unranked = view.unconverted.length
        ? ` · ${view.unconverted.length} without an exchange rate (not ranked)` : "";
      footer.textContent =
        `${scope}${unranked} · ${noPrice} countries without a price · Base/entry model` +
        (state.fetchedAt ? ` · Updated ${Date.now() - state.fetchedAt < 60000
          ? "just now" : fmtDuration(Date.now() - state.fetchedAt) + " ago"}` : "");
    }
  }
}

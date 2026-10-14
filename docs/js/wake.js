// Waking the API: a ping when the page opens, and the "waking up the server" message.
import { API_BASE } from "./config.js";
import { $ } from "./dom.js";

// The API host goes to sleep when idle and needs up to a minute to start
// again. A small request on page load starts that early, while the visitor
// is still typing. If a search is then still waiting for the server's first
// reply, the progress area says so instead of sitting still.
const WAKE_PING_SLOW_MS    = 1500;    // ping unanswered this long → server is probably asleep
const WAKE_HINT_MS         = 3000;    // search unanswered this long → say we are waking it
const WAKE_PING_TIMEOUT_MS = 90000;
const WAKE_TEXT = "Waking up the server… this can take up to a minute";
let pingPending   = false;
let pingStartedAt = 0;
let wakeTimer     = null;             // runs while a search waits for the first reply

export function wakeServer() {
  if (typeof fetch !== "function") return;
  pingPending   = true;
  pingStartedAt = Date.now();
  const ctl    = typeof AbortController === "function" ? new AbortController() : null;
  const giveUp = setTimeout(() => { if (ctl) ctl.abort(); }, WAKE_PING_TIMEOUT_MS);
  const finish = () => { pingPending = false; clearTimeout(giveUp); };
  try {
    fetch(`${API_BASE}/api/health`, { cache: "no-store", signal: ctl ? ctl.signal : undefined })
      .then(finish, finish);          // any answer, or a failure, ends the wait
  } catch (_) { finish(); }
}

// Called when a search is sent; stopWaitingForServer() is called on its first reply.
export function startWaitingForServer() {
  stopWaitingForServer();
  const startedAt = Date.now();
  wakeTimer = setInterval(() => {
    const waited   = Date.now() - startedAt;
    const pingSlow = pingPending && Date.now() - pingStartedAt >= WAKE_PING_SLOW_MS;
    if (!pingSlow && waited < WAKE_HINT_MS) return;
    const label = $("progressLabel");
    if (label.textContent !== WAKE_TEXT) label.textContent = WAKE_TEXT;
    const count = $("progressCount");
    count.setAttribute("aria-hidden", "true");   // a ticking counter should not be read out each second
    count.textContent = `${Math.round(waited / 1000)}s`;
  }, 250);
}
export function stopWaitingForServer() {
  if (wakeTimer === null) return;
  clearInterval(wakeTimer);
  wakeTimer = null;
  const count = $("progressCount");
  count.removeAttribute("aria-hidden");
  count.textContent = "";
}

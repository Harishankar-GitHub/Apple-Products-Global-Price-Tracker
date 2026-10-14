// Formatting numbers: money, durations and percentages.

export function isNum(v) { return typeof v === "number" && Number.isFinite(v); }

export function fmtMoney(amount, cur) {
  if (!isNum(amount)) return "—";
  const digits = Math.abs(amount) >= 1000 ? 0 : 2;
  try {
    return new Intl.NumberFormat("en", {
      style: "currency", currency: cur, currencyDisplay: "narrowSymbol",
      minimumFractionDigits: digits, maximumFractionDigits: digits,
    }).format(amount);
  } catch (_) {
    return `${cur} ${amount.toFixed(digits)}`;
  }
}
// 45000 → "under a minute", 720000 → "12 min", 7500000 → "2 h 5 min"
export function fmtDuration(ms) {
  const mins = Math.floor(Math.max(0, ms) / 60000);
  if (mins < 1)  return "under a minute";
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60), m = mins % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}
export function fmtPct(p) {
  const a = Math.abs(p);
  return (a >= 10 ? Math.round(a) : Math.round(a * 10) / 10) + "%";
}

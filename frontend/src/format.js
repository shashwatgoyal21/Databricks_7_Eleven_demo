export const money = (x, signed = false) => {
  if (x == null || Number.isNaN(x)) return "Not yet";
  const a = Math.abs(x);
  const body = a >= 1e9 ? `${(a / 1e9).toFixed(2)}B` : a >= 1e6 ? `${(a / 1e6).toFixed(1)}M`
    : a >= 1e3 ? `${(a / 1e3).toFixed(0)}K` : a >= 1 ? a.toFixed(0) : a.toFixed(2);
  return `${x < 0 ? "-" : signed && x > 0 ? "+" : ""}$${body}`;
};
export const pct = (x, d = 1) => (x == null || Number.isNaN(x) ? "Not yet" : `${(x * 100).toFixed(d)}%`);
export const pts = (x) => (x == null ? "Not yet" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)} pts`);
export const int = (x) => (x == null ? "Not yet" : Math.round(x).toLocaleString("en-US"));
export const when = (s) => {
  if (!s) return "";
  const d = new Date(String(s).replace(" ", "T") + (String(s).length <= 19 ? "Z" : ""));
  if (Number.isNaN(d.getTime())) return String(s);
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
};
export const STATUS_PILL = {
  "Scale up": "p-good", Performing: "p-info", Watch: "p-warn", "Losing money": "p-bad",
  "Collecting data": "p-plain", "Not running": "p-plain",
};
export const KIND_PILL = { Scale: "p-good", Pause: "p-bad", Retarget: "p-info", "Move volume": "p-warn" };

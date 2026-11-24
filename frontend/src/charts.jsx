import { pct } from "./format.js";

const trim = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

function niceTicks(lo, hi, count = 5) {
  const span = hi - lo || 1;
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) || 10 * mag;
  const out = [];
  for (let v = Math.floor(lo / step) * step; v <= hi + step / 2; v += step) out.push(+v.toFixed(10));
  return out;
}

/** Horizontal bars, one per program, with the target as a dashed line. rows: [{id, name, value}] */
export function TargetBars({ rows, target, onSelect }) {
  if (!rows.length) return <div className="empty">No programs with enough offers</div>;
  const W = 560, L = 190, R = 56, T = 8, rowH = 36;
  const vals = rows.map((r) => r.value).concat([0, target]);
  const ticks = niceTicks(Math.min(...vals), Math.max(...vals) * 1.1, 5);
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  const x = (v) => L + ((v - lo) / (hi - lo)) * (W - L - R);
  const H = T + rows.length * rowH + 26;
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Return on spend by program">
      {ticks.map((v) => (
        <g key={v}>
          <line className="grid" x1={x(v)} x2={x(v)} y1={T} y2={T + rows.length * rowH} />
          <text x={x(v)} y={T + rows.length * rowH + 18} textAnchor="middle">{pct(v, 0)}</text>
        </g>
      ))}
      {rows.map((r, i) => {
        const y = T + i * rowH + 9, bad = r.value < target, x0 = x(0), x1 = x(r.value);
        return (
          <g key={r.id} style={{ cursor: onSelect ? "pointer" : "default" }} onClick={() => onSelect && onSelect(r.id)}>
            <rect x="0" y={y - 9} width={W} height={rowH} fill="transparent" />
            <title>{r.name}</title>
            <text className="lbl" x={L - 12} y={y + 13} textAnchor="end">{trim(r.name, 28)}</text>
            <rect x={Math.min(x0, x1)} y={y} width={Math.max(Math.abs(x1 - x0), 1)} height="18" rx="3"
              fill={bad ? "var(--bad)" : "var(--bar)"} />
            <text className="lbl" x={r.value < 0 ? x1 - 6 : x1 + 6} y={y + 13} textAnchor={r.value < 0 ? "end" : "start"}>
              {pct(r.value)}
            </text>
          </g>
        );
      })}
      <line className="target" x1={x(target)} x2={x(target)} y1={T - 4} y2={T + rows.length * rowH} />
    </svg>
  );
}

/** Columns about zero; the highlighted column uses the brand color. rows: [{label, value, engine}] */
export function Columns({ rows, format, height = 230 }) {
  if (!rows.length) return <div className="empty">No history</div>;
  const W = 520, H = height, L = 52, R = 8, T = 16, B = 26;
  const ticks = niceTicks(Math.min(0, ...rows.map((r) => r.value)), Math.max(0, ...rows.map((r) => r.value)), 4);
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const gw = (W - L - R) / rows.length, bw = Math.min(36, gw * 0.6);
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Net margin per offer">
      {ticks.map((v) => (
        <g key={v}>
          <line className="grid" x1={L} x2={W - R} y1={y(v)} y2={y(v)} />
          <text x={L - 8} y={y(v) + 4} textAnchor="end">{format(v)}</text>
        </g>
      ))}
      <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} stroke="var(--muted)" strokeWidth="1" />
      {rows.map((r, i) => {
        const cx = L + i * gw + gw / 2, top = Math.min(y(r.value), y(0)), h = Math.max(Math.abs(y(r.value) - y(0)), 1);
        return (
          <g key={r.label + i}>
            <rect x={cx - bw / 2} y={top} width={bw} height={h} rx="2"
              fill={r.engine ? "var(--brand)" : r.value < 0 ? "var(--bar-soft)" : "var(--bar)"} />
            {r.engine && (
              <text className="lbl" x={cx} y={r.value >= 0 ? top - 6 : top + h + 14} textAnchor="middle">{format(r.value)}</text>
            )}
            <text x={cx} y={H - 6} textAnchor="middle" className={r.engine ? "lbl" : ""}>{r.label}</text>
          </g>
        );
      })}
    </svg>
  );
}

import { useCallback, useEffect, useRef, useState } from "react";
import { get, post } from "./api.js";
import { Columns, TargetBars } from "./charts.jsx";
import { int, KIND_PILL, money, pct, pts, STATUS_PILL, when } from "./format.js";

const TABS = [
  ["overview", "Overview"],
  ["recommendations", "Recommendations"],
  ["programs", "Offer programs"],
  ["reports", "Reports"],
  ["system", "How it runs"],
];
const REASONS = ["Conflicts with a vendor deal", "Supply risk", "Brand concern", "Need more data"];
const QUESTIONS = [
  "Which offer programs lose money, and why?",
  "Which region and daypart give the best return on spend?",
  "What does the recommender propose this week, and on what evidence?",
  "How much does each decision cost in Databricks compute?",
];
const perOffer = (v) => `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(2)}`;

/* ---------- shared pieces ---------- */

function useData(path, deps = []) {
  const [state, set] = useState({ data: null, error: null, loading: true });
  const load = useCallback(() => {
    set((s) => ({ ...s, loading: true, error: null }));
    get(path).then((data) => set({ data, error: null, loading: false }))
      .catch((e) => set({ data: null, error: e.message, loading: false }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => { load(); }, [load]);
  return { ...state, reload: load };
}

function ErrorBox({ error, retry }) {
  return (
    <div className="err" role="alert">
      <span>Could not load: {error}</span>
      <button className="btn" onClick={retry}>Retry</button>
    </div>
  );
}

function Skeleton({ rows = 3, h = 120 }) {
  return (
    <div className="kpis" aria-busy="true">
      {Array.from({ length: rows }).map((_, i) => <div key={i} className="skel" style={{ height: h }} />)}
    </div>
  );
}

function Pill({ cls, children }) {
  return <span className={`pill ${cls}`}>{children}</span>;
}

function ModelLabel({ model }) {
  if (!model) return null;
  const v = /^\d+$/.test(String(model.version)) ? ` v${model.version}` : ` (${model.version})`;
  return <span className="src">{model.name}{v} · scored {when(model.scored_at)}</span>;
}

/* ---------- Overview ---------- */

function Kpi({ label, value, foot, children }) {
  return (
    <div className="kpi">
      <div className="lab">{label}</div>
      <div className="val num">{value}</div>
      {children}
      {foot && <div className="foot num">{foot}</div>}
    </div>
  );
}

function RecCard({ r, onOpen }) {
  return (
    <div className="qcard">
      <div className="tags">
        <Pill cls={KIND_PILL[r.kind] || "p-plain"}>{r.kind}</Pill>
        <Pill cls="p-plain">{r.confidence} confidence</Pill>
      </div>
      <h3>{r.title}</h3>
      <div className="impact num">
        <div><strong className={r.expected_annual_profit_usd < 0 ? "down" : "up"}>{money(r.expected_annual_profit_usd, true)}</strong>Profit gain / yr</div>
        <div><strong>{money(r.expected_annual_sales_usd, true)}</strong>Sales change / yr</div>
      </div>
      <div className="qfoot">
        <span className="meta">{r.region}</span>
        <button className="btn primary" onClick={() => onOpen(r.proposal_id)}>Review</button>
      </div>
    </div>
  );
}

function Overview({ go, openProgram, version }) {
  const { data, error, loading, reload } = useData("/api/overview", [version]);
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (loading && !data) return <Skeleton rows={4} />;
  const k = data.kpis;
  const ok = k.roic >= k.hurdle;
  const fill = Math.max(0, Math.min(1, k.roic / Math.max(k.hurdle * 3, 0.3)));
  const ranked = data.programs.filter((p) => p.roic != null).map((p) => ({ id: p.id, name: p.name, value: p.roic }));
  const waiting = data.programs.filter((p) => p.roic == null);
  return (
    <section className="screen">
      <div className="kpis">
        <Kpi label="Sales added / yr" value={money(k.sales)} foot={`Acceptance ${pct(k.acceptance)}`} />
        <Kpi label="Profit added / yr" value={money(k.profit)} foot="After discounts, compute, platform" />
        <Kpi label="Return on spend" value={pct(k.roic)}>
          <div className="meter" aria-hidden="true">
            <i style={{ width: `${fill * 100}%`, background: ok ? "var(--good)" : "var(--bad)" }} />
            <b style={{ left: `${(k.hurdle / Math.max(k.hurdle * 3, 0.3)) * 100}%` }} />
          </div>
          <div className="meter-lab num"><span>0%</span><span>Target {pct(k.hurdle)}</span></div>
        </Kpi>
        <Kpi label="Compute / 1,000 decisions" value={`$${k.cost_per_1k.toFixed(2)}`} foot="system.billing" />
      </div>

      <div className="row-head">
        <h2>Recommendations awaiting approval: {data.pending_count}</h2>
        <ModelLabel model={data.model} />
      </div>
      {data.recommendations.length ? (
        <div className="queue">
          {data.recommendations.map((r) => <RecCard key={r.proposal_id} r={r} onOpen={(id) => go("recommendations", id)} />)}
        </div>
      ) : <div className="panel empty">No open recommendations</div>}

      <div className="two">
        <div className="panel">
          <h2>Return on spend by program</h2>
          <TargetBars rows={ranked} target={k.hurdle} onSelect={openProgram} />
          <div className="legend">
            <span><i style={{ background: "var(--bar)" }} />Above target</span>
            <span><i style={{ background: "var(--bad)" }} />Below target</span>
            <span><i style={{ borderTop: "2px dashed var(--fg)", height: 0, width: 14, borderRadius: 0 }} />Target {pct(k.hurdle)}</span>
          </div>
          {waiting.length > 0 && (
            <div className="tags" style={{ marginTop: 12 }}>
              {waiting.map((p) => (
                <button key={p.id} className="chip" onClick={() => openProgram(p.id)}>
                  {p.name} · {p.status}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="panel">
          <h2>Net margin per offer, pilot</h2>
          <Columns rows={data.trend} format={perOffer} />
          <div className="legend">
            <span><i style={{ background: "var(--bar-soft)" }} />Before the engine, by month</span>
            <span><i style={{ background: "var(--brand)" }} />Engine</span>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ---------- Recommendations ---------- */

function Decision({ r, onDecide, onAsk }) {
  const [step, setStep] = useState(null);
  const [busy, setBusy] = useState(false);
  const act = async (status, reason) => {
    setBusy(true);
    try { await onDecide(r, status, reason); setStep(null); } finally { setBusy(false); }
  };
  if (r.status === "approved") {
    return (
      <div className="state">
        <Pill cls="p-good">Approved</Pill>
        <span className="meta">{r.decided_by} · {when(r.decided_at)}</span>
        <span>{r.rollout}</span>
        <div><button className="btn quiet" disabled={busy} onClick={() => act("proposed")}>Undo</button></div>
      </div>
    );
  }
  if (r.status === "rejected") {
    return (
      <div className="state">
        <Pill cls="p-plain">Rejected</Pill>
        <span className="meta">{r.decided_by} · {when(r.decided_at)}</span>
        {r.reject_reason && <span>{r.reject_reason}</span>}
        <div><button className="btn quiet" disabled={busy} onClick={() => act("proposed")}>Undo</button></div>
      </div>
    );
  }
  if (step === "approve") {
    return (
      <div className="confirm">
        <strong>Confirm approval</strong>
        <span>{r.rollout}</span>
        <div className="actions">
          <button className="btn primary" disabled={busy} onClick={() => act("approved")}>Approve</button>
          <button className="btn" disabled={busy} onClick={() => setStep(null)}>Cancel</button>
        </div>
      </div>
    );
  }
  if (step === "reject") {
    return (
      <div className="confirm">
        <strong>Reject reason</strong>
        <div className="chips">
          {REASONS.map((x) => <button key={x} className="chip" disabled={busy} onClick={() => act("rejected", x)}>{x}</button>)}
        </div>
        <div className="actions"><button className="btn" onClick={() => setStep(null)}>Cancel</button></div>
      </div>
    );
  }
  return (
    <div className="actions">
      <button className="btn primary" onClick={() => setStep("approve")}>Approve</button>
      <button className="btn" onClick={() => setStep("reject")}>Reject</button>
      <button className="btn quiet" onClick={() => onAsk(r)}>Ask Genie</button>
    </div>
  );
}

function RecDetail({ r, onDecide, onAsk, openProgram }) {
  return (
    <article className="dcard" id={`rec-${r.proposal_id}`}>
      <div className="dmain">
        <div className="tags">
          <Pill cls={KIND_PILL[r.kind] || "p-plain"}>{r.kind}</Pill>
          <Pill cls="p-plain">{r.confidence} confidence</Pill>
          <span className="meta">{r.region}</span>
        </div>
        <h3>{r.title}</h3>
        <ul className="why">{r.evidence.map((e) => <li key={e} className="num">{e}</li>)}</ul>
        <div><button className="link" onClick={() => openProgram(r.promotion_id)}>Open program</button></div>
      </div>
      <div className="dside">
        <div className="facts2">
          <div className="fact"><span>Profit gain / yr</span><strong className={`num ${r.expected_annual_profit_usd < 0 ? "down" : "up"}`}>{money(r.expected_annual_profit_usd, true)}</strong></div>
          <div className="fact"><span>Sales change / yr</span><strong className="num">{money(r.expected_annual_sales_usd, true)}</strong></div>
        </div>
        <Decision r={r} onDecide={onDecide} onAsk={onAsk} />
      </div>
    </article>
  );
}

function Recommendations({ focus, onChanged, onAsk, openProgram, toast, version }) {
  const { data, error, loading, reload } = useData("/api/recommendations", [version]);
  const [local, setItems] = useState(null);
  useEffect(() => { setItems(null); }, [data]);
  const items = local ?? data?.items ?? null;
  useEffect(() => {
    if (focus && items) document.getElementById(`rec-${focus}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [focus, items]);
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (!items) return <Skeleton rows={2} />;
  const decide = async (r, status, reason) => {
    try {
      const out = await post(`/api/recommendations/${encodeURIComponent(r.proposal_id)}/decision`, { status, reason });
      setItems(items.map((x) => (x.proposal_id === r.proposal_id ? { ...x, ...out } : x)));
      toast(status === "approved" ? "Approved" : status === "rejected" ? "Rejected" : "Undone");
      onChanged();
    } catch (e) {
      toast(`Not saved: ${e.message}`);
    }
  };
  const open = items.filter((r) => r.status === "proposed").length;
  return (
    <section className="screen">
      <div className="row-head">
        <h1>Recommendations <span className="meta num">({open} open)</span></h1>
        <ModelLabel model={data.model} />
      </div>
      {items.length ? (
        <div className="dlist">
          {items.map((r) => <RecDetail key={r.proposal_id} r={r} onDecide={decide} onAsk={onAsk} openProgram={openProgram} />)}
        </div>
      ) : <div className="panel empty">No recommendations from the latest scoring run</div>}
      <div className="panel">
        <h2>Recently decided</h2>
        <div className="tablewrap flat" style={{ marginTop: 12 }}>
          <table>
            <thead><tr><th>Change</th><th>Decision</th><th>By</th><th>When</th><th className="r">Profit gain / yr</th></tr></thead>
            <tbody>
              {data.decided.length ? data.decided.map((r) => (
                <tr key={r.proposal_id}>
                  <td>{r.title}</td>
                  <td><Pill cls={r.status === "approved" ? "p-good" : "p-plain"}>{r.status === "approved" ? "Approved" : "Rejected"}</Pill></td>
                  <td>{r.decided_by}</td>
                  <td className="num">{when(r.decided_at)}</td>
                  <td className="r num">{money(r.expected_annual_profit_usd, true)}</td>
                </tr>
              )) : <tr><td colSpan="5" className="meta">None yet</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

/* ---------- Offer programs ---------- */

function Programs({ openProgram, version }) {
  const { data, error, loading, reload } = useData("/api/programs", [version]);
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (loading && !data) return <Skeleton rows={1} h={300} />;
  const max = Math.max(...data.items.map((p) => p.roic || 0), data.hurdle * 2);
  return (
    <section className="screen">
      <h1>Offer programs</h1>
      <div className="tablewrap">
        <table className="wide">
          <thead><tr>
            <th>Program</th><th>Status</th><th className="r">Offers served</th><th className="r">Accepted</th>
            <th className="r">Lift vs control</th><th className="r">Sales / yr</th><th className="r">Profit / yr</th><th>Return on spend</th>
          </tr></thead>
          <tbody>
            {data.items.map((p) => (
              <tr key={p.id} className="click" tabIndex={0} onClick={() => openProgram(p.id)}
                onKeyDown={(e) => e.key === "Enter" && openProgram(p.id)}>
                <td className="pname">{p.name}</td>
                <td><Pill cls={STATUS_PILL[p.status]}>{p.status}</Pill></td>
                <td className="r num">{p.status === "Not running" ? "0" : `${int(p.offers)}${p.offers < p.min_offers ? ` / ${p.min_offers}` : ""}`}</td>
                <td className="r num">{pct(p.acceptance)}</td>
                <td className="r num">{pts(p.lift)}</td>
                <td className="r num">{money(p.sales)}</td>
                <td className={`r num ${p.profit < 0 ? "down" : ""}`}>{money(p.profit, true)}</td>
                <td className="num">
                  {p.roic == null ? <span className="meta">Not yet</span> : (
                    <><span className="minibar"><i style={{ width: `${Math.max(0, Math.min(100, (p.roic / max) * 100))}%`, background: p.roic < data.hurdle ? "var(--bad)" : "var(--bar)" }} /></span>{pct(p.roic)}</>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ProgramPanel({ id, onAsk, go }) {
  const { data, error, loading, reload } = useData(`/api/programs/${id}`);
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (loading || !data) return <div className="skel" style={{ height: 240 }} />;
  const fact = (l, v) => <div className="fact"><span>{l}</span><strong className="num">{v}</strong></div>;
  return (
    <>
      <div className="tags"><Pill cls={STATUS_PILL[data.status]}>{data.status}</Pill></div>
      <div className="facts2">
        {fact("Return on spend", pct(data.roic))}
        {fact("Profit / yr", money(data.profit, true))}
        {fact("Accepted", pct(data.acceptance))}
        {fact("Lift vs control", pts(data.lift))}
      </div>
      <div>
        <h2>Net margin per offer</h2>
        <Columns rows={data.trend} format={perOffer} height={200} />
      </div>
      {data.cells.length > 0 && (
        <div className="tablewrap flat">
          <table>
            <thead><tr><th>Region</th><th>Daypart</th><th className="r">Offers</th><th className="r">Accepted</th><th className="r">Return</th></tr></thead>
            <tbody>
              {data.cells.map((c) => (
                <tr key={c.region + c.daypart}>
                  <td>{c.region}</td><td>{c.daypart}</td><td className="r num">{int(c.offers_served)}</td>
                  <td className="r num">{pct(c.acceptance)}</td><td className="r num">{pct(c.return_on_spend)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.recommendations.length > 0 && (
        <div className="dlist" style={{ gap: 8 }}>
          <h2>Recommendations</h2>
          {data.recommendations.map((r) => (
            <button key={r.proposal_id} className="chip" style={{ textAlign: "left", borderRadius: 8, padding: "8px 12px" }}
              onClick={() => go("recommendations", r.proposal_id)}>
              {r.title} · {money(r.expected_annual_profit_usd, true)} / yr
            </button>
          ))}
        </div>
      )}
      <div className="actions"><button className="btn" onClick={() => onAsk(null, `How is ${data.name} performing by region and daypart?`)}>Ask Genie</button></div>
    </>
  );
}

/* ---------- Reports ---------- */

function Reports() {
  const { data, error, loading, reload } = useData("/api/reports");
  return (
    <section className="screen">
      <div className="row-head">
        <h1>Reports</h1>
        <div className="actions">
          <a className="btn" href="/api/reports/finance.html" target="_blank" rel="noreferrer">Finance report</a>
          <a className="btn" href="/api/reports/epm.csv">Export for EPM</a>
          {data?.open_url && <a className="btn primary" href={data.open_url} target="_blank" rel="noreferrer">Open in Databricks</a>}
        </div>
      </div>
      {error && <ErrorBox error={error} retry={reload} />}
      <div className="dash">
        {loading ? <div className="skel" style={{ height: 600 }} />
          : data?.embed_url ? <iframe title="NBO Offer Engine dashboard" src={data.embed_url} />
            : <div className="empty">Dashboard "NBO Offer Engine" not found in this workspace</div>}
      </div>
    </section>
  );
}

/* ---------- How it runs ---------- */

function System({ version }) {
  const { data, error, loading, reload } = useData("/api/system", [version]);
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (loading && !data) return <Skeleton rows={4} />;
  const fmt = (s) => (s.value == null ? "Not measured" : s.fmt === "pct" ? pct(s.value) : s.fmt === "ms" ? `${Math.round(s.value)} ms` : int(s.value));
  const Panel = ({ title, rows }) => (
    <div className="panel">
      <h2>{title}</h2>
      <dl className="facts num">
        {rows.map(([k, v]) => [<dt key={`${k}t`}>{k}</dt>, <dd key={`${k}d`}>{v ?? "Not set"}</dd>])}
      </dl>
    </div>
  );
  return (
    <section className="screen">
      <h1>How it runs</h1>
      <div className="flow">
        {data.steps.map((s) => (
          <div className="step" key={s.label}><div className="t">{s.label}</div><div className="m num">{fmt(s)}</div></div>
        ))}
      </div>
      <div className="trio">
        <Panel title="Decision model" rows={[["Endpoint", data.model.endpoint], ["Model", <code key="m">{data.model.uplift_model.split(".").pop()}</code>], ["Version", data.model.version]]} />
        <Panel title="Recommender" rows={[["Model", <code key="r">{data.recommender.name.split(".").pop()}</code>], ["Version", data.recommender.version], ["Scored", when(data.recommender.scored_at)], ["Proposals", data.recommender.proposals]]} />
        <Panel title="Cost" rows={[["Compute / 1,000 decisions", `$${data.cost.per_1k.toFixed(2)}`], ["Compute / yr", money(data.cost.network_year)], ["Platform / yr", money(data.cost.platform_year)], ["Source", data.cost.source]]} />
        <Panel title="Governance" rows={[["Row filter", <code key="f">{data.governance.row_filter}</code>], ["Masked", data.governance.masked], ["App scope", data.governance.app_scope], ["Approvals", <code key="a">{data.governance.approvals}</code>]]} />
      </div>
    </section>
  );
}

/* ---------- Ask Genie ---------- */

function Markdown({ text }) {
  // bold, bullets and numbered lists only; everything else is plain text
  const inline = (s) => s.split(/(\*\*[^*]+\*\*)/g).map((p, i) => (p.startsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : p));
  const blocks = String(text || "").split(/\n{2,}/);
  return blocks.map((b, i) => {
    const lines = b.split("\n");
    if (lines.every((l) => /^\s*[-*] /.test(l))) return <ul key={i}>{lines.map((l, j) => <li key={j}>{inline(l.replace(/^\s*[-*] /, ""))}</li>)}</ul>;
    if (lines.every((l) => /^\s*\d+\. /.test(l))) return <ol key={i}>{lines.map((l, j) => <li key={j}>{inline(l.replace(/^\s*\d+\. /, ""))}</li>)}</ol>;
    return <p key={i}>{inline(b)}</p>;
  });
}

function Genie({ seed }) {
  const [history, setHistory] = useState([]);
  const [answers, setAnswers] = useState([]);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");
  const end = useRef(null);
  const ask = useCallback(async (text) => {
    const h = [...history, { role: "user", content: text }];
    setHistory(h); setBusy(true);
    setAnswers((a) => [...a, { q: text, a: null }]);
    try {
      const res = await post("/api/ask", { history: h }, 120000);
      setHistory([...h, { role: "assistant", content: res.content }]);
      setAnswers((a) => a.map((x, i) => (i === a.length - 1 ? { q: text, a: res } : x)));
    } catch (e) {
      setAnswers((a) => a.map((x, i) => (i === a.length - 1 ? { q: text, a: { content: `Could not answer: ${e.message}` } } : x)));
    } finally { setBusy(false); }
  }, [history]);
  const asked = useRef(null);
  useEffect(() => { if (seed && asked.current !== seed.key) { asked.current = seed.key; ask(seed.text); } }, [seed, ask]);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [answers]);
  return (
    <>
      <div className="dbody">
        {!answers.length && <div className="suggest">{QUESTIONS.map((x) => <button key={x} onClick={() => ask(x)}>{x}</button>)}</div>}
        {answers.map((x, i) => (
          <div key={i} className="dlist" style={{ gap: 10 }}>
            <div className="msg you">{x.q}</div>
            <div className="msg bot">
              {x.a ? <Markdown text={x.a.content} /> : <Thinking />}
              {x.a?.tables?.map((t, j) => (
                <div key={j} className="tablewrap flat"><table>
                  <thead><tr>{t.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                  <tbody>{t.data.map((row, k) => <tr key={k}>{row.map((v, m) => <td key={m} className="num">{String(v ?? "")}</td>)}</tr>)}</tbody>
                </table></div>
              ))}
              {x.a?.sql?.length > 0 && <details><summary>Show the query</summary>{x.a.sql.map((s, j) => <pre key={j}>{s}</pre>)}</details>}
              {x.a?.routed && <span className="src">{x.a.routed}</span>}
            </div>
          </div>
        ))}
        <div ref={end} />
      </div>
      <form className="ask" onSubmit={(e) => { e.preventDefault(); if (q.trim() && !busy) { ask(q.trim()); setQ(""); } }}>
        <input id="genie-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about offers, regions, results" autoComplete="off" />
        <button className="btn primary" type="submit" disabled={busy}>Ask</button>
      </form>
    </>
  );
}

function Thinking() {
  const [s, setS] = useState(0);
  useEffect(() => { const t = setInterval(() => setS((x) => x + 1), 1000); return () => clearInterval(t); }, []);
  return <span className="meta num">Thinking · {s}s</span>;
}

function Drawer({ title, kicker, onClose, children, hidden }) {
  useEffect(() => {
    const k = (e) => e.key === "Escape" && !hidden && onClose();
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  }, [onClose, hidden]);
  return (
    <>
      <div className="scrim" onClick={onClose} hidden={hidden} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title} hidden={hidden}>
        <div className="dhead">
          <div><div className="meta">{kicker}</div><h2>{title}</h2></div>
          <button className="x" onClick={onClose} aria-label="Close">&#x2715;</button>
        </div>
        {children}
      </aside>
    </>
  );
}

/* ---------- App shell ---------- */

function readHash() {
  const [tab, focus] = location.hash.slice(1).split("--");
  return { tab: TABS.some(([t]) => t === tab) ? tab : "overview", focus: focus || null };
}

export default function App() {
  const [{ tab, focus }, setRoute] = useState(readHash);
  const [dark, setDark] = useState(() => { try { return localStorage.getItem("oe-dark") === "1"; } catch { return false; } });
  const [drawer, setDrawer] = useState(null);
  const [toastMsg, setToast] = useState(null);
  const [version, setVersion] = useState(0);
  const [count, setCount] = useState(null);
  const names = useRef({});

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    try { localStorage.setItem("oe-dark", dark ? "1" : "0"); } catch { /* storage blocked */ }
  }, [dark]);
  useEffect(() => {
    const f = () => setRoute(readHash());
    addEventListener("hashchange", f);
    return () => removeEventListener("hashchange", f);
  }, []);
  useEffect(() => {
    get("/api/overview").then((d) => {
      setCount(d.pending_count);
      setScope(d.scope);
      d.programs.forEach((p) => { names.current[p.id] = p.name; });
    }).catch(() => {});
  }, [version]);
  const [scope, setScope] = useState(null);
  useEffect(() => { if (!toastMsg) return undefined; const t = setTimeout(() => setToast(null), 2600); return () => clearTimeout(t); }, [toastMsg]);

  const go = (t, f) => { location.hash = f ? `${t}--${f}` : t; setDrawer(null); window.scrollTo(0, 0); };
  const openProgram = (id) => setDrawer({ kind: "program", id });
  const [genie, setGenie] = useState({ open: false, mounted: false, seed: null });
  const onAsk = (r, text) => {
    const t = text || (r ? `Explain the evidence for: ${r.title}` : null);
    setDrawer(null);
    setGenie((g) => ({ open: true, mounted: true, seed: t ? { text: t, key: Date.now() } : g.seed }));
  };

  const scopeLabel = scope && `Pilot ${scope.pilot_stores} stores · ${scope.start === scope.end ? scope.start : `${scope.start} to ${scope.end}`} · Projected ${int(scope.network_stores)} stores / yr`;

  return (
    <>
      <header>
        <div className="wrap">
          <div className="top">
            <div className="mark" aria-hidden="true">
              <svg viewBox="0 0 16 16" width="16" height="16"><path d="M8 1 15 5v6l-7 4-7-4V5z" fill="none" stroke="#fff" strokeWidth="1.6" /><path d="M1 5l7 4 7-4M8 9v6" stroke="#fff" strokeWidth="1.6" fill="none" /></svg>
            </div>
            <div className="name">In-Store Offer Engine</div>
            {scopeLabel && <div className="scope num">{scopeLabel}</div>}
            <div className="spacer" />
            <button className="toggle" type="button" aria-pressed={dark} onClick={() => setDark(!dark)}>
              <span className="switch" aria-hidden="true" />Dark mode
            </button>
          </div>
          <nav aria-label="Screens">
            {TABS.map(([id, label]) => (
              <a key={id} href={`#${id}`} aria-current={tab === id ? "page" : undefined}>
                {label}
                {id === "recommendations" && count != null && <span className={`count ${count ? "" : "zero"}`}>{count}</span>}
              </a>
            ))}
          </nav>
        </div>
      </header>
      <main className="wrap">
        {tab === "overview" && <Overview go={go} openProgram={openProgram} version={version} />}
        {tab === "recommendations" && <Recommendations focus={focus} onChanged={() => setVersion((v) => v + 1)} onAsk={onAsk} openProgram={openProgram} toast={setToast} version={0} />}
        {tab === "programs" && <Programs openProgram={openProgram} version={version} />}
        {tab === "reports" && <Reports />}
        {tab === "system" && <System version={version} />}
      </main>
      {!drawer && !genie.open && (
        <button className="fab" type="button" title="Ask Genie" aria-label="Ask Genie" onClick={() => onAsk(null)}>
          <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M3 5.5A2.5 2.5 0 0 1 5.5 3h9A2.5 2.5 0 0 1 17 5.5v6a2.5 2.5 0 0 1-2.5 2.5H9l-4 3v-3A2 2 0 0 1 3 12z" /></svg>
          <span>Genie</span>
        </button>
      )}
      {drawer?.kind === "program" && (
        <Drawer kicker="Offer program" title={names.current[drawer.id] || drawer.id} onClose={() => setDrawer(null)}>
          <div className="dbody"><ProgramPanel id={drawer.id} onAsk={onAsk} go={go} /></div>
        </Drawer>
      )}
      {genie.mounted && (
        <Drawer kicker="Genie" title="Ask Genie" hidden={!genie.open} onClose={() => setGenie((g) => ({ ...g, open: false }))}>
          <Genie seed={genie.seed} />
        </Drawer>
      )}
      {toastMsg && <div className="toast" role="status">{toastMsg}</div>}
    </>
  );
}

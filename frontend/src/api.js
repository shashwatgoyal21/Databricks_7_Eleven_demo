async function req(path, opts = {}, timeoutMs = 30000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  let r;
  try {
    r = await fetch(path, { ...opts, signal: ctl.signal });
  } catch (e) {
    throw new Error(e.name === "AbortError" ? `no answer after ${Math.round(timeoutMs / 1000)}s` : e.message);
  } finally {
    clearTimeout(timer);
  }
  let body = null;
  try { body = await r.json(); } catch { /* not JSON */ }
  if (!r.ok) throw new Error((body && (body.error || body.detail)) || `${r.status} ${r.statusText}`);
  return body;
}
export const get = (p) => req(p);
export const post = (p, data, timeoutMs) => req(p, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
}, timeoutMs);

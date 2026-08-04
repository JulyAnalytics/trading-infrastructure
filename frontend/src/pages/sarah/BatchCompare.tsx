import { useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "../../api";
import PlotlyFig from "../../components/PlotlyFig";

// Status chip classes mirror JobsPage so chips look consistent across pages.
const STATUS_CLASS: Record<string, string> = {
  succeeded: "ok", failed: "bad", running: "warn", queued: "",
};
const CONF_CLASS: Record<string, string> = {
  standard: "ok", medium: "warn", low: "warn", insufficient: "bad",
};

type Job = {
  id: string; name: string; status: string;
  log_tail: string | null; error: string | null;
};

type CompareRow = {
  ticker: string; date: string;
  atm_iv_30d: number | null; iv_rank: number | null;
  iv_percentile: number | null; ivr_ivp_confidence: string | null;
  vrp_proxy_bkwd: number | null; vrp_proxy_signal: string | null;
  ts_shape: string | null; skew_25d_rr: number | null;
  rv_21d: number | null; iv_rv_spread: number | null;
  next_earnings_date: string | null; macro_regime: string | null;
};

type CompareResp = {
  as_of: string;
  rows: CompareRow[];
  rankings: Record<string, string[]>;
};

function num(v: any, d = 2) {
  return v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(d);
}

/** Days from today to an iso date string, or null. */
function daysTo(iso: string | null): number | null {
  if (!iso) return null;
  const t = new Date(iso.slice(0, 10)).getTime();
  if (Number.isNaN(t)) return null;
  return Math.round((t - Date.now()) / 86400000);
}

/** Normalise free-text ticker input into a deduped upper list. */
function parseInput(s: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const tok of s.replace(/,/g, " ").split(/\s+/)) {
    const t = tok.trim().toUpperCase();
    if (t && !seen.has(t)) {
      seen.add(t);
      out.push(t);
    }
  }
  return out;
}

export default function BatchCompare({ tickers }: { tickers: string[] }) {
  // ── Batch run ───────────────────────────────────────────────────────────
  const [text, setText] = useState("");
  const [skipRegime, setSkipRegime] = useState(true);
  const [job, setJob] = useState<Job | null>(null);
  const [anyRunning, setAnyRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Is anything else running on the single-writer queue? Disable Run if so.
  useEffect(() => {
    let alive = true;
    const check = () =>
      apiGet<{ jobs: Job[] }>("/api/jobs")
        .then((r) => alive && setAnyRunning(
          r.jobs.some((j) => j.status === "running" || j.status === "queued")))
        .catch(() => {});
    check();
    const t = setInterval(check, 3000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  // Poll the active batch job until it leaves the running/queued states.
  useEffect(() => {
    if (!job || (job.status !== "running" && job.status !== "queued")) {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      return;
    }
    pollRef.current = setInterval(async () => {
      try {
        const j = await apiGet<Job>(`/api/jobs/${job.id}`);
        setJob(j);
        if (j.status === "succeeded") {
          // Auto-seed the compare view with the batch we just scanned.
          const scanned = parseInput(text);
          if (scanned.length) setSelected(scanned);
        }
      } catch { /* transient — keep polling */ }
    }, 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [job?.status]);  // eslint-disable-line react-hooks/exhaustive-deps

  const runBatch = async () => {
    const tkrs = parseInput(text);
    if (!tkrs.length) { setRunError("enter at least one ticker"); return; }
    setRunError(null);
    try {
      const j = await apiSend<Job>("/api/jobs", "POST", {
        name: "sarah_daily_vol",
        args: { tickers: tkrs, skip_regime_check: skipRegime },
      });
      setJob(j);
    } catch (e: any) {
      setRunError(e.message);
    }
  };

  // ── Compare ─────────────────────────────────────────────────────────────
  const [selected, setSelected] = useState<string[]>([]);
  const [cmp, setCmp] = useState<CompareResp | null>(null);
  const [cmpError, setCmpError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<keyof CompareRow>("iv_rank");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const loadCompare = async (tkrs: string[]) => {
    if (!tkrs.length) { setCmp(null); return; }
    setCmpError(null);
    try {
      setCmp(await apiGet<CompareResp>(
        `/api/sarah/compare?tickers=${encodeURIComponent(tkrs.join(","))}`));
    } catch (e: any) {
      setCmp(null);
      setCmpError(e.message);
    }
  };

  useEffect(() => {
    if (selected.length) loadCompare(selected);
    else setCmp(null);
  }, [selected]);  // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (t: string) =>
    setSelected((s) => (s.includes(t) ? s.filter((x) => x !== t) : [...s, t]));

  const toggleSort = (k: keyof CompareRow) => {
    if (k === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(k); setSortDir("desc"); }
  };

  const sortedRows = (() => {
    if (!cmp) return [];
    const rows = [...cmp.rows];
    const dir = sortDir === "asc" ? 1 : -1;
    rows.sort((a, b) => {
      const av = a[sortKey] ?? null, bv = b[sortKey] ?? null;
      if (av == null && bv == null) return 0;
      if (av == null) return 1;   // nulls last regardless of dir
      if (bv == null) return -1;
      if (typeof av === "string" && typeof bv === "string")
        return av.localeCompare(bv) * dir;
      return ((av as number) - (bv as number)) * dir;
    });
    return rows;
  })();

  const rankedFirst = (field: string) => cmp?.rankings[field]?.[0];
  const compareList = encodeURIComponent(selected.join(","));
  const selfBusy = job?.status === "running" || job?.status === "queued";

  return (
    <>
      {/* ── Batch run card ─────────────────────────────────────────────── */}
      <div className="card">
        <h3>Batch scan</h3>
        <p className="muted" style={{ fontSize: "var(--fs-115)" }}>
          Push an ad-hoc ticker list through Stage 1 (chain → term structure →
          skew → signals → DB). Runs as a <code>sarah_daily_vol</code> job —
          respects the single-writer queue. Results land in the vol monitor and
          the compare view below.
        </p>
        <textarea
          rows={3}
          placeholder="AMD PLTR, PFE, LLY, SNDK …"
          value={text}
          onChange={(e) => setText(e.target.value)}
          style={{ width: "100%", fontFamily: "var(--mono)", marginBottom: 8 }}
        />
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <label className="muted" style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <input type="checkbox" checked={skipRegime}
                   onChange={(e) => setSkipRegime(e.target.checked)} />
            skip regime-age check
          </label>
          <button className="action"
                  disabled={anyRunning || selfBusy || !parseInput(text).length}
                  onClick={runBatch}>
            {selfBusy ? "running…" : "Run batch"}
          </button>
          {anyRunning && !selfBusy && (
            <span className="muted">a job is already running on the queue…</span>
          )}
        </div>
        {runError && <div className="error-box">{runError}</div>}
        {job && (
          <div style={{ marginTop: 10 }}>
            <span className={"chip " + (STATUS_CLASS[job.status] ?? "")}>{job.status}</span>{" "}
            <span className="muted" style={{ fontSize: "var(--fs-115)" }}>{job.id}</span>
            {job.status === "failed" && job.error && (
              <pre className="error-box" style={{ marginTop: 8, whiteSpace: "pre-wrap" }}>
                {job.error}
                {job.log_tail ? `\n\n${job.log_tail}` : ""}
              </pre>
            )}
          </div>
        )}
      </div>

      {/* ── Compare card ───────────────────────────────────────────────── */}
      <div className="card" style={{ marginTop: 14 }}>
        <h3>Compare</h3>

        {/* Ticker multi-select chips seeded from the vol universe. */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
          {tickers.concat(parseInput(text))
            .filter((t, i, a) => a.indexOf(t) === i)
            .map((t) => {
              const on = selected.includes(t);
              return (
                <button key={t}
                  className={"chip " + (on ? "ok" : "")}
                  style={{ cursor: "pointer", border: "1px solid var(--border)" }}
                  onClick={() => toggle(t)}>
                  {t}
                </button>
              );
            })}
        </div>
        {selected.length > 0 && (
          <button className="action secondary" style={{ marginBottom: 8 }}
                  onClick={() => loadCompare(selected)}>
            reload
          </button>
        )}

        {cmpError && <div className="error-box">{cmpError}</div>}
        {!cmp && !cmpError && (
          <p className="muted">select tickers (or run a batch) to compare.</p>
        )}

        {cmp && sortedRows.length > 0 && (
          <>
            <table className="data" style={{ marginTop: 4 }}>
              <thead>
                <tr>
                  <Th label="Ticker" k="ticker" cur={sortKey} dir={sortDir} onSort={toggleSort} />
                  <Th label="ATM IV 30d" k="atm_iv_30d" cur={sortKey} dir={sortDir} onSort={toggleSort} />
                  <Th label="IV rank" k="iv_rank" cur={sortKey} dir={sortDir} onSort={toggleSort} />
                  <Th label="IV pctile" k="iv_percentile" cur={sortKey} dir={sortDir} onSort={toggleSort} />
                  <Th label="VRP" k="vrp_proxy_bkwd" cur={sortKey} dir={sortDir} onSort={toggleSort} />
                  <Th label="TS shape" k="ts_shape" cur={sortKey} dir={sortDir} onSort={toggleSort} />
                  <Th label="25Δ RR" k="skew_25d_rr" cur={sortKey} dir={sortDir} onSort={toggleSort} />
                  <Th label="RV 21d" k="rv_21d" cur={sortKey} dir={sortDir} onSort={toggleSort} />
                  <th>Earnings</th>
                  <Th label="Regime" k="macro_regime" cur={sortKey} dir={sortDir} onSort={toggleSort} />
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((r) => {
                  const d = daysTo(r.next_earnings_date);
                  return (
                    <tr key={r.ticker}>
                      <td><b>{r.ticker}</b></td>
                      <td>{num(r.atm_iv_30d, 1)}</td>
                      <td style={{ position: "relative" }}>
                        {num(r.iv_rank, 1)}{" "}
                        <span className={"chip " + (CONF_CLASS[r.ivr_ivp_confidence ?? ""] ?? "")}>
                          {r.ivr_ivp_confidence ?? "—"}
                        </span>
                        {rankedFirst("iv_rank") === r.ticker && <Crown />}
                      </td>
                      <td>{num(r.iv_percentile, 1)}</td>
                      <td style={{ position: "relative" }}>
                        {num(r.vrp_proxy_bkwd, 1)}{" "}
                        <span className="muted">{r.vrp_proxy_signal ?? ""}</span>
                        {rankedFirst("vrp_proxy_bkwd") === r.ticker && <Crown />}
                      </td>
                      <td>{r.ts_shape ?? "—"}</td>
                      <td style={{ position: "relative" }}>
                        {num(r.skew_25d_rr, 2)}
                        {rankedFirst("skew_25d_rr") === r.ticker && <Crown />}
                      </td>
                      <td>{num(r.rv_21d, 1)}</td>
                      <td>
                        {d == null ? (
                          <span className="muted">—</span>
                        ) : d <= 14 ? (
                          <span className="chip warn">{d}d</span>
                        ) : (
                          <span className="muted">{d}d</span>
                        )}
                      </td>
                      <td className="muted">{r.macro_regime ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="muted" style={{ fontSize: "var(--fs-115)", marginTop: 6 }}>
              <Crown inline /> = rank 1 in that column. VRP = IV − RV (vol pts,
              backward-looking proxy — not matched-maturity). Earnings flagged
              within 14d. Click any column header to sort.
            </p>

            <div className="grid cols-2" style={{ marginTop: 14 }}>
              <div className="card">
                <h3>Term structure overlay</h3>
                <PlotlyFig src={`/api/sarah/charts/term-structure-compare?tickers=${compareList}`} />
              </div>
              <div className="card">
                <h3>ATM IV 30d history</h3>
                <PlotlyFig src={`/api/sarah/charts/iv-history-compare?tickers=${compareList}`} />
              </div>
            </div>
            <div className="card" style={{ marginTop: 14 }}>
              <h3>Vol opportunity map</h3>
              <PlotlyFig src={`/api/sarah/charts/scatter-vol-map?tickers=${compareList}`} />
              <p className="muted" style={{ fontSize: "var(--fs-115)" }}>
                Top-right = high IV rank + rich VRP (premium-selling candidates);
                bottom-left = low IV rank + cheap VRP (long-premium / hedge candidates).
                Bubble size ∝ ATM IV.
              </p>
            </div>
          </>
        )}
      </div>
    </>
  );
}

/** Sortable column header with a direction arrow. */
function Th({ label, k, cur, dir, onSort }: {
  label: string; k: keyof CompareRow;
  cur: keyof CompareRow; dir: "asc" | "desc";
  onSort: (k: keyof CompareRow) => void;
}) {
  const active = k === cur;
  return (
    <th onClick={() => onSort(k)} style={{ cursor: "pointer", userSelect: "none" }}>
      {label}{" "}
      <span className="muted">{active ? (dir === "asc" ? "▲" : "▼") : "↕"}</span>
    </th>
  );
}

/** A small marker for the rank-1 row in a column. */
function Crown({ inline = false }: { inline?: boolean }) {
  return (
    <span style={{
      marginLeft: inline ? 0 : 4,
      color: "var(--accent)",
      fontSize: "var(--fs-115)",
    }}>★</span>
  );
}

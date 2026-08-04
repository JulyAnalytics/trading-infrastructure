import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../api";
import { usePlotTheme } from "../theme";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";

const Plot = createPlotlyComponent(Plotly);

function num(v: any, d = 3) {
  return v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(d);
}

function Verdict({ v }: { v: string | null | undefined }) {
  if (!v) return null;
  return v === "GO"
    ? <span className="chip ok" style={{ fontSize: "var(--fs-13)" }}>GO</span>
    : <span className="chip bad" style={{ fontSize: "var(--fs-13)" }}>NO_GO</span>;
}

export default function PriyaPage() {
  const [error, setError] = useState<string | null>(null);
  const plotTheme = usePlotTheme();

  // hypotheses
  const [hyps, setHyps] = useState<any[]>([]);
  const [hForm, setHForm] = useState<any>({
    hypothesis: "", dataset_id: "", signal_type: "technical", rationale: "",
  });
  const [hBusy, setHBusy] = useState(false);

  // data audit
  const [aTicker, setATicker] = useState("SPY");
  const [aBusy, setABusy] = useState(false);
  const [audit, setAudit] = useState<any>(null);

  // run configurator
  const [rForm, setRForm] = useState<any>({
    hypothesis_id: "", ticker: "SPY", signal_type: "momentum",
    window: "20", z_entry: "1.0", sweep_windows: "10,20,40,60",
    use_sweep: true, cost_bps: "10",
  });
  const [rBusy, setRBusy] = useState(false);
  const [run, setRun] = useState<any>(null);

  // verdict + archive + gates
  const [verdict, setVerdict] = useState<any>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [runFilter, setRunFilter] = useState<string>("");
  const [gates, setGates] = useState<any>(null);

  const loadHyps = () =>
    apiGet<{ hypotheses: any[] }>("/api/priya/hypotheses")
      .then((r) => setHyps(r.hypotheses)).catch(() => {});
  const loadRuns = (f: string) =>
    apiGet<{ runs: any[] }>(`/api/priya/runs${f ? `?verdict=${f}` : ""}`)
      .then((r) => setRuns(r.runs)).catch(() => {});

  useEffect(() => {
    loadHyps();
    loadRuns("");
    apiGet("/api/priya/verdict").then(setVerdict).catch(() => {});
    apiGet("/api/priya/gates").then(setGates).catch(() => {});
  }, []);

  const register = async () => {
    setHBusy(true); setError(null);
    try {
      const r = await apiSend("/api/priya/hypotheses", "POST", hForm);
      setHForm({ hypothesis: "", dataset_id: "", signal_type: "technical", rationale: "" });
      await loadHyps();
      setRForm((f: any) => ({ ...f, hypothesis_id: r.hypothesis_id }));
    } catch (e: any) { setError(e.message); }
    finally { setHBusy(false); }
  };

  const runAudit = async () => {
    setABusy(true); setError(null); setAudit(null);
    try { setAudit(await apiSend("/api/priya/data-audit", "POST", { ticker: aTicker })); }
    catch (e: any) { setError(e.message); }
    finally { setABusy(false); }
  };

  const launch = async () => {
    setRBusy(true); setError(null); setRun(null);
    try {
      const body: any = {
        hypothesis_id: rForm.hypothesis_id, ticker: rForm.ticker,
        signal_type: rForm.signal_type, cost_bps: Number(rForm.cost_bps),
        params: { window: Number(rForm.window) },
      };
      if (rForm.signal_type === "mean_reversion")
        body.params.z_entry = Number(rForm.z_entry);
      if (rForm.use_sweep)
        body.sweep = {
          window: rForm.sweep_windows.split(",").map((s: string) => Number(s.trim()))
            .filter((n: number) => !Number.isNaN(n)),
        };
      const r = await apiSend("/api/priya/run", "POST", body);
      setRun(r);
      loadRuns(runFilter);
      apiGet("/api/priya/verdict").then(setVerdict).catch(() => {});
      loadHyps(); // trial counts moved
    } catch (e: any) { setError(e.message); }
    finally { setRBusy(false); }
  };

  const p = run?.pipeline;

  return (
    <div>
      <h2>Priya — Research Workbench</h2>
      {error && <div className="error-box">{error}</div>}

      <div className="grid cols-2">
        <div className="card">
          <h3>Hypothesis registration (gate 1 — pre-register before testing)</h3>
          <div className="field"><div className="label">Hypothesis</div>
            <input value={hForm.hypothesis} placeholder="e.g. 20d momentum persists on SPY after costs"
                   onChange={(e) => setHForm({ ...hForm, hypothesis: e.target.value })} /></div>
          <div className="grid cols-2">
            <div className="field"><div className="label">Dataset ID</div>
              <input value={hForm.dataset_id} placeholder="SPY_daily_2016_2026"
                     onChange={(e) => setHForm({ ...hForm, dataset_id: e.target.value })} /></div>
            <div className="field"><div className="label">Signal type</div>
              <select value={hForm.signal_type}
                      onChange={(e) => setHForm({ ...hForm, signal_type: e.target.value })}>
                <option>technical</option><option>macro</option><option>vol_surface</option>
              </select></div>
          </div>
          <div className="field"><div className="label">Rationale (economic basis, not paperwork)</div>
            <input value={hForm.rationale} placeholder="why should this edge exist?"
                   onChange={(e) => setHForm({ ...hForm, rationale: e.target.value })} /></div>
          <button className="action" disabled={hBusy || !hForm.hypothesis || !hForm.dataset_id || !hForm.rationale}
                  onClick={register}>{hBusy ? "registering…" : "Register hypothesis"}</button>

          {hyps.length > 0 && (
            <table className="data" style={{ marginTop: 10 }}>
              <thead><tr><th>ID</th><th>Dataset</th><th>Trials</th></tr></thead>
              <tbody>
                {hyps.slice(0, 8).map((h) => (
                  <tr key={h.hypothesis_id} style={{ cursor: "pointer" }}
                      onClick={() => setRForm((f: any) => ({ ...f, hypothesis_id: h.hypothesis_id }))}>
                    <td className="mono" title={h.hypothesis}>{h.hypothesis_id.slice(0, 34)}…</td>
                    <td>{h.dataset_id}</td>
                    <td>{h.trial_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <h3>Data audit (gate 2 — blockers stop the pipeline)</h3>
          <div className="grid cols-2">
            <div className="field"><div className="label">Ticker</div>
              <input value={aTicker} onChange={(e) => setATicker(e.target.value.toUpperCase())} /></div>
            <div className="field"><div className="label">&nbsp;</div>
              <button className="action" disabled={aBusy} onClick={runAudit}>
                {aBusy ? "auditing…" : "Run data audit"}</button></div>
          </div>
          {audit && (
            <>
              <p className="muted" style={{ fontSize: "var(--fs-12)" }}>
                {audit.label} · {audit.n_rows} rows · {audit.start} → {audit.end}
              </p>
              {(audit.blockers ?? []).length === 0
                ? <p><span className="chip ok">no blockers</span></p>
                : (audit.blockers ?? []).map((b: any, i: number) => (
                  <div key={i} className="error-box" style={{ fontSize: "var(--fs-115)" }}>
                    <b>{b.check}</b> — {b.detail}</div>))}
              {(audit.flags ?? []).map((f: any, i: number) => (
                <p key={i} className="muted" style={{ fontSize: "var(--fs-115)" }}>
                  ⚠ <b>{f.check}</b> — {f.detail}</p>))}
            </>
          )}
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Backtest configurator → full pipeline (Stages 5–8)</h3>
        <div className="grid cols-3">
          <div className="field"><div className="label">Hypothesis</div>
            <select value={rForm.hypothesis_id}
                    onChange={(e) => setRForm({ ...rForm, hypothesis_id: e.target.value })}>
              <option value="">— select —</option>
              {hyps.map((h) => (
                <option key={h.hypothesis_id} value={h.hypothesis_id}>
                  {h.dataset_id}: {String(h.hypothesis).slice(0, 40)}
                </option>))}
            </select></div>
          <div className="field"><div className="label">Ticker</div>
            <input value={rForm.ticker}
                   onChange={(e) => setRForm({ ...rForm, ticker: e.target.value.toUpperCase() })} /></div>
          <div className="field"><div className="label">Signal</div>
            <select value={rForm.signal_type}
                    onChange={(e) => setRForm({ ...rForm, signal_type: e.target.value })}>
              <option value="momentum">momentum (sign of rolling mean)</option>
              <option value="mean_reversion">mean reversion (fade z-score)</option>
            </select></div>
          <div className="field"><div className="label">Window (days)</div>
            <input type="number" value={rForm.window}
                   onChange={(e) => setRForm({ ...rForm, window: e.target.value })} /></div>
          {rForm.signal_type === "mean_reversion" && (
            <div className="field"><div className="label">Z entry</div>
              <input type="number" step="0.1" value={rForm.z_entry}
                     onChange={(e) => setRForm({ ...rForm, z_entry: e.target.value })} /></div>)}
          <div className="field"><div className="label">Cost (bps round-trip)</div>
            <input type="number" value={rForm.cost_bps}
                   onChange={(e) => setRForm({ ...rForm, cost_bps: e.target.value })} /></div>
          <div className="field"><div className="label">Sweep</div>
            <label style={{ fontSize: "var(--fs-12)", display: "block" }}>
              <input type="checkbox" checked={rForm.use_sweep}
                     onChange={(e) => setRForm({ ...rForm, use_sweep: e.target.checked })} />{" "}
              sweep windows (every combo is a recorded trial)
            </label>
            {rForm.use_sweep && (
              <input value={rForm.sweep_windows}
                     onChange={(e) => setRForm({ ...rForm, sweep_windows: e.target.value })} />)}
          </div>
        </div>
        <button className="action" disabled={rBusy || !rForm.hypothesis_id} onClick={launch}>
          {rBusy ? "running CPCV + permutation + gates… (30–90s)" : "Run research pipeline"}
        </button>
        <p className="muted" style={{ fontSize: "var(--fs-115)" }}>
          Every evaluated combination increments the dataset's trial count (DSR
          honesty). A NO_GO is a result, not a failure — it lands in the archive.
        </p>

        {run && (
          <div style={{ marginTop: 12 }}>
            {run.gate_failed && (
              <div className="error-box">
                <b>Process gate stopped the run</b> — {run.gate_failed}
                <div className="muted" style={{ fontSize: "var(--fs-115)" }}>
                  Sweep trials were still recorded (n_trials now {run.n_trials_used}).
                </div>
              </div>
            )}

            {p && (
              <div className="grid cols-2">
                <div>
                  <p>
                    Verdict: <Verdict v={p.verdict} />{" "}
                    {p.verdict !== p.suggested_verdict && (
                      <span className="chip warn">override (suggested {p.suggested_verdict})</span>)}
                  </p>
                  <p className="muted" style={{ fontSize: "var(--fs-12)" }}>{p.verdict_rationale}</p>
                  <table className="data">
                    <tbody>
                      <tr><td className="muted">DSR (n_trials {run.n_trials_used})</td>
                          <td><b>{num(p.dsr)}</b></td>
                          <td className="muted">PBO</td><td><b>{num(p.pbo)}</b></td></tr>
                      <tr><td className="muted">Sharpe (ann)</td><td>{num(p.sr_annual, 2)}</td>
                          <td className="muted">haircut SR</td>
                          <td style={{ color: p.viable_after_haircut ? "var(--green)" : "var(--red)" }}>
                            {num(p.production_haircut_sr, 2)}</td></tr>
                      <tr><td className="muted">permutation p</td><td>{num(p.permutation_p, 4)}</td>
                          <td className="muted">Ljung-Box p</td><td>{num(p.ljung_box_pvalue, 4)}</td></tr>
                      <tr><td className="muted">min track record</td>
                          <td>{num(p.min_track_record_years, 1)}y</td>
                          <td className="muted">P[strategy fails]</td>
                          <td>{num(p.strategy_risk_prob_failure, 3)}</td></tr>
                    </tbody>
                  </table>
                  <p style={{ fontSize: "var(--fs-12)" }}>
                    gates passed: {(p.gates_passed ?? []).map((g: string) => (
                      <span key={g} className="chip ok" style={{ marginRight: 4 }}>{g}</span>))}
                    {(p.gates_failed ?? []).map((g: string) => (
                      <span key={g} className="chip bad" style={{ marginRight: 4 }}>{g}</span>))}
                  </p>
                </div>
                <div>
                  {(p.cpcv_path_sharpes ?? []).length > 0 && (
                    <Plot
                      data={[{ type: "bar",
                               x: p.cpcv_path_sharpes.map((_: any, i: number) => `path ${i + 1}`),
                               y: p.cpcv_path_sharpes, marker: { color: plotTheme.accent } }]}
                      layout={{ ...plotTheme.layout, height: 220,
                                title: { text: "CPCV path Sharpes" } }}
                      useResizeHandler style={{ width: "100%" }}
                      config={{ displaylogo: false }} />
                  )}
                  {p.regime_conditional_sharpes && (
                    <table className="data">
                      <thead><tr><th>Regime</th><th>Sharpe</th><th>n</th></tr></thead>
                      <tbody>
                        {Object.entries<any>(p.regime_conditional_sharpes).map(([k, v]) => (
                          <tr key={k}><td className="muted">{k}</td>
                            <td style={{ color: (v.sharpe ?? v) < 0 ? "var(--red)" : "var(--green)" }}>
                              {num(v.sharpe ?? v, 2)}</td>
                            <td>{v.n_obs ?? "—"}</td></tr>))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            )}

            {run.sweep?.length > 0 && (
              <>
                <h3 style={{ marginTop: 10 }}>Sweep ({run.sweep.length} configs — median is the finding, not the peak)</h3>
                <div style={{ maxHeight: 220, overflow: "auto" }}>
                  <table className="data">
                    <thead><tr>{Object.keys(run.sweep[0]).slice(0, 8).map((k) => <th key={k}>{k}</th>)}</tr></thead>
                    <tbody>
                      {run.sweep.map((row: any, i: number) => (
                        <tr key={i}>{Object.keys(run.sweep[0]).slice(0, 8).map((k) => (
                          <td key={k}>{typeof row[k] === "number" ? num(row[k], 3) : String(row[k])}</td>))}</tr>))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {run.warnings?.length > 0 && (
              <details style={{ marginTop: 8 }}>
                <summary className="muted" style={{ cursor: "pointer", fontSize: "var(--fs-12)" }}>
                  {run.warnings.length} pipeline warnings</summary>
                {run.warnings.map((w: string, i: number) => (
                  <p key={i} className="muted" style={{ fontSize: "var(--fs-115)" }}>⚠ {w}</p>))}
              </details>
            )}
          </div>
        )}
      </div>

      <div className="grid cols-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Current Jordan contract (research_verdict.json)</h3>
          {!verdict ? <p className="muted">not written yet.</p> : (
            <>
              <p><Verdict v={verdict.verdict} />{" "}
                <span className="mono" style={{ fontSize: "var(--fs-115)" }}>{verdict.hypothesis_id}</span></p>
              <table className="data">
                <tbody>
                  <tr><td className="muted">haircut Sharpe</td><td>{num(verdict.production_haircut_sharpe, 3)}</td>
                      <td className="muted">viable</td>
                      <td>{verdict.viable_after_haircut
                        ? <span className="chip ok">yes</span> : <span className="chip bad">no</span>}</td></tr>
                  <tr><td className="muted">DSR</td><td>{num(verdict.dsr)}</td>
                      <td className="muted">PBO</td><td>{num(verdict.pbo)}</td></tr>
                  <tr><td className="muted">n_trials</td><td>{verdict.n_trials}</td>
                      <td className="muted">regime @ verdict</td><td>{verdict.regime_at_verdict ?? "—"}</td></tr>
                  <tr><td className="muted">written</td><td colSpan={3} className="mono"
                        style={{ fontSize: "var(--fs-11)" }}>{verdict.written_at}</td></tr>
                </tbody>
              </table>
              <p className="muted" style={{ fontSize: "var(--fs-11)" }}>{verdict.staleness_guidance}</p>
            </>
          )}
        </div>

        <div className="card">
          <h3>Gates (registry — edit on Parameters page)</h3>
          {gates && (
            <>
              <table className="data">
                <tbody>
                  {gates.gates.map((g: any) => (
                    <tr key={g.field} title={g.help ?? ""}>
                      <td className="muted">{g.label}{g.guarded && " 🔒"}</td>
                      <td><b>{g.value}</b></td>
                    </tr>))}
                </tbody>
              </table>
              <p className="muted" style={{ fontSize: "var(--fs-11)" }}>{gates.note}</p>
            </>
          )}
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Run archive ({runs.length})</h3>
        <div className="tabs">
          {["", "GO", "NO_GO"].map((f) => (
            <button key={f} className={runFilter === f ? "active" : ""}
                    onClick={() => { setRunFilter(f); loadRuns(f); }}>
              {f === "" ? "All" : f === "NO_GO" ? "Failure archive" : "GO"}
            </button>))}
        </div>
        {runs.length === 0 ? <p className="muted">no runs logged.</p> : (
          <table className="data">
            <thead><tr><th>Run</th><th>Verdict</th><th>DSR</th><th>Prod SR</th>
                       <th>Hypothesis</th><th>Logged</th></tr></thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id}>
                  <td>{r.run_name}</td>
                  <td><Verdict v={r.verdict} /></td>
                  <td>{num(r.dsr_primary)}</td>
                  <td>{num(r.production_sr, 2)}</td>
                  <td className="mono" style={{ fontSize: "var(--fs-105)" }}>{String(r.hypothesis_id).slice(0, 30)}…</td>
                  <td className="muted" style={{ fontSize: "var(--fs-11)" }}>{String(r.logged_at).slice(0, 16)}</td>
                </tr>))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

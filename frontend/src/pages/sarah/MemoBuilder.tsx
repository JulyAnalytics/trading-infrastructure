import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../../api";
import { usePlotTheme } from "../../theme";
import RcsIntakePanel from "../../components/RcsIntakePanel";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";

const Plot = createPlotlyComponent(Plotly);

const CATALYSTS = ["macro_slow", "macro_catalyst", "event_specific", "technical"];

function KV({ obj, keys }: { obj: any; keys: [string, string][] }) {
  return (
    <table className="data">
      <tbody>
        {keys.map(([k, label]) =>
          obj?.[k] == null ? null : (
            <tr key={k}>
              <td className="muted">{label}</td>
              <td><b>{typeof obj[k] === "number" ? Number(obj[k]).toLocaleString() : String(obj[k])}</b></td>
            </tr>
          ),
        )}
      </tbody>
    </table>
  );
}

function MemoView({ memo }: { memo: any }) {
  const plotTheme = usePlotTheme();
  const ms = memo.market_state ?? {};
  const dist = ms.distribution ?? {};
  const sc = memo.structure_comparison ?? {};
  const affordable = new Set(Object.keys(sc.affordable ?? {}));
  const density = (dist.density_points ?? []) as { strike: number; prob_mass: number }[];

  return (
    <>
      {memo.memo_id && (
        <p>
          <span className="chip ok">saved</span>{" "}
          <b className="mono">{memo.memo_id}</b>{" "}
          <span className="muted">— stable ID for RCS cross-links</span>
          {memo.rcs_trade_ulid && (
            <>
              {" · "}
              <span className="muted">RCS trade </span>
              <b className="mono">{memo.rcs_trade_ulid}</b>
            </>
          )}
        </p>
      )}
      <p className="muted" style={{ fontSize: "var(--fs-115)" }}>{memo.data_warning}</p>

      <div className="grid cols-3">
        <div className="card">
          <h3>Panel 1 — vol level</h3>
          <KV obj={ms.vol_level} keys={[
            ["atm_iv_30d", "ATM IV 30d"], ["iv_rank", "IV rank"],
            ["iv_percentile", "IV percentile"], ["ivr_confidence", "IVR confidence"],
            ["cost_burden", "Cost burden"], ["daily_theta_approx", "Daily theta ≈"],
            ["monthly_carry_vpts", "Carry (vpts)"],
            ["carry_horizon_days", "…over (days)"],
            ["roll_down_vpts", "Roll-down (vpts)"],
            ["roll_adjusted_carry_vpts", "Roll-adj carry (vpts)"],
            ["be_move_pct", "BE move %"], ["iv_52w_pctile", "52w IV pctile"],
          ]} />
          {ms.vol_level?.carry_note && (
            <p className="muted" style={{ fontSize: "var(--fs-11)" }}>{ms.vol_level.carry_note}</p>
          )}
          {ms.vol_level?.roll_carry_note && (
            <p className="muted" style={{ fontSize: "var(--fs-11)" }}>{ms.vol_level.roll_carry_note}</p>
          )}
        </div>
        <div className="card">
          <h3>Panel 2 — term structure</h3>
          <KV obj={ms.term_structure} keys={[
            ["ts_shape", "Shape"], ["front_slope", "Front slope"],
            ["back_slope", "Back slope"], ["front_slope_pctile", "Front slope pctile"],
            ["iv_30d", "IV 30d"], ["iv_60d", "IV 60d"], ["iv_180d", "IV 180d"],
            ["thesis_exp_iv", "IV @ thesis exp"],
            ["event_premium_vpts", "Event premium (vpts)"],
            ["roll_cost_total", "Roll cost total"],
          ]} />
          {ms.term_structure?.optimal_expiration && (
            <p className="muted" style={{ fontSize: "var(--fs-115)" }}>
              Recommended DTE <b>{ms.term_structure.optimal_expiration.recommended_dte}</b>{" "}
              (IV {ms.term_structure.optimal_expiration.recommended_iv}) —{" "}
              {ms.term_structure.optimal_expiration.reason}
            </p>
          )}
        </div>
        <div className="card">
          <h3>Panel 3 — skew</h3>
          <KV obj={ms.skew} keys={[
            ["skew_25d_rr", "25Δ RR"], ["skew_25d_put", "25Δ put IV"],
            ["skew_25d_call", "25Δ call IV"], ["skew_1025_ratio", "25/10Δ ratio"],
            ["tail_steepness", "Tail steepness"], ["skew_rr_pctile", "RR pctile"],
            ["put_wing_premium", "Put wing premium"],
          ]} />
          {ms.skew?.directional_context && (
            <p className="muted" style={{ fontSize: "var(--fs-115)" }}>
              {ms.skew.directional_context.description}
            </p>
          )}
        </div>
      </div>

      {ms.flow && (
        <div className="card" style={{ marginTop: 14 }}>
          <h3>Panel 4 — flow observation</h3>
          <KV obj={ms.flow} keys={[
            ["net_delta_description", "Net delta"], ["execution_character", "Execution"],
            ["size_contracts", "Size (contracts)"], ["expiration_dte", "Flow DTE"],
            ["expiration_alignment", "Thesis alignment"], ["size_context", "Size context"],
            ["pc_oi_ratio", "P/C OI ratio"], ["notes", "Notes"],
          ]} />
        </div>
      )}

      <div className="grid cols-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Panel 5 — implied distribution (BL)</h3>
          {dist.error ? (
            <div className="error-box">{dist.error}</div>
          ) : (
            <>
              {!dist.reliable && dist.quality_note && (
                <div className="error-box" style={{ fontSize: "var(--fs-115)" }}>{dist.quality_note}</div>
              )}
              {density.length > 0 && (
                <Plot
                  data={[{ type: "bar", x: density.map((d) => d.strike),
                           y: density.map((d) => d.prob_mass),
                           marker: { color: plotTheme.accent } }]}
                  layout={{ ...plotTheme.layout, height: 260,
                            margin: { ...plotTheme.layout.margin, t: 10 },
                            xaxis: { title: { text: "strike" }, ...plotTheme.layout.xaxis },
                            yaxis: { title: { text: "prob mass" }, ...plotTheme.layout.yaxis } }}
                  useResizeHandler style={{ width: "100%" }}
                  config={{ displaylogo: false, responsive: true }} />
              )}
              <KV obj={dist} keys={[
                ["expiration_used", "Expiration used"], ["dte_used", "DTE"],
                ["total_mass", "Total mass"], ["iem_1sd_pct", "Implied 1SD move %"],
                ["prob_up_10pct", "P(+10%)"], ["prob_dn_10pct", "P(−10%)"],
                ["implied_skewness", "Implied skewness"],
                ["implied_kurtosis", "Implied excess kurtosis"],
              ]} />
            </>
          )}
        </div>

        <div className="card">
          <h3>Structure comparison</h3>
          <table className="data">
            <thead>
              <tr><th>Structure</th><th>Cost</th><th>Max loss</th>
                  <th>P&L @ +move</th><th>P&L @ −move</th><th></th></tr>
            </thead>
            <tbody>
              {Object.entries<any>(sc.all_structures ?? {}).map(([name, s]) => (
                <tr key={name}>
                  <td>{name.replaceAll("_", " ")}</td>
                  <td>{s.cost?.toLocaleString()}</td>
                  <td>{s.max_loss?.toLocaleString()}</td>
                  <td style={{ color: s.pnl_at_up < 0 ? "var(--red)" : "var(--green)" }}>
                    {s.pnl_at_up?.toLocaleString()}
                  </td>
                  <td style={{ color: s.pnl_at_dn < 0 ? "var(--red)" : "var(--green)" }}>
                    {s.pnl_at_dn?.toLocaleString()}
                  </td>
                  <td>{affordable.has(name)
                    ? <span className="chip ok">in budget</span>
                    : <span className="chip bad">over budget</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted" style={{ fontSize: "var(--fs-115)" }}>{sc.note}</p>
        </div>
      </div>
    </>
  );
}

export default function MemoBuilder({ tickers }: { tickers: string[] }) {
  const [form, setForm] = useState<any>({
    ticker: "SPY", expected_move: "8", thesis_days: "30",
    catalyst_type: "macro_catalyst", max_loss_budget: "600", direction: "0",
  });
  const [cat, setCat] = useState<any>(null);
  const [catBusy, setCatBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [memo, setMemo] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [intakeUlid, setIntakeUlid] = useState<string | null>(null);
  const [implied, setImplied] = useState<any>(null);

  const loadHistory = () =>
    apiGet<{ memos: any[] }>("/api/sarah/memos").then((r) => setHistory(r.memos)).catch(() => {});
  useEffect(() => { loadHistory(); }, []);

  /** Pull an RCS intake row into the form. expected_move is deliberately
   *  CLEARED, never pre-filled from the implied move — the memo's whole job
   *  is to price your belief against what the market implies. */
  const loadIntake = (row: any) => {
    setIntakeUlid(row.rcs_trade_ulid);
    setImplied(row.implied_move_reference ?? null);
    setCat(null);
    setError(null);
    setForm({
      ticker: row.ticker ?? "",
      expected_move: "",
      thesis_days: row.thesis_days != null ? String(row.thesis_days) : "",
      catalyst_type: row.catalyst_type ?? "macro_catalyst",
      max_loss_budget: row.max_loss_budget != null ? String(row.max_loss_budget) : "",
      direction: row.expected_move_sign != null ? String(row.expected_move_sign) : "0",
    });
  };

  const clearIntake = () => { setIntakeUlid(null); setImplied(null); };

  const resolveCatalyst = async () => {
    setCatBusy(true); setCat(null);
    try {
      const r = await apiGet(`/api/sarah/catalysts/${form.ticker}`);
      setCat(r);
      if (r.primary) {
        setForm((f: any) => ({
          ...f,
          catalyst_type: r.primary.catalyst_type,
          thesis_days: String(r.primary.thesis_days),
        }));
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setCatBusy(false);
    }
  };

  /** Number("") === 0, so an empty numeric field would otherwise be submitted
   *  as a real zero. A zero expected_move renders a complete-looking memo in
   *  which every candidate strike has collapsed onto ATM — worse than an
   *  error, because it looks like an answer. Empty stays empty. */
  const num = (v: any): number | null => {
    if (v === "" || v === null || v === undefined) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };

  const build = async () => {
    const move = num(form.expected_move);
    const days = num(form.thesis_days);
    const budget = num(form.max_loss_budget);
    const blank = [
      move === null && "expected move",
      days === null && "thesis horizon",
      budget === null && "max loss budget",
    ].filter(Boolean);
    if (blank.length) {
      setError(`Fill in: ${blank.join(", ")}.`);
      return;
    }
    if (move === 0) {
      setError(
        "Expected move is 0% — the memo prices structures at ±your move, so a " +
        "zero move collapses every strike onto ATM and the comparison becomes " +
        "meaningless. Enter the magnitude you believe in.");
      return;
    }

    setBusy(true); setError(null); setMemo(null);
    try {
      const body: any = {
        ticker: form.ticker,
        expected_move: (move as number) / 100,
        thesis_days: days,
        catalyst_type: form.catalyst_type,
        max_loss_budget: budget,
      };
      if (form.direction !== "0") body.expected_move_sign = Number(form.direction);
      // Carries the citation key so the PTM id ↔ RCS trade link is structural.
      if (intakeUlid) body.rcs_trade_ulid = intakeUlid;
      const r = await apiSend("/api/sarah/memo", "POST", body);
      setMemo(r);
      loadHistory();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const openMemo = async (id: string) => {
    setError(null);
    try { setMemo(await apiGet(`/api/sarah/memos/${id}`)); }
    catch (e: any) { setError(e.message); }
  };

  return (
    <>
      {error && <div className="error-box">{error}</div>}

      <RcsIntakePanel title="RCS trade intake" onLoad={loadIntake}
                      activeUlid={intakeUlid} onClearActive={clearIntake} />

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Trade thesis (Stage 4 — no direction recommended, cost basis only)</h3>
        <div className="grid cols-3">
          <div className="field"><div className="label">Ticker</div>
            <input list="memo-tickers" value={form.ticker}
                   onChange={(e) => setForm({ ...form, ticker: e.target.value.toUpperCase() })} />
            <datalist id="memo-tickers">
              {tickers.map((t) => <option key={t} value={t} />)}
            </datalist></div>
          <div className="field">
            <div className="label">Expected move (± %) — your forecast</div>
            <input type="number" step="any" value={form.expected_move}
                   placeholder="your belief, in %"
                   onChange={(e) => setForm({ ...form, expected_move: e.target.value })} />
            {implied && (
              <p className="muted" style={{ fontSize: "var(--fs-11)", marginTop: 4 }}>
                Market implies <b>±{(implied.implied_move * 100).toFixed(2)}%</b>{" "}
                over {implied.horizon_days}d (ATM IV {implied.atm_iv_30d},{" "}
                {implied.as_of}) — reference only, not a default.
              </p>
            )}
          </div>
          <div className="field"><div className="label">Thesis horizon (days)</div>
            <input type="number" value={form.thesis_days}
                   onChange={(e) => setForm({ ...form, thesis_days: e.target.value })} /></div>
          <div className="field"><div className="label">Catalyst type</div>
            <select value={form.catalyst_type}
                    onChange={(e) => setForm({ ...form, catalyst_type: e.target.value })}>
              {CATALYSTS.map((c) => <option key={c} value={c}>{c}</option>)}
            </select></div>
          <div className="field"><div className="label">Max loss budget ($/contract)</div>
            <input type="number" value={form.max_loss_budget}
                   onChange={(e) => setForm({ ...form, max_loss_budget: e.target.value })} /></div>
          <div className="field"><div className="label">Direction (optional)</div>
            <select value={form.direction}
                    onChange={(e) => setForm({ ...form, direction: e.target.value })}>
              <option value="0">symmetric / undisclosed</option>
              <option value="1">up bias (call wing)</option>
              <option value="-1">down bias (put wing)</option>
            </select></div>
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className="action secondary" disabled={catBusy} onClick={resolveCatalyst}>
            {catBusy ? "looking up…" : "Auto-resolve catalyst (U4.3)"}
          </button>
          <button className="action" disabled={busy} onClick={build}>
            {busy ? "building memo…" : "Build pre-trade memo"}
          </button>
        </div>

        {cat && (cat.requires_manual ? (
          <p className="muted" style={{ fontSize: "var(--fs-12)" }}>{cat.note}</p>
        ) : (
          <div style={{ marginTop: 8 }}>
            <p className="muted" style={{ fontSize: "var(--fs-12)" }}>{cat.note}</p>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {cat.all_candidates.map((c: any, i: number) => (
                <button key={i} className="action secondary" style={{ fontSize: "var(--fs-115)" }}
                        onClick={() => setForm((f: any) => ({
                          ...f, catalyst_type: c.catalyst_type,
                          thesis_days: String(c.thesis_days),
                        }))}>
                  {c.event} · {c.date} · {c.thesis_days}d
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {memo && <div style={{ marginTop: 14 }}><MemoView memo={memo} /></div>}

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Memo history ({history.length})</h3>
        {history.length === 0 ? (
          <p className="muted">no persisted memos yet.</p>
        ) : (
          <table className="data">
            <thead>
              <tr><th>ID</th><th>Ticker</th><th>Date</th><th>Catalyst</th>
                  <th>Move</th><th>Days</th><th>Budget</th></tr>
            </thead>
            <tbody>
              {history.map((m) => (
                <tr key={m.memo_id} style={{ cursor: "pointer" }}
                    onClick={() => openMemo(m.memo_id)}>
                  <td className="mono">{m.memo_id}</td>
                  <td><b>{m.ticker}</b></td>
                  <td className="muted">{String(m.date).slice(0, 10)}</td>
                  <td>{m.catalyst_type}</td>
                  <td>±{(Number(m.expected_move) * 100).toFixed(1)}%</td>
                  <td>{m.thesis_days}</td>
                  <td>${Number(m.max_loss_budget).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

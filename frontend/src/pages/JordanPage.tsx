import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../api";

export default function JordanPage() {
  const [book, setBook] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [intake, setIntake] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [sizing, setSizing] = useState<any>(null);
  const [sizeForm, setSizeForm] = useState({ entry: "", stop: "", risk_pct: "" });
  const [posForm, setPosForm] = useState<any>({
    ticker: "", asset_type: "equity", quantity: "", long_short: "long",
    flag: "c", strike: "", expiration: "", entry_price: "",
  });

  const loadBook = () => apiGet("/api/jordan/book").then(setBook).catch((e) => setError(e.message));

  useEffect(() => {
    loadBook();
    apiGet("/api/jordan/verdict-intake").then(setIntake).catch(() => {});
  }, []);

  const analyze = async (withStress: boolean) => {
    setAnalyzing(true); setError(null);
    try {
      setResult(await apiSend("/api/jordan/analyze", "POST", { include_stress: withStress }));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setAnalyzing(false);
    }
  };

  const addPosition = async () => {
    setError(null);
    try {
      const body: any = { ...posForm, quantity: Number(posForm.quantity) };
      if (body.asset_type === "option") body.strike = Number(body.strike);
      if (body.entry_price) body.entry_price = Number(body.entry_price);
      await apiSend("/api/jordan/positions", "POST", body);
      setPosForm({ ...posForm, ticker: "", quantity: "", strike: "", expiration: "" });
      await loadBook();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const runSize = async () => {
    setError(null);
    try {
      setSizing(await apiSend("/api/jordan/size", "POST", {
        entry: Number(sizeForm.entry), stop: Number(sizeForm.stop),
        risk_pct: sizeForm.risk_pct ? Number(sizeForm.risk_pct) : undefined,
      }));
    } catch (e: any) {
      setError(e.message);
    }
  };

  const limits = result?.limits;
  const analysis = result?.analysis;
  const stress = result?.stress;

  return (
    <div>
      <h2>Jordan — Risk</h2>
      {error && <div className="error-box">{error}</div>}

      {limits && (limits.breaches.length > 0 ? (
        <div className="error-box"><b>LIMIT BREACHES</b>{"\n"}{limits.breaches.join("\n")}</div>
      ) : (
        <div className="ok-box">All limits within bounds (NAV ${Number(limits.nav).toLocaleString()}).</div>
      ))}

      <div className="card">
        <h3>
          Book{" "}
          {book?.rcs?.available === false
            ? <span className="chip bad">RCS bridge offline: {book.rcs.reason}</span>
            : <span className="chip ok">RCS linked (read-only)</span>}
          <span className="chip">{book?.counts?.rcs ?? 0} from RCS</span>
          <span className="chip">{book?.counts?.manual ?? 0} manual</span>
        </h3>
        <table className="data">
          <thead>
            <tr><th>Source</th><th>Ticker</th><th>Type</th><th>Detail</th><th>Qty</th><th>Side</th><th></th></tr>
          </thead>
          <tbody>
            {(book?.positions ?? []).map((p: any) => (
              <tr key={p.id}>
                <td>{p.source === "rcs" && p.rcs_url
                  ? <a href={p.rcs_url} target="_blank" rel="noreferrer">RCS ↗</a>
                  : p.source}</td>
                <td>{p.ticker}</td>
                <td>{p.asset_type}</td>
                <td className="muted">
                  {p.asset_type === "option" ? `${p.strike}${p.flag?.toUpperCase()} ${p.expiration}` : "shares"}
                </td>
                <td>{p.quantity}</td>
                <td>{p.long_short}</td>
                <td>
                  {p.source === "manual" && (
                    <button className="action secondary" style={{ padding: "2px 8px" }}
                            onClick={() => apiSend(`/api/jordan/positions/${p.id}/close`, "POST").then(loadBook)}>
                      close
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ marginTop: 10 }}>
          <button className="action" disabled={analyzing} onClick={() => analyze(false)}>
            {analyzing ? "pricing book…" : "Analyze book (live greeks)"}
          </button>{" "}
          <button className="action secondary" disabled={analyzing} onClick={() => analyze(true)}>
            Analyze + stress
          </button>
        </div>
      </div>

      {analysis && (
        <div className="grid cols-2" style={{ marginTop: 14 }}>
          <div className="card">
            <h3>Net exposure <span className="chip">{analysis.as_of}</span></h3>
            <table className="data">
              <tbody>
                <tr><td>Net delta ($)</td><td>{analysis.net_delta_dollars.toLocaleString()}</td></tr>
                <tr><td>Net vega ($/vol-pt)</td><td>{analysis.net_vega_dollars.toLocaleString()}</td></tr>
                <tr><td>Gross notional</td><td>{analysis.gross_notional.toLocaleString()}</td></tr>
                {Object.entries<any>(analysis.net_greeks ?? {}).map(([g, v]) => (
                  <tr key={g}><td>net {g}</td><td>{Number(v).toFixed(4)}</td></tr>
                ))}
              </tbody>
            </table>
            {analysis.errors.length > 0 && (
              <div className="notice-box">
                {analysis.errors.length} position(s) failed pricing:{" "}
                {analysis.errors.map((e: any) => e.position?.ticker).join(", ")}
              </div>
            )}
            <p className="muted" style={{ fontSize: "var(--fs-115)" }}>{analysis.data_warning}</p>
          </div>

          <div className="card">
            <h3>Limit checks</h3>
            <table className="data">
              <tbody>
                {Object.entries<any>(limits.checks).map(([name, c]) => (
                  <tr key={name}>
                    <td>{c.label}</td>
                    <td>{c.value !== undefined ? `${(c.value * 100).toFixed(1)}%` : c.note ?? "—"}</td>
                    <td>
                      <span className={"chip " + (c.breached ? "bad" : c.note ? "" : "ok")}>
                        {c.breached ? "BREACH" : c.note ? "n/a" : "ok"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {stress && (
        <div className="card" style={{ marginTop: 14 }}>
          <h3>
            Book stress{" "}
            {stress.worst_case && (
              <span className="chip bad">
                worst: {stress.worst_case.label} {stress.worst_case.pnl_skew_amplified.toLocaleString()}
              </span>
            )}
          </h3>
          <table className="data">
            <thead>
              <tr><th>Scenario</th><th>Spot</th><th>Vol (vpts)</th><th>P&L flat</th><th>P&L skew-amp</th></tr>
            </thead>
            <tbody>
              {Object.values<any>(stress.scenarios).map((s) => (
                <tr key={s.label}>
                  <td>{s.label} <span className="muted">({s.duration})</span></td>
                  <td>{(s.spot_shock * 100).toFixed(0)}%</td>
                  <td>+{s.vol_shock_vpts}</td>
                  <td style={{ color: s.pnl_flat < 0 ? "var(--red)" : "var(--green)" }}>
                    {s.pnl_flat.toLocaleString()}
                  </td>
                  <td style={{ color: s.pnl_skew_amplified < 0 ? "var(--red)" : "var(--green)" }}>
                    {s.pnl_skew_amplified.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted" style={{ fontSize: "var(--fs-115)" }}>{stress.methodology_note}</p>
        </div>
      )}

      <div className="grid cols-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Verdict intake (Priya → Jordan)</h3>
          {intake ? (
            <>
              <div className={intake.actionable ? "ok-box" : "notice-box"}>
                {intake.actionable
                  ? "Verdict is actionable — all intake checks pass."
                  : intake.note ?? "Not actionable."}
              </div>
              <table className="data">
                <tbody>
                  {intake.checks.map((c: any) => (
                    <tr key={c.name}>
                      <td>{c.name}</td>
                      <td>
                        <span className={"chip " + (c.ok === true ? "ok" : c.ok === false ? "bad" : "warn")}>
                          {c.ok === true ? "pass" : c.ok === false ? "fail" : "unknown"}
                        </span>
                      </td>
                      <td className="muted">{c.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <p className="muted">loading…</p>
          )}
        </div>

        <div className="card">
          <h3>Position sizing</h3>
          <div className="grid cols-3">
            <div className="field"><div className="label">Entry</div>
              <input type="number" step="any" value={sizeForm.entry}
                     onChange={(e) => setSizeForm({ ...sizeForm, entry: e.target.value })} /></div>
            <div className="field"><div className="label">Stop</div>
              <input type="number" step="any" value={sizeForm.stop}
                     onChange={(e) => setSizeForm({ ...sizeForm, stop: e.target.value })} /></div>
            <div className="field"><div className="label">Risk % (blank = default)</div>
              <input type="number" step="any" value={sizeForm.risk_pct}
                     onChange={(e) => setSizeForm({ ...sizeForm, risk_pct: e.target.value })} /></div>
          </div>
          <button className="action" onClick={runSize} disabled={!sizeForm.entry || !sizeForm.stop}>
            Suggest size
          </button>
          {sizing && (
            <div className="ok-box">
              {sizing.units.toLocaleString()} units (≈${sizing.notional.toLocaleString()}) risking $
              {sizing.risk_dollars.toLocaleString()} ({(sizing.risk_pct * 100).toFixed(2)}% of NAV)
              {sizing.capped_by ? ` — capped by ${sizing.capped_by}` : ""}
            </div>
          )}
          <p className="muted" style={{ fontSize: "var(--fs-115)" }}>
            Size = (NAV × risk%) / |entry − stop|. NAV and limits are registry
            parameters (Jordan tab on the Parameters page).
          </p>
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Add manual position</h3>
        <div className="grid cols-3">
          <div className="field"><div className="label">Ticker</div>
            <input value={posForm.ticker}
                   onChange={(e) => setPosForm({ ...posForm, ticker: e.target.value.toUpperCase() })} /></div>
          <div className="field"><div className="label">Type</div>
            <select value={posForm.asset_type}
                    onChange={(e) => setPosForm({ ...posForm, asset_type: e.target.value })}>
              <option value="equity">equity</option>
              <option value="option">option</option>
            </select></div>
          <div className="field"><div className="label">Side</div>
            <select value={posForm.long_short}
                    onChange={(e) => setPosForm({ ...posForm, long_short: e.target.value })}>
              <option value="long">long</option>
              <option value="short">short</option>
            </select></div>
          <div className="field"><div className="label">Quantity</div>
            <input type="number" step="any" value={posForm.quantity}
                   onChange={(e) => setPosForm({ ...posForm, quantity: e.target.value })} /></div>
          {posForm.asset_type === "option" && (
            <>
              <div className="field"><div className="label">Call/Put</div>
                <select value={posForm.flag}
                        onChange={(e) => setPosForm({ ...posForm, flag: e.target.value })}>
                  <option value="c">call</option>
                  <option value="p">put</option>
                </select></div>
              <div className="field"><div className="label">Strike</div>
                <input type="number" step="any" value={posForm.strike}
                       onChange={(e) => setPosForm({ ...posForm, strike: e.target.value })} /></div>
              <div className="field"><div className="label">Expiration (YYYY-MM-DD)</div>
                <input value={posForm.expiration}
                       onChange={(e) => setPosForm({ ...posForm, expiration: e.target.value })} /></div>
            </>
          )}
        </div>
        <button className="action" onClick={addPosition}
                disabled={!posForm.ticker || !posForm.quantity}>
          Add position
        </button>
        <p className="muted" style={{ fontSize: "var(--fs-115)" }}>
          Prefer journaling trades in the RCS — they appear here automatically.
          Manual entries are for anything outside the journal.
        </p>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../api";
import PlotlyFig from "../components/PlotlyFig";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";

const Plot = createPlotlyComponent(Plotly);

const CONF_CLASS: Record<string, string> = {
  standard: "ok", medium: "warn", low: "warn", insufficient: "bad",
};

export default function SarahPage() {
  const [signals, setSignals] = useState<any[] | null>(null);
  const [ticker, setTicker] = useState<string>("SPY");
  const [error, setError] = useState<string | null>(null);

  // greeks tool
  const [gForm, setGForm] = useState<any>({
    ticker: "SPY", flag: "c", strike: "", expiration: "", quantity: 1,
    long_short: "long",
  });
  const [gBusy, setGBusy] = useState(false);
  const [position, setPosition] = useState<any>(null);

  // scenario lab
  const [sBusy, setSBusy] = useState(false);
  const [scen, setScen] = useState<any>(null);
  const [checkpoint, setCheckpoint] = useState<number>(0);

  useEffect(() => {
    apiGet<{ signals: any[] }>("/api/sarah/signals")
      .then((r) => {
        setSignals(r.signals);
        if (r.signals.length) setTicker(r.signals[0].ticker);
      })
      .catch((e) => setError(e.message));
  }, []);

  const runGreeks = async () => {
    setGBusy(true); setError(null); setScen(null);
    try {
      setPosition(await apiSend("/api/sarah/greeks", "POST", {
        ...gForm, strike: Number(gForm.strike), quantity: Number(gForm.quantity),
      }));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setGBusy(false);
    }
  };

  const runScenario = async (cp: number) => {
    if (!position) return;
    setSBusy(true); setError(null);
    try {
      const r = await apiSend("/api/sarah/scenario", "POST", {
        position, checkpoint: cp,
      });
      setScen(r);
      setCheckpoint(r.checkpoint);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSBusy(false);
    }
  };

  return (
    <div>
      <h2>Sarah — Vol Workspace</h2>
      {error && <div className="error-box">{error}</div>}

      <div className="card">
        <h3>Vol monitor (latest daily run)</h3>
        {!signals ? (
          <p className="muted">no vol_signals yet — run the Sarah daily job.</p>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Ticker</th><th>Date</th><th>ATM IV 30d</th><th>IV rank</th>
                <th>VRP</th><th>TS shape</th><th>25Δ RR</th><th>Regime</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((s) => (
                <tr key={s.ticker} onClick={() => setTicker(s.ticker)}
                    style={{ cursor: "pointer",
                             outline: s.ticker === ticker ? "1px solid var(--accent)" : "none" }}>
                  <td><b>{s.ticker}</b></td>
                  <td className="muted">{String(s.date).slice(0, 10)}</td>
                  <td>{Number(s.atm_iv_30d).toFixed(1)}</td>
                  <td>
                    {s.iv_rank == null ? "—" : Number(s.iv_rank).toFixed(2)}{" "}
                    <span className={"chip " + (CONF_CLASS[s.ivr_ivp_confidence] ?? "")}>
                      {s.ivr_ivp_confidence}
                    </span>
                  </td>
                  <td>
                    {s.vrp_proxy_bkwd == null ? "—" : Number(s.vrp_proxy_bkwd).toFixed(1)}{" "}
                    <span className="muted">{s.vrp_proxy_signal}</span>
                  </td>
                  <td>{s.ts_shape}</td>
                  <td>{s.skew_25d_rr == null ? "—" : Number(s.skew_25d_rr).toFixed(2)}</td>
                  <td className="muted">{s.macro_regime}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {signals && (
        <div className="grid cols-2" style={{ marginTop: 14 }}>
          <div className="card">
            <h3>{ticker} — IV vs RV</h3>
            <PlotlyFig src={`/api/sarah/charts/iv-history/${ticker}`} />
          </div>
          <div className="card">
            <h3>{ticker} — term structure</h3>
            <PlotlyFig src={`/api/sarah/charts/term-structure/${ticker}`} />
          </div>
        </div>
      )}

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Greeks tool (Stage 2)</h3>
        <div className="grid cols-3">
          <div className="field"><div className="label">Ticker</div>
            <input value={gForm.ticker}
                   onChange={(e) => setGForm({ ...gForm, ticker: e.target.value.toUpperCase() })} /></div>
          <div className="field"><div className="label">Call/Put</div>
            <select value={gForm.flag} onChange={(e) => setGForm({ ...gForm, flag: e.target.value })}>
              <option value="c">call</option><option value="p">put</option>
            </select></div>
          <div className="field"><div className="label">Side</div>
            <select value={gForm.long_short}
                    onChange={(e) => setGForm({ ...gForm, long_short: e.target.value })}>
              <option value="long">long</option><option value="short">short</option>
            </select></div>
          <div className="field"><div className="label">Strike</div>
            <input type="number" step="any" value={gForm.strike}
                   onChange={(e) => setGForm({ ...gForm, strike: e.target.value })} /></div>
          <div className="field"><div className="label">Expiration (YYYY-MM-DD)</div>
            <input value={gForm.expiration}
                   onChange={(e) => setGForm({ ...gForm, expiration: e.target.value })} /></div>
          <div className="field"><div className="label">Contracts</div>
            <input type="number" value={gForm.quantity}
                   onChange={(e) => setGForm({ ...gForm, quantity: e.target.value })} /></div>
        </div>
        <button className="action" disabled={gBusy || !gForm.strike || !gForm.expiration}
                onClick={runGreeks}>
          {gBusy ? "pricing…" : "Analyze position"}
        </button>

        {position && (
          <>
            <pre className="mono" style={{
              background: "var(--bg)", border: "1px solid var(--border)",
              borderRadius: 6, padding: 12, whiteSpace: "pre-wrap",
              fontSize: 11.5, marginTop: 12,
            }}>{position.interpretation}</pre>
            <button className="action secondary" disabled={sBusy}
                    onClick={() => runScenario(0)}>
              {sBusy ? "running scenarios…" : "→ Scenario lab (Stage 3)"}
            </button>
          </>
        )}
      </div>

      {scen && (
        <div className="card" style={{ marginTop: 14 }}>
          <h3>Scenario lab</h3>
          <div className="tabs">
            {scen.checkpoints.map((cp: number) => (
              <button key={cp} className={cp === checkpoint ? "active" : ""}
                      disabled={sBusy} onClick={() => runScenario(cp)}>
                {Math.round(cp * 100)}% of DTE
              </button>
            ))}
          </div>
          <Plot data={scen.grid_fig.data}
                layout={{ ...scen.grid_fig.layout, autosize: true }}
                useResizeHandler style={{ width: "100%" }}
                config={{ displaylogo: false, responsive: true }} />
          <p className="muted" style={{ fontSize: 11.5 }}>{scen.bs_limitation}</p>

          <div className="grid cols-2">
            <div>
              <h3 style={{ marginTop: 10 }}>Stress scenarios (registry library)</h3>
              <table className="data">
                <thead>
                  <tr><th>Scenario</th><th>Spot</th><th>Vol</th><th>Flat</th><th>Skew-amp</th></tr>
                </thead>
                <tbody>
                  {Object.values<any>(scen.stress).filter((s) => !s.error).map((s) => (
                    <tr key={s.scenario}>
                      <td>{s.scenario}</td>
                      <td>{s.spot_shock_pct.toFixed(0)}%</td>
                      <td>+{s.vol_shock_vpts}</td>
                      <td style={{ color: s.pnl_flat_shift < 0 ? "var(--red)" : "var(--green)" }}>
                        {s.pnl_flat_shift.toLocaleString()}
                      </td>
                      <td style={{ color: s.pnl_skew_amplified < 0 ? "var(--red)" : "var(--green)" }}>
                        {s.pnl_skew_amplified.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div>
              <h3 style={{ marginTop: 10 }}>Kill scenario</h3>
              <div className="error-box">
                Max realistic loss: <b>${scen.kill.max_realistic_loss.toLocaleString()}</b>
              </div>
              <p className="muted" style={{ fontSize: 12 }}>{scen.kill.kill_description}</p>
              <p className="muted" style={{ fontSize: 11.5 }}>
                Assumptions (IV crush {scen.kill.kill_conditions.iv_compression_vpts} vpts by day{" "}
                {scen.kill.kill_conditions.days_elapsed}) are registry parameters — Sarah tab.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

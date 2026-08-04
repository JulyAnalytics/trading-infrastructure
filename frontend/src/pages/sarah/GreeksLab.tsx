import { useState } from "react";
import { apiSend } from "../../api";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";

const Plot = createPlotlyComponent(Plotly);

export default function GreeksLab() {
  const [error, setError] = useState<string | null>(null);

  const [gForm, setGForm] = useState<any>({
    ticker: "SPY", flag: "c", strike: "", expiration: "", quantity: 1,
    long_short: "long",
  });
  const [gBusy, setGBusy] = useState(false);
  const [position, setPosition] = useState<any>(null);

  const [sBusy, setSBusy] = useState(false);
  const [scen, setScen] = useState<any>(null);
  const [checkpoint, setCheckpoint] = useState<number>(0);

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
    <>
      {error && <div className="error-box">{error}</div>}

      <div className="card">
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
              fontSize: "var(--fs-115)", marginTop: 12,
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
          <p className="muted" style={{ fontSize: "var(--fs-115)" }}>{scen.bs_limitation}</p>

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
              <p className="muted" style={{ fontSize: "var(--fs-12)" }}>{scen.kill.kill_description}</p>
              <p className="muted" style={{ fontSize: "var(--fs-115)" }}>
                Assumptions (IV crush {scen.kill.kill_conditions.iv_compression_vpts} vpts by day{" "}
                {scen.kill.kill_conditions.days_elapsed}) are registry parameters — Sarah tab.
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

import { useState } from "react";
import PlotlyFig from "../../components/PlotlyFig";

const CONF_CLASS: Record<string, string> = {
  standard: "ok", medium: "warn", low: "warn", insufficient: "bad",
};

export default function VolMonitor({
  signals, loadError,
}: { signals: any[] | null; loadError: string | null }) {
  const [ticker, setTicker] = useState<string>("SPY");

  const active =
    signals?.find((s) => s.ticker === ticker)?.ticker ?? signals?.[0]?.ticker;

  return (
    <>
      {loadError && <div className="error-box">{loadError}</div>}

      <div className="card">
        <h3>Latest daily run</h3>
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
                             outline: s.ticker === active ? "1px solid var(--accent)" : "none" }}>
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

      {signals && active && (
        <>
          <div className="grid cols-2" style={{ marginTop: 14 }}>
            <div className="card">
              <h3>{active} — IV vs RV</h3>
              <PlotlyFig src={`/api/sarah/charts/iv-history/${active}`} />
            </div>
            <div className="card">
              <h3>{active} — term structure</h3>
              <PlotlyFig src={`/api/sarah/charts/term-structure/${active}`} />
            </div>
          </div>
          <div className="grid cols-2" style={{ marginTop: 14 }}>
            <div className="card">
              <h3>{active} — IV surface (strike × DTE)</h3>
              <PlotlyFig src={`/api/sarah/charts/surface/${active}`} />
            </div>
            <div className="card">
              <h3>{active} — realized vol cone (U1.1)</h3>
              <PlotlyFig src={`/api/sarah/charts/vol-cone/${active}`} />
              <p className="muted" style={{ fontSize: "var(--fs-115)" }}>
                Percentile cone of realized vol by window (Hodges-Tompkins
                corrected). Red diamond = current ATM IV 30d.
              </p>
            </div>
          </div>
        </>
      )}
    </>
  );
}

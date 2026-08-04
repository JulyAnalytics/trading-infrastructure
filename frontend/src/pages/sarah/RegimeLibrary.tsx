import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../../api";
import PlotlyFig from "../../components/PlotlyFig";

const CONF_CLASS: Record<string, string> = {
  reliable: "ok", developing: "warn", insufficient_history: "bad",
};

function num(v: any, d = 2) {
  return v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(d);
}

export default function RegimeLibrary({ tickers }: { tickers: string[] }) {
  const [error, setError] = useState<string | null>(null);

  // analog search
  const [ticker, setTicker] = useState("SPY");
  const [nResults, setNResults] = useState("10");
  const [excludeZeroRate, setExcludeZeroRate] = useState(false);
  const [regimeMatch, setRegimeMatch] = useState(false);
  const [aBusy, setABusy] = useState(false);
  const [analogs, setAnalogs] = useState<any>(null);

  // monitor
  const [monitor, setMonitor] = useState<any>(null);

  // events
  const [events, setEvents] = useState<any[]>([]);
  const [eventDetail, setEventDetail] = useState<any>(null);
  const [yamlText, setYamlText] = useState<string | null>(null);
  const [yamlBusy, setYamlBusy] = useState(false);
  const [yamlMsg, setYamlMsg] = useState<string | null>(null);

  useEffect(() => {
    apiGet("/api/sarah/regime-library/monitor")
      .then(setMonitor)
      .catch((e) => setMonitor({ error: e.message }));
    apiGet<{ events: any[] }>("/api/sarah/regime-library/events")
      .then((r) => setEvents(r.events))
      .catch((e) => setError(e.message));
  }, []);

  const search = async () => {
    setABusy(true); setError(null);
    try {
      const q = new URLSearchParams({
        ticker, n: nResults,
        exclude_zero_rate_era: String(excludeZeroRate),
        require_regime_match: String(regimeMatch),
      });
      setAnalogs(await apiGet(`/api/sarah/regime-library/analogs?${q}`));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setABusy(false);
    }
  };

  const loadYaml = async () => {
    setYamlMsg(null);
    try {
      const r = await apiGet<{ yaml: string }>("/api/sarah/regime-library/events-yaml");
      setYamlText(r.yaml);
    } catch (e: any) { setError(e.message); }
  };

  const saveYaml = async () => {
    if (yamlText == null) return;
    setYamlBusy(true); setYamlMsg(null);
    try {
      const r = await apiSend("/api/sarah/regime-library/events-yaml", "PUT", { yaml: yamlText });
      setYamlMsg(`saved — ${r.n_events} events (previous version kept as .bak)`);
      const ev = await apiGet<{ events: any[] }>("/api/sarah/regime-library/events");
      setEvents(ev.events);
    } catch (e: any) {
      setYamlMsg(`save failed: ${e.message}`);
    } finally {
      setYamlBusy(false);
    }
  };

  const sig = monitor?.vix_vvix_signals;

  return (
    <>
      {error && <div className="error-box">{error}</div>}

      <div className="grid cols-2">
        <div className="card">
          <h3>VVIX pre-transition monitor</h3>
          {!monitor ? (
            <p className="muted">loading…</p>
          ) : monitor.error ? (
            <div className="error-box">{monitor.error}</div>
          ) : (
            <>
              <p>
                <span className={"chip " + (CONF_CLASS[monitor.confidence] ?? "")}>
                  {monitor.confidence}
                </span>{" "}
                <span className="muted">
                  {monitor.vvix_history_days} days of VVIX history · as of {monitor.vvix_as_of}
                </span>
              </p>
              {monitor.confidence_note && (
                <p className="muted" style={{ fontSize: "var(--fs-115)" }}>{monitor.confidence_note}</p>
              )}
              <table className="data">
                <tbody>
                  <tr><td className="muted">VIX</td><td><b>{num(sig?.vix, 1)}</b></td>
                      <td className="muted">z (1y)</td><td><b>{num(sig?.vix_z1y)}</b></td></tr>
                  <tr><td className="muted">VVIX</td><td><b>{num(sig?.vvix, 1)}</b></td>
                      <td className="muted">z (1y)</td><td><b>{num(sig?.vvix_z1y)}</b></td></tr>
                  <tr><td className="muted">VVIX/VIX ratio</td><td><b>{num(sig?.vvix_vix_ratio, 1)}</b></td>
                      <td className="muted">pre-transition</td>
                      <td>{sig?.pre_transition_flag
                        ? <span className="chip bad">FLAGGED</span>
                        : <span className="chip ok">clear</span>}</td></tr>
                </tbody>
              </table>
              {(monitor.warnings ?? []).map((w: any, i: number) => (
                <div key={i} className="error-box" style={{ fontSize: "var(--fs-115)" }}>
                  <b>{w.pattern}</b> — {w.description}
                </div>
              ))}
              {monitor.macro_db_staleness?.warning && (
                <div className="error-box" style={{ fontSize: "var(--fs-115)" }}>
                  {monitor.macro_db_staleness.warning}
                </div>
              )}
              <p className="muted" style={{ fontSize: "var(--fs-11)" }}>{monitor.note}</p>
            </>
          )}
        </div>

        <div className="card">
          <h3>VVIX vs VIX history</h3>
          <PlotlyFig src="/api/sarah/regime-library/charts/vvix" />
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Analog search (Stage 5 — context, not prediction)</h3>
        <div className="grid cols-3">
          <div className="field"><div className="label">Ticker</div>
            <select value={ticker} onChange={(e) => setTicker(e.target.value)}>
              {(tickers.length ? tickers : ["SPY"]).map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select></div>
          <div className="field"><div className="label">Results</div>
            <input type="number" value={nResults}
                   onChange={(e) => setNResults(e.target.value)} /></div>
          <div className="field"><div className="label">Macro filters</div>
            <label style={{ display: "block", fontSize: "var(--fs-12)" }}>
              <input type="checkbox" checked={excludeZeroRate}
                     onChange={(e) => setExcludeZeroRate(e.target.checked)} />{" "}
              exclude zero-rate era (pre-2022)
            </label>
            <label style={{ display: "block", fontSize: "var(--fs-12)" }}>
              <input type="checkbox" checked={regimeMatch}
                     onChange={(e) => setRegimeMatch(e.target.checked)} />{" "}
              require regime compatibility
            </label></div>
        </div>
        <button className="action" disabled={aBusy} onClick={search}>
          {aBusy ? "searching…" : "Find analogs"}
        </button>

        {analogs && (
          <div style={{ marginTop: 12 }}>
            {(analogs.warnings ?? []).map((w: string, i: number) => (
              <div key={i} className="error-box" style={{ fontSize: "var(--fs-115)" }}>{w}</div>
            ))}
            <p className="muted" style={{ fontSize: "var(--fs-12)" }}>
              {analogs.ticker} as of {analogs.as_of} · {analogs.n_history} searchable days ·
              features {analogs.include_vvix ? "6+VVIX" : "6"} ·
              vix_z1y {num(analogs.current_snapshot?.vix_z1y)}
            </p>
            {analogs.analogs.length === 0 ? (
              <p className="muted">no candidate history yet — the pool fills as the daily run accumulates.</p>
            ) : (
              <table className="data">
                <thead>
                  <tr><th>Date</th><th>Similarity</th><th>ATM IV</th><th>IV rank</th>
                      <th>Front slope</th><th>25Δ RR</th><th>vix z1y</th><th>Regime</th></tr>
                </thead>
                <tbody>
                  {analogs.analogs.map((a: any) => (
                    <tr key={a.date}>
                      <td className="mono">{a.date}</td>
                      <td><b>{num(a.similarity, 3)}</b></td>
                      <td>{num(a.atm_iv_30d, 1)}</td>
                      <td>{num(a.iv_rank)}</td>
                      <td>{num(a.ts_front_slope)}</td>
                      <td>{num(a.skew_25d_rr)}</td>
                      <td>{num(a.vix_z1y)}</td>
                      <td className="muted">{a.macro_regime}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Named event library ({events.length})</h3>
        <div className="grid cols-2">
          <div>
            <table className="data">
              <thead>
                <tr><th>Event</th><th>Acute date</th><th>Spot</th><th>Vol</th><th>Days</th></tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id} style={{ cursor: "pointer" }}
                      onClick={() =>
                        apiGet(`/api/sarah/regime-library/events/${e.id}`)
                          .then(setEventDetail).catch(() => {})}>
                    <td><b>{e.name}</b></td>
                    <td className="mono">{e.acute_date}</td>
                    <td style={{ color: (e.spot_move ?? 0) < 0 ? "var(--red)" : "var(--green)" }}>
                      {num(e.spot_move, 1)}%
                    </td>
                    <td>+{num(e.vol_move, 0)} vpts</td>
                    <td>{e.duration}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button className="action secondary" style={{ marginTop: 8 }} onClick={loadYaml}>
              {yamlText == null ? "Edit library YAML" : "Reload YAML"}
            </button>
          </div>
          <div>
            {eventDetail ? (
              <>
                <h3>{eventDetail.name}</h3>
                <pre className="mono" style={{
                  background: "var(--bg)", border: "1px solid var(--border)",
                  borderRadius: 6, padding: 12, whiteSpace: "pre-wrap",
                  fontSize: "var(--fs-115)", maxHeight: 380, overflow: "auto",
                }}>{JSON.stringify(eventDetail, null, 2)}</pre>
              </>
            ) : (
              <p className="muted">click an event for the full record
                (character, what worked / failed, lessons).</p>
            )}
          </div>
        </div>

        {yamlText != null && (
          <div style={{ marginTop: 12 }}>
            <div className="label">regime_events.yaml (validated on save; .bak kept)</div>
            <textarea className="mono" value={yamlText}
                      onChange={(e) => setYamlText(e.target.value)}
                      style={{ width: "100%", minHeight: 320, background: "var(--bg)",
                               color: "var(--text)", border: "1px solid var(--border)",
                               borderRadius: 6, padding: 10, fontSize: "var(--fs-115)" }} />
            <button className="action" disabled={yamlBusy} onClick={saveYaml}>
              {yamlBusy ? "saving…" : "Save event library"}
            </button>
            {yamlMsg && <span className="muted" style={{ marginLeft: 10 }}>{yamlMsg}</span>}
          </div>
        )}
      </div>
    </>
  );
}

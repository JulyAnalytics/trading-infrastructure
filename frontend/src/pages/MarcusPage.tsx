import { useEffect, useState } from "react";
import { REGIME_COLORS, apiGet } from "../api";
import PlotlyFig from "../components/PlotlyFig";

type Summary = {
  latest: Record<string, any>;
  regime_color: string | null;
  staleness: Record<string, { as_of: string | null; age_days: number | null; stale: boolean; limit: number }>;
  attribution: any;
  regime_change_probability: { label: string; toward: string; drivers: string[] };
};

const SCORE_KEYS: [string, string][] = [
  ["Vol", "vol_score"], ["Credit", "credit_score"], ["Curve", "curve_score"],
  ["Inflation", "inflation_score"], ["Labor", "labor_score"],
  ["Positioning", "positioning_score"],
];

const CHART_TABS: [string, string][] = [
  ["VIX", "vix"], ["HY spread", "hy_spread"],
  ["Yield curve", "yield_curve_10_2"], ["Breakeven", "breakeven_10y"],
];

function ScoreBar({ name, value }: { name: string; value: number }) {
  const pct = Math.min(Math.abs(value), 1) * 50;
  const color = value >= 0 ? "var(--green)" : "var(--red)";
  const style =
    value >= 0
      ? { left: "50%", width: `${pct}%`, background: color }
      : { right: "50%", width: `${pct}%`, background: color };
  return (
    <div className="scorebar">
      <div className="name">{name}</div>
      <div className="track">
        <div className="mid" />
        <div className="fill" style={style} />
      </div>
      <div className="val">{value >= 0 ? "+" : ""}{value.toFixed(2)}</div>
    </div>
  );
}

export default function MarcusPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [returns, setReturns] = useState<any>(null);
  const [calendar, setCalendar] = useState<any>(null);
  const [cot, setCot] = useState<any>(null);
  const [transitions, setTransitions] = useState<any>(null);
  const [stateVector, setStateVector] = useState<any>(null);
  const [interpretations, setInterpretations] = useState<any>(null);
  const [implications, setImplications] = useState<any>(null);
  const [tab, setTab] = useState("vix");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<Summary>("/api/marcus/summary").then(setSummary).catch((e) => setError(e.message));
    apiGet("/api/marcus/returns").then(setReturns).catch(() => {});
    apiGet("/api/marcus/calendar").then(setCalendar).catch(() => {});
    apiGet("/api/marcus/cot").then(setCot).catch(() => {});
    apiGet("/api/marcus/transitions").then(setTransitions).catch(() => {});
    apiGet("/api/marcus/state-vector").then(setStateVector).catch(() => {});
    apiGet("/api/marcus/interpretations").then(setInterpretations).catch(() => {});
    apiGet("/api/marcus/implications").then(setImplications).catch(() => {});
  }, []);

  if (error) return <div className="error-box">Marcus summary failed: {error}</div>;
  if (!summary) return <div className="loading">loading Marcus workspace…</div>;

  const L = summary.latest;
  const div = L.divergence_type;
  const prob = summary.regime_change_probability;

  return (
    <div>
      <h2>Marcus — Macro Regime</h2>

      <div className="regime-banner" style={{ borderLeft: `6px solid ${summary.regime_color ?? "#888"}` }}>
        <span className="label" style={{ color: summary.regime_color ?? "inherit" }}>
          {L.regime}
        </span>
        <span className="score">
          score {Number(L.composite_score) >= 0 ? "+" : ""}
          {Number(L.composite_score).toFixed(2)} · confidence {L.confidence}
        </span>
        <span className="muted">as of {String(L.date).slice(0, 10)}</span>
        <span className="chip warn">Δ30d: {prob.label} → {prob.toward}</span>
      </div>

      {div && (
        <div className="notice-box">
          <b>Divergence active:</b> {div} ({L.divergence_severity})
        </div>
      )}

      <div className="grid cols-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Component scores</h3>
          {SCORE_KEYS.map(([name, key]) => (
            <ScoreBar key={key} name={name} value={Number(L[key] ?? 0)} />
          ))}
          <div style={{ marginTop: 10 }}>
            {Object.entries(summary.staleness).map(([comp, s]) => (
              <span key={comp} className={"chip " + (s.stale ? "bad" : "ok")}>
                {comp}: {s.age_days === null ? "no data" : `${s.age_days}d`}
              </span>
            ))}
          </div>
        </div>

        <div className="card">
          <h3>Attribution</h3>
          <table className="data">
            <thead>
              <tr><th>Component</th><th>Score</th><th>Weight</th><th>Contribution</th></tr>
            </thead>
            <tbody>
              {Object.entries<any>(summary.attribution.drivers).map(([name, d]) => (
                <tr key={name}>
                  <td>{name}</td><td>{d.score}</td><td>{d.weight}</td><td>{d.contribution}</td>
                </tr>
              ))}
              {Object.entries<any>(summary.attribution.contradictors).map(([name, d]) => (
                <tr key={name} style={{ opacity: 0.65 }}>
                  <td>{name} (contra)</td><td>{d.score}</td><td>{d.weight}</td><td>{d.contribution}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted" style={{ fontSize: 12 }}>
            Nearest regime: {summary.attribution.nearest_regime} (gap {summary.attribution.nearest_gap}).{" "}
            {prob.drivers.join(" · ")}
          </p>
        </div>
      </div>

      {interpretations && (
        <div className="grid cols-2" style={{ marginTop: 14 }}>
          {interpretations.interpretations.map((it: any) => (
            <div className="card" key={it.component}>
              <h3>
                {it.component} read{" "}
                <span className={"chip " + (it.aligned ? "ok" : "warn")}>
                  {it.aligned ? "confirms regime" : "contradicts regime"}
                </span>
                <span className="chip">{it.severity}</span>
              </h3>
              <p style={{ margin: "4px 0" }}>{it.headline}</p>
              <p className="muted" style={{ margin: "4px 0", fontSize: 12.5 }}>{it.regime_context}</p>
              <p style={{ margin: "4px 0", fontSize: 12.5, color: "var(--amber)" }}>
                ▸ {it.watch_condition}
              </p>
            </div>
          ))}
        </div>
      )}

      {stateVector && (
        <div className="grid cols-2" style={{ marginTop: 14 }}>
          <div className="card">
            <h3>
              State vector · {stateVector.geometry.configuration_type}{" "}
              <span className="chip">coherence {stateVector.geometry.regime_coherence_score}</span>
            </h3>
            <table className="data">
              <tbody>
                <tr>
                  <td>Financial conditions (vol+credit)</td>
                  <td>{stateVector.vector.financial_conditions_score}</td>
                </tr>
                <tr>
                  <td>Real economy (labor+curve)</td>
                  <td>{stateVector.vector.real_economy_score}</td>
                </tr>
                <tr><td>Nominal (inflation)</td><td>{stateVector.vector.nominal_score}</td></tr>
                <tr><td>Distance to CAUTION</td><td>{stateVector.vector.distance_to_stress}</td></tr>
                <tr><td>Distance to STRESS</td><td>{stateVector.vector.distance_to_crisis}</td></tr>
              </tbody>
            </table>
            <div style={{ marginTop: 8 }}>
              {stateVector.geometry.aligned_components.map((c: string) => (
                <span key={c} className="chip ok">{c}</span>
              ))}
              {stateVector.geometry.contradicting_components.map((c: string) => (
                <span key={c} className="chip warn">{c} ⤫</span>
              ))}
            </div>
          </div>

          <div className="card">
            <h3>Nearest historical analogues (ex. trailing 1y)</h3>
            {stateVector.geometry.nearest_historical_analogues.length === 0 ? (
              <p className="muted">Not enough backfilled history yet — run backfill_regime_history.</p>
            ) : (
              <table className="data">
                <thead>
                  <tr><th>Date</th><th>Regime</th><th>Score</th><th>Similarity</th></tr>
                </thead>
                <tbody>
                  {stateVector.geometry.nearest_historical_analogues.map((a: any) => (
                    <tr key={a.date}>
                      <td>{a.date}</td>
                      <td style={{ color: REGIME_COLORS[a.regime] }}>{a.regime}</td>
                      <td>{a.composite_score}</td>
                      <td>{a.similarity}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {implications?.headline_implication && (
        <div className="card" style={{ marginTop: 14 }}>
          <h3>
            Regime implications <span className="chip">{implications.sample_reliability}</span>
          </h3>
          <p>{implications.headline_implication}</p>
          {implications.caveat && <div className="notice-box">{implications.caveat}</div>}
        </div>
      )}

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Regime history</h3>
        <PlotlyFig src="/api/marcus/charts/regime-history?days=504" />
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Series</h3>
        <div className="tabs">
          {CHART_TABS.map(([label, key]) => (
            <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>
              {label}
            </button>
          ))}
        </div>
        <PlotlyFig src={`/api/marcus/charts/series/${tab}`} />
      </div>

      <div className="grid cols-3" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Regime transitions</h3>
          <table className="data">
            <tbody>
              {(transitions?.transitions ?? []).map((t: any, i: number) => (
                <tr key={i}>
                  <td>{String(t.date).slice(0, 10)}</td>
                  <td className="muted">{t.prev_regime} →</td>
                  <td style={{ color: REGIME_COLORS[t.regime] }}>{t.regime}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3>Macro calendar (45d)</h3>
          <table className="data">
            <tbody>
              {(calendar?.events ?? []).slice(0, 10).map((e: any, i: number) => (
                <tr key={i}>
                  <td>{String(e.event_date).slice(0, 10)}</td>
                  <td>{e.event_name}</td>
                  <td className="muted">{e.category}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3>COT positioning (z, 1y)</h3>
          <table className="data">
            <tbody>
              {(cot?.positioning ?? []).map((p: any, i: number) => (
                <tr key={i}>
                  <td>{p.instrument}</td>
                  <td>{p.z_score_1y == null ? "—" : Number(p.z_score_1y).toFixed(2)}</td>
                  <td className="muted">{String(p.date).slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Regime-conditional forward returns</h3>
        {returns?.note && <p className="muted">{returns.note}</p>}
        {(returns?.stats ?? []).length > 0 && (
          <table className="data">
            <thead>
              <tr><th>Regime</th><th>Asset</th><th>Horizon</th><th>Median</th><th>P25</th><th>P75</th><th>N</th></tr>
            </thead>
            <tbody>
              {returns.stats.map((r: any, i: number) => (
                <tr key={i}>
                  <td style={{ color: REGIME_COLORS[r.regime] }}>{r.regime}</td>
                  <td>{r.asset}</td><td>{r.horizon}</td>
                  <td>{(r.median_return * 100).toFixed(1)}%</td>
                  <td>{(r.p25_return * 100).toFixed(1)}%</td>
                  <td>{(r.p75_return * 100).toFixed(1)}%</td>
                  <td className={r.n_observations < 20 ? "chip bad" : ""}>{r.n_observations}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

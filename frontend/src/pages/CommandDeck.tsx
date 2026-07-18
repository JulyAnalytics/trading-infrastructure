import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { REGIME_COLORS, apiGet } from "../api";

const FRAGILITY_COLORS: Record<string, string> = {
  STABLE: "var(--green)",
  WATCH: "var(--amber)",
  FRAGILE: "var(--orange)",
  BREAKING: "var(--red)",
};

/**
 * Fragility-first hierarchy (Marcus improvements Gap 3): the 7am read is
 * "how fragile is the current regime", with the regime label as a badge.
 */
export default function CommandDeck() {
  const [regime, setRegime] = useState<any>(null);
  const [regimeErr, setRegimeErr] = useState<string | null>(null);
  const [fragility, setFragility] = useState<any>(null);
  const [vol, setVol] = useState<any>(null);
  const [verdict, setVerdict] = useState<any>(null);
  const [jobs, setJobs] = useState<any>(null);

  useEffect(() => {
    apiGet("/api/context/regime").then(setRegime).catch((e) => setRegimeErr(e.message));
    apiGet("/api/marcus/fragility").then(setFragility).catch(() => {});
    apiGet("/api/context/vol-signals").then(setVol).catch(() => {});
    apiGet("/api/context/research-verdict").then(setVerdict).catch(() => {});
    apiGet("/api/jobs?limit=5").then(setJobs).catch(() => {});
  }, []);

  const color = regime ? REGIME_COLORS[regime.regime_state] : "#888";
  const fragColor = fragility ? FRAGILITY_COLORS[fragility.fragility_level] : "#888";
  const div = fragility?.active_divergence;
  const prob = fragility?.p_transition_30d;

  return (
    <div>
      <h2>Command Deck</h2>

      {regimeErr && (
        <div className="error-box">
          regime_state.json unavailable: {regimeErr} — run the Marcus classify job.
        </div>
      )}

      {fragility && (
        <div className="regime-banner" style={{ borderLeft: `6px solid ${fragColor}` }}>
          <span className="label" style={{ color: fragColor }}>
            Fragility: {fragility.fragility_level}
          </span>
          {regime && (
            <span className="chip" style={{ color, borderColor: color, fontSize: 13 }}>
              {regime.regime_state}{" "}
              {Number(regime.composite_score) >= 0 ? "+" : ""}
              {Number(regime.composite_score).toFixed(2)} · {regime.confidence}
            </span>
          )}
          {prob && <span className="chip warn">Δ30d {prob.label} → {prob.toward}</span>}
          {fragility.composite_delta_7d !== 0 && (
            <span className="chip">
              7d {fragility.composite_delta_7d > 0 ? "+" : ""}
              {fragility.composite_delta_7d}
            </span>
          )}
          {regime && (
            <span className={"chip " + (regime.stale ? "bad" : "ok")}>
              {regime.stale
                ? `STALE — ${regime.age_hours ?? "?"}h old (limit ${regime.staleness_limit_hours}h)`
                : `fresh (${regime.age_hours}h)`}
            </span>
          )}
          {(regime?.missing_inputs ?? []).length > 0 && (
            <span className="chip bad">missing: {regime.missing_inputs.join(", ")}</span>
          )}
        </div>
      )}

      {!fragility && regime && (
        <div className="regime-banner" style={{ borderLeft: `6px solid ${color}` }}>
          <span className="label" style={{ color }}>{regime.regime_state}</span>
          <span className="score">
            {Number(regime.composite_score) >= 0 ? "+" : ""}
            {Number(regime.composite_score).toFixed(2)} · {regime.confidence}
          </span>
        </div>
      )}

      {div ? (
        <div className="notice-box">
          <b>Active divergence:</b> {div.type} ({div.severity}) — active{" "}
          {div.days_active}d since {div.onset_date}
          {div.severity_trend ? `, ${div.severity_trend.toLowerCase()}` : ""}.
        </div>
      ) : (
        fragility && <div className="ok-box">No active divergence — regime internally consistent.</div>
      )}

      <div className="grid cols-3" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Vol signals (Sarah)</h3>
          {vol ? (
            <>
              <div className="muted" style={{ fontSize: 12 }}>as of {vol.as_of}</div>
              <table className="data">
                <tbody>
                  {Object.entries<any>(vol.signals ?? {}).map(([tkr, s]) => (
                    <tr key={tkr}>
                      <td>{tkr}</td>
                      <td>IV {(s.atm_iv_30d * 100).toFixed(1)}%</td>
                      <td className="muted">{s.vrp_signal ?? s.vrp_proxy_signal ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <p className="muted">vol_signals.json not found — run the Sarah daily job.</p>
          )}
        </div>

        <div className="card">
          <h3>Latest research verdict (Priya)</h3>
          {verdict ? (
            <>
              <span className={"chip " + (verdict.verdict === "GO" ? "ok" : "bad")}>
                {verdict.verdict}
              </span>
              <span className="chip">haircut SR {verdict.production_haircut_sharpe}</span>
              <span className="chip">DSR {verdict.dsr}</span>
              <span className="chip">PBO {verdict.pbo}</span>
              <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                {verdict.hypothesis_id} · {verdict.age_hours}h old
              </div>
            </>
          ) : (
            <p className="muted">no research_verdict.json yet.</p>
          )}
        </div>

        <div className="card">
          <h3>Recent jobs</h3>
          {(jobs?.jobs ?? []).map((j: any) => (
            <div key={j.id} style={{ margin: "4px 0" }}>
              <span className={"chip " + (j.status === "succeeded" ? "ok" : j.status === "failed" ? "bad" : "warn")}>
                {j.status}
              </span>{" "}
              {j.name} <span className="muted mono">{String(j.created_at).slice(5, 16)}</span>
            </div>
          ))}
          <Link to="/jobs">→ jobs & health</Link>
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Workspaces</h3>
        <p>
          <Link to="/marcus">Marcus — macro regime</Link> ·{" "}
          <Link to="/params">Parameter registry</Link> ·{" "}
          <span className="muted">Sarah / Priya / Jordan land in Phases 3–5</span>
        </p>
      </div>
    </div>
  );
}

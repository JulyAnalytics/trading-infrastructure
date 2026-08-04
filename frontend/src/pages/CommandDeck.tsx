import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { regimeColor, apiGet } from "../api";
import RcsIntakePanel from "../components/RcsIntakePanel";

const FRAGILITY_COLORS: Record<string, string> = {
  STABLE: "var(--green)",
  WATCH: "var(--amber)",
  FRAGILE: "var(--orange)",
  BREAKING: "var(--red)",
};

export default function CommandDeck() {
  const [regime, setRegime] = useState<any>(null);
  const [regimeErr, setRegimeErr] = useState<string | null>(null);
  const [fragility, setFragility] = useState<any>(null);
  const [vol, setVol] = useState<any>(null);
  const [verdict, setVerdict] = useState<any>(null);
  const [jobs, setJobs] = useState<any>(null);
  const [book, setBook] = useState<any>(null);
  // Only for the Workspaces chip — the panel below owns its own fetching.
  const [intakes, setIntakes] = useState<any[] | null>(null);

  useEffect(() => {
    apiGet("/api/context/regime").then(setRegime).catch((e) => setRegimeErr(e.message));
    apiGet("/api/marcus/fragility").then(setFragility).catch(() => {});
    apiGet("/api/context/vol-signals").then(setVol).catch(() => {});
    apiGet("/api/context/research-verdict").then(setVerdict).catch(() => {});
    apiGet("/api/jobs?limit=5").then(setJobs).catch(() => {});
    apiGet("/api/jordan/book").then(setBook).catch(() => {});
    apiGet<{ intakes: any[] }>("/api/sarah/intake")
      .then((r) => setIntakes(r.intakes)).catch(() => {});
  }, []);

  const color = regime ? regimeColor(regime.regime_state) : "var(--muted)";
  const fragColor = fragility
    ? FRAGILITY_COLORS[fragility.fragility_level] ?? "var(--muted)"
    : "var(--muted)";
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
            <span className="chip" style={{ color, borderColor: color, fontSize: "var(--fs-13)" }}>
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

      <RcsIntakePanel compact />

      <div className="grid cols-3" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Vol signals (Sarah)</h3>
          {vol ? (
            <>
              <div className="muted" style={{ fontSize: "var(--fs-12)" }}>as of {vol.as_of}</div>
              <table className="data">
                <tbody>
                  {Object.entries<any>(vol.signals ?? {}).map(([tkr, s]) => (
                    <tr key={tkr}>
                      <td>{tkr}</td>
                      {/* atm_iv_30d is already in VOL POINTS (12.6 = 12.6%),
                          same as the vol_signals table. The ×100 that used to
                          be here rendered SPY as "1256.8%". */}
                      <td>IV {Number(s.atm_iv_30d).toFixed(1)}%</td>
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
              <div className="muted" style={{ fontSize: "var(--fs-12)", marginTop: 6 }}>
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
        <div className="workspace-rows">
          <div className="workspace-row">
            <Link to="/marcus">Marcus · Macro</Link>
            {regime ? (
              <span className="chip" style={{ color, borderColor: color }}>
                {regime.regime_state} {Number(regime.composite_score) >= 0 ? "+" : ""}
                {Number(regime.composite_score).toFixed(2)}
              </span>
            ) : (
              <span className="chip bad">no regime_state.json</span>
            )}
          </div>

          <div className="workspace-row">
            <Link to="/sarah">Sarah · Vol</Link>
            {vol?.signals ? (
              <span className="chip">{Object.keys(vol.signals).length} tickers</span>
            ) : (
              <span className="chip warn">no signals yet</span>
            )}
            {(intakes ?? []).some((r) => r.needs_user.length > 0 || !r.has_vol_data) && (
              <span className="chip warn">
                {(intakes ?? []).filter(
                  (r) => r.needs_user.length > 0 || !r.has_vol_data).length}{" "}
                RCS trade(s) waiting
              </span>
            )}
          </div>

          <div className="workspace-row">
            <Link to="/priya">Priya · Research</Link>
            {verdict ? (
              <span className={"chip " + (verdict.verdict === "GO" ? "ok" : "bad")}>
                {verdict.verdict}
              </span>
            ) : (
              <span className="chip warn">no verdict yet</span>
            )}
          </div>

          <div className="workspace-row">
            <Link to="/jordan">Jordan · Risk</Link>
            {book ? (
              <span className={"chip " + (book.counts.rcs + book.counts.manual > 0 ? "ok" : "")}>
                {book.counts.rcs + book.counts.manual} positions
              </span>
            ) : (
              <span className="chip warn">book empty</span>
            )}
          </div>

          <div className="workspace-row">
            <Link to="/params">Parameters</Link>
            <span className="muted">control surface</span>
          </div>
        </div>
      </div>
    </div>
  );
}

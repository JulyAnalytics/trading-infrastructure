import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../api";

type Job = {
  id: string; name: string; status: string;
  created_at: string | null; started_at: string | null; finished_at: string | null;
  exit_code: number | null; log_tail: string | null; error: string | null;
  param_hashes: Record<string, string> | null;
};

const STATUS_CLASS: Record<string, string> = {
  succeeded: "ok", failed: "bad", running: "warn", queued: "",
};

export default function JobsPage() {
  const [specs, setSpecs] = useState<Record<string, any> | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [health, setHealth] = useState<any>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [sched, setSched] = useState<any>(null);
  const [reviews, setReviews] = useState<any[]>([]);
  const [reviewMd, setReviewMd] = useState<string | null>(null);

  const refresh = () => {
    apiGet<{ jobs: Job[] }>("/api/jobs").then((r) => setJobs(r.jobs)).catch((e) => setError(e.message));
    apiGet("/health").then(setHealth).catch(() => setHealth(null));
    apiGet<{ alerts: any[] }>("/api/ops/alerts?limit=20").then((r) => setAlerts(r.alerts)).catch(() => {});
  };

  useEffect(() => {
    apiGet("/api/jobs/specs").then(setSpecs).catch((e) => setError(e.message));
    apiGet("/api/ops/schedule").then(setSched).catch(() => {});
    apiGet<{ reviews: any[] }>("/api/ops/weekly-reviews").then((r) => setReviews(r.reviews)).catch(() => {});
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, []);

  const ackAlert = async (id: string) => {
    try { await apiSend(`/api/ops/alerts/${id}/ack`, "POST"); refresh(); }
    catch { /* transient */ }
  };

  const openReview = async (name: string) => {
    try {
      const r = await apiGet<{ markdown: string }>(`/api/ops/weekly-reviews/${name}`);
      setReviewMd(r.markdown);
    } catch (e: any) { setError(e.message); }
  };

  const trigger = async (name: string) => {
    setError(null);
    try {
      await apiSend("/api/jobs", "POST", { name });
      refresh();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const anyRunning = jobs.some((j) => j.status === "running" || j.status === "queued");

  return (
    <div>
      <h2>Jobs & Health</h2>

      <div className="card">
        <h3>Health</h3>
        {health ? (
          <>
            <span className={"chip " + (health.registry === "ok" ? "ok" : "bad")}>registry: {health.registry}</span>
            <span className={"chip " + (health.macro_db === "ok" ? "ok" : "bad")}>macro.db: {health.macro_db}</span>
            <span className={"chip " + (health.trading_db === "ok" ? "ok" : "bad")}>trading.db: {health.trading_db}</span>
            <span className="chip">running: {health.job_running ?? "idle"}</span>
            {health.param_hashes && (
              <div className="mono muted" style={{ marginTop: 8, fontSize: "var(--fs-11)" }}>
                {Object.entries(health.param_hashes).map(([c, h]) => `${c}:${h}`).join("  ")}
              </div>
            )}
          </>
        ) : (
          <span className="chip bad">API unreachable</span>
        )}
      </div>

      <div className="grid cols-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Alerts {alerts.filter((a) => !a.acked).length > 0 &&
            <span className="chip bad">{alerts.filter((a) => !a.acked).length} unacked</span>}</h3>
          {alerts.length === 0 ? (
            <p className="muted">no alerts — failures and limit breaches land here
              (plus a macOS notification).</p>
          ) : (
            <table className="data">
              <tbody>
                {alerts.map((a) => (
                  <tr key={a.id} style={{ opacity: a.acked ? 0.45 : 1 }}>
                    <td className="muted" style={{ fontSize: "var(--fs-11)" }}>{a.created_at?.slice(0, 16)}</td>
                    <td><span className={"chip " + (a.severity === "error" ? "bad" : "warn")}>
                      {a.source}</span></td>
                    <td style={{ fontSize: "var(--fs-12)" }}>{a.message}</td>
                    <td>{!a.acked && (
                      <button className="action secondary" style={{ padding: "2px 8px" }}
                              onClick={() => ackAlert(a.id)}>ack</button>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <h3>Scheduler v2 {sched && (sched.enabled
            ? <span className="chip ok">enabled</span>
            : <span className="chip bad">disabled</span>)}</h3>
          {sched && (
            <>
              <table className="data">
                <tbody>
                  {sched.entries.map((e: any, i: number) => (
                    <tr key={i}><td style={{ fontSize: "var(--fs-12)" }}>{e.job}</td>
                      <td className="muted" style={{ fontSize: "var(--fs-12)" }}>{e.when}</td></tr>
                  ))}
                </tbody>
              </table>
              <p className="muted" style={{ fontSize: "var(--fs-115)" }}>
                retries: {sched.retries.max} × {sched.retries.wait_s}s · times are
                OpsParams (Parameters page) and apply live · catch-up on start,
                never a double-run (jobs table is the guard)
              </p>
            </>
          )}
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Weekly reviews ({reviews.length})</h3>
        {reviews.length === 0 ? (
          <p className="muted">none yet — scheduled Fridays, or run the
            weekly_review job now.</p>
        ) : (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {reviews.map((r) => (
              <button key={r.name} className="action secondary"
                      onClick={() => openReview(r.name)}>
                {r.name.replace("weekly_review_", "")}{r.pdf ? " · pdf ✓" : ""}
              </button>
            ))}
          </div>
        )}
        {reviewMd && (
          <pre className="mono" style={{
            background: "var(--bg)", border: "1px solid var(--border)",
            borderRadius: 6, padding: 12, whiteSpace: "pre-wrap",
            fontSize: "var(--fs-115)", marginTop: 10, maxHeight: 420, overflow: "auto",
          }}>{reviewMd}</pre>
        )}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Run a pipeline</h3>
        {specs &&
          Object.entries<any>(specs).map(([name, s]) => (
            <div key={name} style={{ display: "flex", gap: 10, alignItems: "center", margin: "8px 0" }}>
              <button className="action" style={{ minWidth: 260, textAlign: "left" }}
                      disabled={anyRunning} onClick={() => trigger(name)}>
                ▶ {s.label}
              </button>
              <span className="muted" style={{ fontSize: "var(--fs-12)" }}>{s.description}</span>
            </div>
          ))}
        {anyRunning && (
          <p className="muted" style={{ fontSize: "var(--fs-12)" }}>
            One job at a time — pipelines are single-writer on the databases.
          </p>
        )}
        {error && <div className="error-box">{error}</div>}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Recent runs</h3>
        <table className="data">
          <thead>
            <tr><th>Job</th><th>Status</th><th>Created</th><th>Finished</th><th>Params</th><th></th></tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id}>
                <td>{j.name} <span className="mono muted">{j.id}</span></td>
                <td><span className={"chip " + (STATUS_CLASS[j.status] ?? "")}>{j.status}</span></td>
                <td className="muted">{j.created_at?.slice(0, 19)}</td>
                <td className="muted">{j.finished_at?.slice(0, 19) ?? "—"}</td>
                <td className="mono muted" style={{ fontSize: "var(--fs-105)" }}>
                  {j.param_hashes ? Object.values(j.param_hashes).join(" ") : "—"}
                </td>
                <td>
                  {(j.log_tail || j.error) && (
                    <button className="action secondary" style={{ padding: "2px 10px" }}
                            onClick={() => setExpanded(expanded === j.id ? null : j.id)}>
                      {expanded === j.id ? "hide log" : "log"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {expanded && (
          <pre className="mono" style={{
            background: "var(--bg)", border: "1px solid var(--border)",
            borderRadius: 6, padding: 10, whiteSpace: "pre-wrap", fontSize: "var(--fs-11)",
          }}>
            {(jobs.find((j) => j.id === expanded)?.error ?? "") + "\n" +
             (jobs.find((j) => j.id === expanded)?.log_tail ?? "")}
          </pre>
        )}
      </div>
    </div>
  );
}

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

  const refresh = () => {
    apiGet<{ jobs: Job[] }>("/api/jobs").then((r) => setJobs(r.jobs)).catch((e) => setError(e.message));
    apiGet("/health").then(setHealth).catch(() => setHealth(null));
  };

  useEffect(() => {
    apiGet("/api/jobs/specs").then(setSpecs).catch((e) => setError(e.message));
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, []);

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
              <div className="mono muted" style={{ marginTop: 8, fontSize: 11 }}>
                {Object.entries(health.param_hashes).map(([c, h]) => `${c}:${h}`).join("  ")}
              </div>
            )}
          </>
        ) : (
          <span className="chip bad">API unreachable</span>
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
              <span className="muted" style={{ fontSize: 12 }}>{s.description}</span>
            </div>
          ))}
        {anyRunning && (
          <p className="muted" style={{ fontSize: 12 }}>
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
                <td className="mono muted" style={{ fontSize: 10.5 }}>
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
            borderRadius: 6, padding: 10, whiteSpace: "pre-wrap", fontSize: 11,
          }}>
            {(jobs.find((j) => j.id === expanded)?.error ?? "") + "\n" +
             (jobs.find((j) => j.id === expanded)?.log_tail ?? "")}
          </pre>
        )}
      </div>
    </div>
  );
}

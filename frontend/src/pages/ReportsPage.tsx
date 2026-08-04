import { useEffect, useState } from "react";
import { apiGet } from "../api";

type Report = {
  category: string;
  category_label: string;
  name: string;
  stem: string;
  size: number;
  modified: number;
};

type Category = { key: string; label: string };

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function ReportsPage() {
  const [reports, setReports] = useState<Report[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [selected, setSelected] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      apiGet<{ reports: Report[]; categories: Category[] }>("/api/reports")
        .then((r) => {
          setReports(r.reports);
          setCategories(r.categories);
        })
        .catch((e) => setError(e.message));
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  const visible = filter === "all" ? reports : reports.filter((r) => r.category === filter);

  const srcUrl = (r: Report) => `/api/reports/${r.category}/${encodeURIComponent(r.name)}`;

  return (
    <div>
      <h2>Reports</h2>

      {error && <div className="error-box">{error}</div>}

      <div className="grid cols-2" style={{ marginTop: 14 }}>
        {/* ── List ── */}
        <div className="card">
          <h3>
            Archive
            <span style={{ marginLeft: 8 }}>
              <select
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                style={{ fontSize: "var(--fs-12)" }}
              >
                <option value="all">all ({reports.length})</option>
                {categories.map((c) => (
                  <option key={c.key} value={c.key}>
                    {c.label} ({reports.filter((r) => r.category === c.key).length})
                  </option>
                ))}
              </select>
            </span>
          </h3>

          {visible.length === 0 ? (
            <p className="muted">no PDF reports yet — snapshots and weekly reviews appear here as they're generated.</p>
          ) : (
            <table className="data">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Modified</th>
                  <th>Size</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => (
                  <tr
                    key={`${r.category}/${r.name}`}
                    onClick={() => setSelected(r)}
                    style={{
                      cursor: "pointer",
                      background:
                        selected && selected.category === r.category && selected.name === r.name
                          ? "var(--panel-2)"
                          : undefined,
                    }}
                  >
                    <td>
                      <div>{r.stem}</div>
                      <div className="muted" style={{ fontSize: "var(--fs-11)" }}>{r.category_label}</div>
                    </td>
                    <td className="muted" style={{ fontSize: "var(--fs-115)", whiteSpace: "nowrap" }}>
                      {fmtDate(r.modified)}
                    </td>
                    <td className="muted" style={{ fontSize: "var(--fs-115)", whiteSpace: "nowrap" }}>
                      {fmtSize(r.size)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* ── Viewer ── */}
        <div className="card">
          <h3>Viewer</h3>
          {!selected ? (
            <p className="muted">select a report to view it inline.</p>
          ) : (
            <>
              <div style={{ marginBottom: 10, display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
                <div>
                  <div>{selected.stem}</div>
                  <div className="muted" style={{ fontSize: "var(--fs-115)" }}>
                    {selected.category_label} · {fmtDate(selected.modified)} · {fmtSize(selected.size)}
                  </div>
                </div>
                <a href={srcUrl(selected)} target="_blank" rel="noreferrer">
                  <button className="action secondary">Open in new tab</button>
                </a>
              </div>
              <iframe
                title={selected.name}
                src={srcUrl(selected)}
                style={{ width: "100%", height: "75vh", border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg)" }}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

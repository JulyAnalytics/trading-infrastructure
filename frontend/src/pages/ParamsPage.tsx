import { useEffect, useMemo, useState } from "react";
import { apiGet, apiSend } from "../api";

type ComponentInfo = {
  component: string;
  version: number;
  hash: string;
  payload: Record<string, any>;
  specs: Record<string, { label?: string; help?: string; bounds?: [number, number];
                          recompute?: string; guarded?: boolean }>;
};

type HistoryEntry = {
  version: number; hash: string; note: string | null;
  created_at: string; active: boolean; payload: Record<string, any>;
};

const COMPONENT_LABELS: Record<string, string> = {
  marcus: "Marcus · Macro",
  sarah: "Sarah · Vol",
  priya: "Priya · Research gates",
  jordan: "Jordan · Risk limits",
  ops: "Ops · Schedule",
  data: "Data · Calendars",
};

function FieldEditor({
  name, value, spec, draft, setDraft,
}: {
  name: string;
  value: any;
  spec: ComponentInfo["specs"][string] | undefined;
  draft: any;
  setDraft: (v: any) => void;
}) {
  const isScalar = typeof value === "number" || typeof value === "string" || typeof value === "boolean";
  const current = draft === undefined ? value : draft;
  const dirty = draft !== undefined;
  const [jsonError, setJsonError] = useState<string | null>(null);

  return (
    <div className={"field" + (dirty ? " dirty" : "")}>
      <div className="label">
        {spec?.label ?? name} <span className="muted mono">({name})</span>
        {spec?.guarded && <span className="chip warn">research gate</span>}
        {spec?.recompute && <span className="chip">edit → {spec.recompute}</span>}
        {dirty && (
          <button
            className="action secondary"
            style={{ padding: "1px 8px", marginLeft: 8, fontSize: 11 }}
            onClick={() => setDraft(undefined)}
          >
            reset
          </button>
        )}
      </div>
      {isScalar ? (
        <input
          type={typeof value === "number" ? "number" : "text"}
          step="any"
          value={String(current)}
          onChange={(e) => {
            const v = typeof value === "number" ? Number(e.target.value) : e.target.value;
            setDraft(v);
          }}
        />
      ) : (
        <textarea
          className="json"
          value={typeof current === "string" ? current : JSON.stringify(current, null, 2)}
          onChange={(e) => {
            setJsonError(null);
            try {
              setDraft(JSON.parse(e.target.value));
            } catch {
              setDraft(e.target.value); // keep raw text while invalid
              setJsonError("invalid JSON — fix before saving");
            }
          }}
        />
      )}
      {jsonError && <div className="help" style={{ color: "var(--red)" }}>{jsonError}</div>}
      {spec?.help && <div className="help">{spec.help}</div>}
      {spec?.bounds && (
        <div className="help">allowed range: [{spec.bounds[0]}, {spec.bounds[1]}]</div>
      )}
    </div>
  );
}

export default function ParamsPage() {
  const [all, setAll] = useState<Record<string, ComponentInfo> | null>(null);
  const [component, setComponent] = useState("marcus");
  const [drafts, setDrafts] = useState<Record<string, any>>({});
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryEntry[] | null>(null);
  const [preview, setPreview] = useState<any>(null);
  const [previewing, setPreviewing] = useState(false);

  const load = () =>
    apiGet<Record<string, ComponentInfo>>("/api/params").then(setAll).catch((e) => setError(e.message));

  useEffect(() => { load(); }, []);
  useEffect(() => {
    setDrafts({}); setError(null); setSaved(null); setHistory(null); setPreview(null);
  }, [component]);

  const runPreview = async () => {
    if (!dirtyPayload) return;
    setPreviewing(true); setError(null);
    try {
      setPreview(await apiSend("/api/marcus/preview", "POST", { payload: dirtyPayload }));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setPreviewing(false);
    }
  };

  const info = all?.[component];
  const dirtyPayload = useMemo(() => {
    const p: Record<string, any> = {};
    for (const [k, v] of Object.entries(drafts)) {
      if (v !== undefined) {
        if (typeof v === "string" && typeof info?.payload[k] !== "string") return null; // unparsed JSON
        p[k] = v;
      }
    }
    return p;
  }, [drafts, info]);

  const save = async () => {
    if (!dirtyPayload || Object.keys(dirtyPayload).length === 0) return;
    setSaving(true); setError(null); setSaved(null);
    try {
      const res = await apiSend<any>(`/api/params/${component}`, "PUT", {
        payload: dirtyPayload,
        note,
      });
      let msg = `saved as v${res.activated_version} (${res.hash})`;
      if (res.guarded_fields_changed?.length)
        msg += ` — GUARDED gate fields changed: ${res.guarded_fields_changed.join(", ")}`;
      if (res.recompute_suggested?.length)
        msg += ` — suggested recompute: ${res.recompute_suggested.join(", ")} (Jobs page)`;
      setSaved(msg);
      setDrafts({}); setNote("");
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const loadHistory = () =>
    apiGet<{ history: HistoryEntry[] }>(`/api/params/${component}/history`)
      .then((r) => setHistory(r.history))
      .catch((e) => setError(e.message));

  const activate = async (version: number) => {
    setError(null);
    try {
      await apiSend(`/api/params/${component}/activate/${version}`, "POST", {
        note: `GUI rollback to v${version}`,
      });
      await load();
      await loadHistory();
      setSaved(`re-activated v${version} (as a new version)`);
    } catch (e: any) {
      setError(e.message);
    }
  };

  if (!all) return <div className="loading">loading parameter registry…</div>;
  const nDirty = dirtyPayload ? Object.keys(dirtyPayload).length : 0;

  return (
    <div>
      <h2>Parameter Registry</h2>
      <div className="tabs">
        {Object.keys(all).map((c) => (
          <button key={c} className={c === component ? "active" : ""} onClick={() => setComponent(c)}>
            {COMPONENT_LABELS[c] ?? c}
          </button>
        ))}
      </div>

      {info && (
        <>
          <div className="card">
            <h3>
              {COMPONENT_LABELS[component]} — active v{info.version}{" "}
              <span className="mono muted">{info.hash}</span>
            </h3>
            <p className="muted" style={{ fontSize: 12.5 }}>
              Every save creates a new version and stamps its hash on all
              subsequent runs. Rollback re-activates an old payload as a new
              version — history is never rewritten.
            </p>
            {Object.entries(info.payload).map(([name, value]) => (
              <FieldEditor
                key={name}
                name={name}
                value={value}
                spec={info.specs[name]}
                draft={drafts[name]}
                setDraft={(v) => setDrafts((d) => ({ ...d, [name]: v }))}
              />
            ))}
          </div>

          <div className="card" style={{ marginTop: 14 }}>
            <div className="field">
              <div className="label">Change note (why)</div>
              <input value={note} onChange={(e) => setNote(e.target.value)}
                     placeholder="e.g. calibrated VC threshold against 2018–2025 backfill" />
            </div>
            <button className="action" disabled={saving || !dirtyPayload || nDirty === 0} onClick={save}>
              {saving ? "saving…" : nDirty > 0 ? `Save ${nDirty} change(s) as new version` : "No changes"}
            </button>{" "}
            {component === "marcus" && (
              <>
                <button className="action secondary" disabled={previewing || !dirtyPayload || nDirty === 0}
                        onClick={runPreview}>
                  {previewing ? "classifying…" : "Preview today under draft"}
                </button>{" "}
              </>
            )}
            <button className="action secondary" onClick={loadHistory}>
              {history ? "Refresh history" : "Show history"}
            </button>
            {preview && (
              <div className={Object.keys(preview.changed).length ? "notice-box" : "ok-box"}>
                <b>Preview:</b> active → {preview.active.regime} ({preview.active.composite_score >= 0 ? "+" : ""}
                {preview.active.composite_score}, {preview.active.confidence}) · draft →{" "}
                {preview.candidate.regime} ({preview.candidate.composite_score >= 0 ? "+" : ""}
                {preview.candidate.composite_score}, {preview.candidate.confidence}).{" "}
                {Object.keys(preview.changed).length
                  ? "Today's classification WOULD CHANGE under this draft."
                  : "Today's classification is unchanged under this draft."}
              </div>
            )}
            {dirtyPayload === null && (
              <div className="notice-box">a JSON field is invalid — fix it before saving</div>
            )}
            {error && <div className="error-box">{error}</div>}
            {saved && <div className="ok-box">{saved}</div>}
          </div>

          {history && (
            <div className="card" style={{ marginTop: 14 }}>
              <h3>Version history</h3>
              <table className="data">
                <thead>
                  <tr><th>v</th><th>hash</th><th>note</th><th>created</th><th></th></tr>
                </thead>
                <tbody>
                  {history.map((h) => (
                    <tr key={h.version}>
                      <td>{h.version}{h.active ? " ●" : ""}</td>
                      <td className="mono">{h.hash}</td>
                      <td>{h.note || <span className="muted">—</span>}</td>
                      <td className="muted">{h.created_at.slice(0, 19)}</td>
                      <td>
                        {!h.active && (
                          <button className="action secondary" style={{ padding: "2px 10px" }}
                                  onClick={() => activate(h.version)}>
                            activate
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

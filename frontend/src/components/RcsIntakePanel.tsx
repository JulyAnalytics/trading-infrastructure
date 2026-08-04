import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiSend } from "../api";

/**
 * RCS trade intake — shared by the Command Deck (the nudge) and the Sarah
 * memo tab (the workspace). The only difference is `onLoad`: when supplied,
 * each row gets a "Load" button that pulls the trade's pre-fills into the
 * memo form.
 *
 * Three things it has to do that the first cut didn't:
 *   1. Find a trade WITHOUT its ULID — nobody memorises a ULID, so the entry
 *      point is a search over RCS trades by ticker or name.
 *   2. Re-pull a trade already intaken. RCS emits no usable event when option
 *      legs are captured, so a trade first seen with no legs stays that way
 *      until something re-reads it.
 *   3. Show what actually changed on a re-pull, so a silent no-op is
 *      distinguishable from a real update.
 */

type Row = any;

function StateChips({ r }: { r: Row }) {
  if (!r.has_vol_data) return <span className="chip warn">vol pull pending</span>;
  if (r.needs_user.length === 0) return <span className="chip ok">ready to price</span>;
  return (
    <>
      {r.needs_user.map((f: string) => (
        <span key={f} className="chip bad" style={{ marginRight: 4 }}>needs {f}</span>
      ))}
    </>
  );
}

export default function RcsIntakePanel({
  title = "Trades from RCS",
  onLoad,
  activeUlid,
  onClearActive,
  compact = false,
}: {
  title?: string;
  onLoad?: (row: Row) => void;
  activeUlid?: string | null;
  onClearActive?: () => void;
  compact?: boolean;
}) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Row[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    apiGet<{ intakes: Row[] }>("/api/sarah/intake")
      .then((r) => { setRows(r.intakes); setLoadErr(null); })
      .catch((e) => setLoadErr(e.message));
  useEffect(() => { load(); }, []);

  const search = async () => {
    setError(null); setNote(null);
    try {
      const r = await apiGet<{ trades: Row[] }>(
        `/api/sarah/rcs-trades?q=${encodeURIComponent(query.trim())}`);
      setResults(r.trades);
      if (r.trades.length === 0) setNote(`no idea/active RCS trade matches "${query}".`);
    } catch (e: any) {
      setError(e.message);
    }
  };

  /** Both "analyse this" and "re-pull this" — the same idempotent call. */
  const intake = async (ulid: string, opts: { forceVol?: boolean } = {}) => {
    setBusy(ulid); setError(null); setNote(null);
    try {
      const r = await apiSend("/api/sarah/intake", "POST", {
        rcs_trade_ulid: ulid,
        ...(opts.forceVol ? { refresh_vol: true } : {}),
      });
      const changes = Object.entries<any>(r.changed ?? {});
      const what = changes.length
        ? changes.map(([f, c]) => `${f}: ${c.from ?? "—"} → ${c.to ?? "—"}`).join(", ")
        : r.repull ? "nothing changed in RCS since the last pull" : "intaken";
      setNote(
        `${r.ticker}${r.underlier_mapped ? ` (from ${r.rcs_instrument})` : ""} — ${what}.` +
        (r.vol_refresh_queued ? ` Vol pull queued as job ${r.job_id}.` : "") +
        (r.legs_captured ? "" : " No legs in RCS yet — greeks/scenarios stay empty until one is captured.") +
        (r.needs_user.length ? ` Still needed: ${r.needs_user.join(", ")}.` : ""),
      );
      await load();
      if (results) await search();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const waiting = (rows ?? []).filter((r) => r.needs_user.length > 0 || !r.has_vol_data);
  const ready = (rows ?? []).length - waiting.length;
  const ordered = [...waiting, ...(rows ?? []).filter((r) => !waiting.includes(r))];

  return (
    <div className="card" style={{ marginTop: 14 }}>
      <h3>
        {title}{" "}
        {waiting.length > 0 && <span className="chip warn">{waiting.length} waiting</span>}
        {ready > 0 && <span className="chip ok">{ready} ready</span>}
      </h3>

      {loadErr && (
        <p className="muted" style={{ fontSize: "var(--fs-12)" }}>
          intake endpoint unavailable ({loadErr}) — restart the API to pick it up.
        </p>
      )}
      {error && <div className="error-box">{error}</div>}
      {note && <p className="muted" style={{ fontSize: "var(--fs-12)" }}>{note}</p>}

      {!loadErr && rows !== null && (
        rows.length === 0 ? (
          <p className="muted" style={{ fontSize: "var(--fs-12)" }}>
            nothing tracked yet — the poll picks up option trades as you commit
            them in RCS, or find one below.
          </p>
        ) : (
          <table className="data">
            <tbody>
              {ordered.map((r) => (
                <tr key={r.rcs_trade_ulid}
                    style={r.rcs_trade_ulid === activeUlid
                      ? { outline: "1px solid var(--accent, #33b5e5)" } : undefined}>
                  <td>
                    <b>{r.ticker}</b>
                    {r.rcs_instrument && r.rcs_instrument !== r.ticker && (
                      <span className="muted"> ← {r.rcs_instrument}</span>
                    )}
                    {(r.user_overrides ?? []).length > 0 && (
                      <div className="muted" style={{ fontSize: "var(--fs-105)" }}>
                        yours: {r.user_overrides.join(", ")}
                      </div>
                    )}
                  </td>
                  <td><StateChips r={r} /></td>
                  {!compact && (
                    <td className="muted" style={{ fontSize: "var(--fs-11)" }}>
                      {r.rcs_synced_at
                        ? `synced ${String(r.rcs_synced_at).slice(5, 16)}`
                        : ""}
                    </td>
                  )}
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="action secondary" style={{ fontSize: "var(--fs-11)" }}
                            disabled={busy === r.rcs_trade_ulid}
                            title="Re-read this trade from RCS: refreshes legs, strategy and budget; never touches your expected move"
                            onClick={() => intake(r.rcs_trade_ulid)}>
                      {busy === r.rcs_trade_ulid ? "…" : "Re-pull"}
                    </button>{" "}
                    <button className="action secondary" style={{ fontSize: "var(--fs-11)" }}
                            disabled={busy === r.rcs_trade_ulid}
                            title="Re-pull and force a fresh options-chain fetch"
                            onClick={() => intake(r.rcs_trade_ulid, { forceVol: true })}>
                      + vol
                    </button>{" "}
                    {onLoad
                      ? <button className="action secondary" style={{ fontSize: "var(--fs-11)" }}
                                onClick={() => onLoad(r)}>Load</button>
                      : <Link to="/sarah">→ Sarah</Link>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      )}

      {rows !== null && rows.some((r) => r.last_error) && (
        <div className="error-box" style={{ fontSize: "var(--fs-115)" }}>
          {rows.filter((r) => r.last_error).map((r) => (
            <div key={r.rcs_trade_ulid}><b>{r.ticker}</b>: {r.last_error}</div>
          ))}
        </div>
      )}

      {/* Find a trade without knowing its ULID. */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10 }}>
        <input placeholder="find an RCS trade — ticker, name, or ULID"
               style={{ flex: 1, maxWidth: 340 }}
               value={query}
               onChange={(e) => setQuery(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") search(); }} />
        <button className="action secondary" onClick={search}>Search RCS</button>
      </div>

      {results !== null && results.length > 0 && (
        <table className="data" style={{ marginTop: 8 }}>
          <thead>
            <tr><th>Trade</th><th>Instrument</th><th>Status</th><th>Legs</th><th></th></tr>
          </thead>
          <tbody>
            {results.map((t) => (
              <tr key={t.id}>
                <td>{t.name}</td>
                <td>
                  <b>{t.instrument}</b>
                  {t.resolved_ticker !== t.instrument && (
                    <span className="muted"> → {t.resolved_ticker}</span>
                  )}
                  <span className="muted"> · {t.instrument_type}</span>
                </td>
                <td><span className="chip">{t.status}</span></td>
                <td>
                  {t.leg_count > 0
                    ? <span className="chip ok">{t.leg_count}</span>
                    : <span className="chip warn">none</span>}
                </td>
                <td>
                  {!t.analysable ? (
                    <span className="muted" style={{ fontSize: "var(--fs-11)" }}>equity — no vol pull</span>
                  ) : (
                    <button className="action secondary" style={{ fontSize: "var(--fs-11)" }}
                            disabled={busy === t.id}
                            onClick={() => intake(t.id)}>
                      {busy === t.id ? "…" : t.intaken ? "Re-pull" : "Analyse"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {activeUlid && onClearActive && (
        <p style={{ fontSize: "var(--fs-12)", marginTop: 8 }}>
          <span className="chip ok">linked</span>{" "}
          memo will be saved against RCS trade{" "}
          <b className="mono">{activeUlid}</b>{" "}
          <button className="action secondary" style={{ fontSize: "var(--fs-11)" }}
                  onClick={onClearActive}>unlink</button>
        </p>
      )}
    </div>
  );
}

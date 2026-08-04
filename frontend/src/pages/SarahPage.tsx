import { useEffect, useState } from "react";
import { apiGet } from "../api";
import VolMonitor from "./sarah/VolMonitor";
import GreeksLab from "./sarah/GreeksLab";
import MemoBuilder from "./sarah/MemoBuilder";
import RegimeLibrary from "./sarah/RegimeLibrary";
import BatchCompare from "./sarah/BatchCompare";

const TOOLS = [
  { id: "monitor", label: "Vol monitor" },
  { id: "greeks", label: "Greeks & scenarios" },
  { id: "memo", label: "Pre-trade memo" },
  { id: "library", label: "Regime library" },
  { id: "batch", label: "Batch & compare" },
] as const;

type ToolId = (typeof TOOLS)[number]["id"];

export default function SarahPage() {
  const [tool, setTool] = useState<ToolId>("monitor");
  const [signals, setSignals] = useState<any[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<{ signals: any[] }>("/api/sarah/signals")
      .then((r) => setSignals(r.signals))
      .catch((e) => setLoadError(e.message));
  }, []);

  const tickers = signals?.map((s) => s.ticker) ?? [];

  return (
    <div>
      <h2>Sarah — Vol Workspace</h2>
      <div className="tabs">
        {TOOLS.map((t) => (
          <button key={t.id} className={tool === t.id ? "active" : ""}
                  onClick={() => setTool(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tool === "monitor" && (
        <VolMonitor signals={signals} loadError={loadError} />
      )}
      {tool === "greeks" && <GreeksLab />}
      {tool === "memo" && <MemoBuilder tickers={tickers} />}
      {tool === "library" && <RegimeLibrary tickers={tickers} />}
      {tool === "batch" && <BatchCompare tickers={tickers} />}
    </div>
  );
}

import { useEffect, useState } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";
import { apiGet } from "../api";

const Plot = createPlotlyComponent(Plotly);

/** Fetches a server-built Plotly figure ({data, layout}) and renders it. */
export default function PlotlyFig({ src }: { src: string }) {
  const [fig, setFig] = useState<{ data: any[]; layout: any } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setFig(null);
    setError(null);
    apiGet(src)
      .then((f) => alive && setFig(f))
      .catch((e) => alive && setError(String(e.message ?? e)));
    return () => {
      alive = false;
    };
  }, [src]);

  if (error) return <div className="error-box">chart failed: {error}</div>;
  if (!fig) return <div className="loading">loading chart…</div>;
  return (
    <Plot
      data={fig.data}
      layout={{ ...fig.layout, autosize: true }}
      useResizeHandler
      style={{ width: "100%" }}
      config={{ displaylogo: false, responsive: true }}
    />
  );
}

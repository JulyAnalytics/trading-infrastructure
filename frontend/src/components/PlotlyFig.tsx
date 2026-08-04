import { useEffect, useMemo, useState } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";
import { apiGet } from "../api";
import { usePlotTheme, useTheme } from "../theme";

const Plot = createPlotlyComponent(Plotly);

/** Fetches a server-built Plotly figure ({data, layout}) and renders it. */
export default function PlotlyFig({ src }: { src: string }) {
  const [fig, setFig] = useState<{ data: any[]; layout: any } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [theme] = useTheme();
  const plotTheme = usePlotTheme();

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

  // Server figures are built with the dark palette baked in; overlay the
  // active theme's colors (bg, font, axes) so charts follow the theme.
  // Axis entries are merged shallowly so server titles/settings survive.
  const layout = useMemo(() => {
    const l = { ...(fig?.layout ?? {}) };
    if (theme === "light") delete l.template; // plotly_dark clashes on light
    return {
      ...l,
      autosize: true,
      paper_bgcolor: plotTheme.layout.paper_bgcolor,
      plot_bgcolor: plotTheme.layout.plot_bgcolor,
      font: { ...(l.font ?? {}), color: plotTheme.layout.font.color,
              family: plotTheme.layout.font.family },
      xaxis: { ...(l.xaxis ?? {}), ...plotTheme.layout.xaxis },
      yaxis: { ...(l.yaxis ?? {}), ...plotTheme.layout.yaxis },
    };
  }, [fig, theme, plotTheme]);

  if (error) return <div className="error-box">chart failed: {error}</div>;
  if (!fig) return <div className="loading">loading chart…</div>;
  return (
    <Plot
      data={fig.data}
      layout={layout}
      useResizeHandler
      style={{ width: "100%" }}
      config={{ displaylogo: false, responsive: true }}
    />
  );
}

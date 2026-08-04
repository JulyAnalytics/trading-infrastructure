// Theme system. Each theme is a :root[data-theme="<id>"] block of CSS
// custom properties in theme.css; the data-theme attribute on <html> is
// the single source of truth. This module toggles that attribute and
// exposes helpers for TS-side consumers — Plotly figures need concrete
// hex values, so cssVar() reads them back from computed styles.
//
// Theme state lives in a module-level store (not per-component state) so
// every consumer re-renders when the theme changes.

import { useMemo, useSyncExternalStore } from "react";

export const THEMES = [
  { id: "dark", label: "Dark" },
  { id: "light", label: "Light" },
  { id: "terminal", label: "Terminal" },
  { id: "spring", label: "Spring" },
  { id: "spring-shade", label: "Spring Shade" },
] as const;

export type ThemeId = (typeof THEMES)[number]["id"];

const STORAGE_KEY = "ui-theme";
export const DEFAULT_THEME: ThemeId = "dark";

// --- store ---

let current: ThemeId = DEFAULT_THEME;
const listeners = new Set<() => void>();

function emit(): void {
  for (const l of listeners) l();
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

function getSnapshot(): ThemeId {
  return current;
}

/** Apply the persisted theme before first render (call once in main.tsx). */
export function initTheme(): void {
  const saved = localStorage.getItem(STORAGE_KEY);
  current = THEMES.some((t) => t.id === saved) ? (saved as ThemeId) : DEFAULT_THEME;
  document.documentElement.dataset.theme = current;
}

export function setTheme(id: ThemeId): void {
  current = id;
  document.documentElement.dataset.theme = id; // update CSS before re-render
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    /* storage unavailable (private mode) — theme still applies for the session */
  }
  emit();
}

/** Current theme id + setter; every consumer re-renders on change. */
export function useTheme(): [ThemeId, (id: ThemeId) => void] {
  const id = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  return [id, setTheme];
}

/** Resolve a CSS custom property to its computed value (e.g. for Plotly). */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * Plotly layout colors for the active theme. Inline styles can use
 * var(--x) directly, but Plotly figure JSON cannot — so charts read
 * concrete values from the computed styles of the active theme.
 */
export function usePlotTheme() {
  const [id] = useTheme();
  return useMemo(() => {
    const panel = cssVar("--panel");
    return {
      layout: {
        autosize: true,
        paper_bgcolor: panel,
        plot_bgcolor: panel,
        font: { color: cssVar("--text"), family: cssVar("--font-sans") },
        margin: { l: 40, r: 20, t: 30, b: 30 },
        xaxis: {
          gridcolor: cssVar("--border"),
          zerolinecolor: cssVar("--border"),
          tickfont: { color: cssVar("--muted") },
        },
        yaxis: {
          gridcolor: cssVar("--border"),
          zerolinecolor: cssVar("--border"),
          tickfont: { color: cssVar("--muted") },
        },
      },
      accent: cssVar("--accent"),
    };
  }, [id]);
}

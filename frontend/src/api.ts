// Thin fetch wrapper. In dev, Vite proxies /api and /health to :8100.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body);
    } catch { /* keep statusText */ }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export function apiGet<T = any>(path: string): Promise<T> {
  return fetch(path).then((r) => handle<T>(r));
}

export function apiSend<T = any>(
  path: string,
  method: "POST" | "PUT" | "DELETE",
  body?: unknown,
): Promise<T> {
  return fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then((r) => handle<T>(r));
}

export const REGIME_COLORS: Record<string, string> = {
  RISK_ON_LOW_VOL: "#00C851",
  RISK_ON_ELEVATED_VOL: "#ffbb33",
  NEUTRAL: "#33b5e5",
  CAUTION: "#FF8800",
  RISK_OFF_STRESS: "#ff4444",
  CRISIS: "#CC0000",
};

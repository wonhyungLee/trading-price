export type Candle = {
  ts: number; // unix seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  is_partial?: boolean;
};

export type Scenario = {
  tf_sec: number;
  path: { ts: number; value: number }[];
  levels: { entry: number; stop: number; tp1: number; tp2?: number };
};

export type RecommendResponse = {
  ok: boolean;
  error?: string;
  regime?: {
    bias: string;
    confidence: number;
    last_close?: number;
    sma200?: number;
    ts?: number;
  };
  selected?: any;
  best_params?: any;
  plan?: any;
  candidates?: any[];
};

const API_BASE = (import.meta as any).env?.VITE_API_BASE ?? '';

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export async function fetchLatest(): Promise<any> {
  return getJson('/api/latest');
}

export async function fetchRecommend(side: 'long' | 'short', riskPct?: number): Promise<RecommendResponse> {
  const q = new URLSearchParams({ side });
  if (riskPct !== undefined && Number.isFinite(riskPct)) q.set('risk_pct', String(riskPct));
  return getJson(`/api/recommend?${q.toString()}`);
}

export async function notifyRecommend(
  side: 'long' | 'short',
  riskPct?: number,
): Promise<{ ok: boolean; detail?: string; recommend?: RecommendResponse }> {
  const q = new URLSearchParams({ side });
  if (riskPct !== undefined && Number.isFinite(riskPct)) q.set('risk_pct', String(riskPct));
  const res = await fetch(`${API_BASE}/api/notify/recommend?${q.toString()}`, { method: 'POST' });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return (await res.json()) as { ok: boolean; detail?: string; recommend?: RecommendResponse };
}

export async function fetchCandles(tf: string, limit = 200): Promise<{ ok: boolean; timeframe: string; candles: Candle[] }> {
  const q = new URLSearchParams({ tf, limit: String(limit) });
  const res = await getJson<any>(`/api/candles?${q.toString()}`);
  return {
    ok: res.ok,
    timeframe: res.timeframe,
    candles: res.data || [],
  };
}

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  fetchCandles,
  fetchLatest,
  fetchRecommend,
  notifyRecommend,
  type Candle,
  type Scenario,
} from './api';
import PriceChart from './components/PriceChart';
import GlossaryModal from './components/GlossaryModal';

type Side = 'long' | 'short';
type CoupangPromoItem = {
  id: string;
  link: string;
  image: string;
  title: string;
};

const BANNER_COOLDOWN_MS = 6 * 60 * 60 * 1000;
const BANNER_COOLDOWN_KEY = 'cpb_cooldown_until';

const COUPANG_PROMO_ITEMS: CoupangPromoItem[] = [
  { id: 'dPJvzF', link: 'https://link.coupang.com/a/dPJvzF', image: '/coupang-ads-2026/dPJvzF_600.gif', title: '쿠팡 추천 링크 1' },
  { id: 'dPJzZu', link: 'https://link.coupang.com/a/dPJzZu', image: '/coupang-ads-2026/dPJzZu_600.gif', title: '쿠팡 추천 링크 2' },
  { id: 'dPJC4g', link: 'https://link.coupang.com/a/dPJC4g', image: '/coupang-ads-2026/dPJC4g_600.gif', title: '쿠팡 추천 링크 3' },
  { id: 'dPJQFz', link: 'https://link.coupang.com/a/dPJQFz', image: '/coupang-ads-2026/dPJQFz_600.gif', title: '쿠팡 추천 링크 4' },
  { id: 'dPJVxr', link: 'https://link.coupang.com/a/dPJVxr', image: '/coupang-ads-2026/dPJVxr_600.gif', title: '쿠팡 추천 링크 5' },
  { id: 'dPJ2jt', link: 'https://link.coupang.com/a/dPJ2jt', image: '/coupang-ads-2026/dPJ2jt_600.gif', title: '쿠팡 추천 링크 6' },
  { id: 'dPKcZs', link: 'https://link.coupang.com/a/dPKcZs', image: '/coupang-ads-2026/dPKcZs_600.gif', title: '쿠팡 추천 링크 7' },
  { id: 'dPKgU0', link: 'https://link.coupang.com/a/dPKgU0', image: '/coupang-ads-2026/dPKgU0_600.gif', title: '쿠팡 추천 링크 8' },
  { id: 'dPKjlp', link: 'https://link.coupang.com/a/dPKjlp', image: '/coupang-ads-2026/dPKjlp_600.gif', title: '쿠팡 추천 링크 9' },
  { id: 'dPKIZ9', link: 'https://link.coupang.com/a/dPKIZ9', image: '/coupang-ads-2026/dPKIZ9_600.gif', title: '쿠팡 추천 링크 10' },
  { id: 'dPKoN6', link: 'https://link.coupang.com/a/dPKoN6', image: '/coupang-ads-2026/dPKoN6_600.gif', title: '쿠팡 추천 링크 11' },
  { id: 'dPKr4O', link: 'https://link.coupang.com/a/dPKr4O', image: '/coupang-ads-2026/dPKr4O_600.gif', title: '쿠팡 추천 링크 12' },
  { id: 'dPKvE3', link: 'https://link.coupang.com/a/dPKvE3', image: '/coupang-ads-2026/dPKvE3_600.gif', title: '쿠팡 추천 링크 13' },
  { id: 'dPKzjf', link: 'https://link.coupang.com/a/dPKzjf', image: '/coupang-ads-2026/dPKzjf_600.gif', title: '쿠팡 추천 링크 14' },
  { id: 'dPKFV8', link: 'https://link.coupang.com/a/dPKFV8', image: '/coupang-ads-2026/dPKFV8_600.gif', title: '쿠팡 추천 링크 15' },
  { id: 'dPKI7T', link: 'https://link.coupang.com/a/dPKI7T', image: '/coupang-ads-2026/dPKI7T_600.gif', title: '쿠팡 추천 링크 16' },
];

const TF_SECONDS: Record<string, number> = {
  '30m': 30 * 60,
  '60m': 60 * 60,
  '180m': 180 * 60,
};

function readBannerCooldown(): number {
  try {
    const raw = localStorage.getItem(BANNER_COOLDOWN_KEY);
    const parsed = raw ? Number(raw) : 0;
    return Number.isFinite(parsed) ? parsed : 0;
  } catch {
    return 0;
  }
}

function normalizeCandles(candles: Candle[], timeframe: string): Candle[] {
  const tfSec = TF_SECONDS[timeframe];
  if (!Array.isArray(candles) || candles.length === 0) {
    return [];
  }

  const rows = candles
    .map((c) => ({
      ts: Number(c.ts),
      open: Number(c.open),
      high: Number(c.high),
      low: Number(c.low),
      close: Number(c.close),
      volume: c.volume == null ? 0 : Number(c.volume),
      is_partial: c.is_partial,
    }))
    .filter((c) =>
      Number.isFinite(c.ts) &&
      Number.isFinite(c.open) &&
      Number.isFinite(c.high) &&
      Number.isFinite(c.low) &&
      Number.isFinite(c.close),
    )
    .sort((a, b) => a.ts - b.ts);

  if (rows.length === 0) return [];

  const deduped: Candle[] = [];
  for (const c of rows) {
    const last = deduped[deduped.length - 1];
    if (!last || last.ts !== c.ts) {
      deduped.push({
        ts: c.ts,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
        volume: Number.isFinite(c.volume) ? c.volume : 0,
        is_partial: c.is_partial,
      });
      continue;
    }
    last.close = c.close;
    last.high = Math.max(last.high, c.high);
    last.low = Math.min(last.low, c.low);
    last.volume = Number.isFinite(c.volume) ? (Number(last.volume ?? 0) + c.volume) : Number(last.volume ?? 0);
    last.is_partial = c.is_partial ?? last.is_partial;
  }

  if (!tfSec) {
    return deduped;
  }

  const deltas = [];
  for (let i = 1; i < deduped.length; i++) {
    const d = deduped[i].ts - deduped[i - 1].ts;
    if (d > 0 && d < 24 * 60 * 60) {
      deltas.push(d);
    }
  }
  if (deltas.length === 0) {
    return deduped;
  }
  deltas.sort((a, b) => a - b);
  const median = deltas[Math.floor(deltas.length / 2)];

  // If most bars are much shorter than timeframe (예: 1m 데이터가 30m으로 섞인 경우),
  // 해당 프레임 기준으로 봉을 재집계해서 그리기 안정성을 확보한다.
  if (median >= tfSec * 0.9 && median <= tfSec * 1.1) {
    return deduped;
  }

  const normalized: Candle[] = [];
  let bucket: Candle | null = null;
  for (const c of deduped) {
    const bucketTs = c.ts - (c.ts % tfSec);
    if (!bucket || bucket.ts !== bucketTs) {
      if (bucket) normalized.push(bucket);
      bucket = {
        ts: bucketTs,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
        volume: Number.isFinite(c.volume) ? c.volume : 0,
        is_partial: c.is_partial,
      };
      continue;
    }
    bucket.high = Math.max(bucket.high, c.high);
    bucket.low = Math.min(bucket.low, c.low);
    bucket.close = c.close;
    const bucketVolume = typeof bucket.volume === 'number' ? bucket.volume : 0;
    const addVolume = typeof c.volume === 'number' ? c.volume : 0;
    bucket.volume = bucketVolume + addVolume;
    bucket.is_partial = bucket.is_partial || c.is_partial;
  }
  if (bucket) normalized.push(bucket);

  return normalized;
}

const READY_RULE_INFO: Record<
  string,
  { title: string; desc: string; recommendedTp: 'TP1' | 'TP2' | '-'; noStop: boolean }
> = {
  A: {
    title: '규칙 A',
    desc: 'SMA5 이탈폭이 0.3% 이내면 발동합니다. ATR 제한은 없습니다. 단기 되돌림 구간에서도 기회를 놓치지 않도록 완만한 진입 구간입니다.',
    recommendedTp: 'TP2',
    noStop: true,
  },
  B: {
    title: '규칙 B',
    desc: 'SMA5 이탈폭이 0.3% 이내 + ATR% 1.5% 이하에서 발동합니다. 변동성이 과도하지 않은 상태에서 진입 타이밍의 정합성이 높은 구간입니다.',
    recommendedTp: 'TP2',
    noStop: true,
  },
  C: {
    title: '규칙 C',
    desc: 'SMA5 이탈폭이 0.2% 이내 + ATR% 1.5% 이하에서 발동합니다. 가장 빠르게 회복될 가능성이 높은 보수형 구간입니다.',
    recommendedTp: 'TP1',
    noStop: true,
  },
  D: {
    title: '규칙 D',
    desc: 'ABCD 조건에 해당하지 않을 때의 기본 구간입니다. ATR%가 1.5% 이내일 때만 일반 Stop 규칙을 유지합니다.',
    recommendedTp: 'TP1',
    noStop: false,
  },
};

function fmt(x: any): string {
  const n = Number(x);
  if (!Number.isFinite(n)) return '-';
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function fmtPct(x: any, digits = 2): string {
  const n = Number(x);
  if (!Number.isFinite(n)) return '-';
  return `${n.toFixed(digits)}%`;
}

function fmtTs(ts: number | undefined): string {
  if (!ts) return '-';
  return new Date(ts * 1000).toLocaleString();
}

function fmtCountdown(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const mm = Math.floor(s / 60);
  const ss = s % 60;
  return `${mm}:${String(ss).padStart(2, '0')}`;
}

function clampInt(x: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, Math.round(x)));
}

function formatDiscordDetail(detail?: string): string {
  if (!detail) return '전송 실패';
  if (detail === 'discord_webhook_missing') {
    return '디스코드 웹훅이 설정되지 않았습니다. (WONYODD_DISCORD_WEBHOOK_URL 또는 WONYODD_DISCORD_WEBHOOK_FILE)';
  }
  if (detail.startsWith('http_')) return `디스코드 요청 실패 (${detail})`;
  if (detail.startsWith('error:')) return '디스코드 전송 중 오류';
  return detail;
}

export default function App() {
  const chartWindowBars = 80;
  const [side, setSide] = useState<Side>('long');
  const [riskPct, setRiskPct] = useState<number>(0.5);

  const [latest, setLatest] = useState<any>(null);
  const [rec, setRec] = useState<any>(null);

  const [candles, setCandles] = useState<Candle[]>([]);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [chartTf, setChartTf] = useState<string>('30m');

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notifyMsg, setNotifyMsg] = useState<string | null>(null);

  const [serverOffsetMs, setServerOffsetMs] = useState<number>(0);
  const [nextUpdateAtMs, setNextUpdateAtMs] = useState<number | null>(null);
  const [countdownSec, setCountdownSec] = useState<number>(0);
  const [lastUpdateAgeSec, setLastUpdateAgeSec] = useState<number | null>(null);

  const [glossaryOpen, setGlossaryOpen] = useState(false);
  const [glossaryQuery, setGlossaryQuery] = useState<string>('');

  const [bannerOpen, setBannerOpen] = useState(false);
  const [bannerCooldownUntil, setBannerCooldownUntil] = useState<number>(() => readBannerCooldown());
  const [promoSeed, setPromoSeed] = useState<number>(() =>
    Math.floor(Math.random() * Math.max(1, COUPANG_PROMO_ITEMS.length)),
  );

  const [fontBasePx, setFontBasePx] = useState<number>(() => {
    try {
      const v = localStorage.getItem('wonyodd_font_base_px');
      const n = v ? Number(v) : 16;
      return clampInt(Number.isFinite(n) ? n : 16, 14, 20);
    } catch {
      return 16;
    }
  });

  const hasPlan = Boolean(rec?.plan?.entry_price);
  const selectedTf = rec?.plan?.tf ?? chartTf;

  const lastCandle = candles.length > 0 ? candles[candles.length - 1] : null;
  const prevCandle = candles.length > 1 ? candles[candles.length - 2] : null;
  const lastPrice = lastCandle?.close;
  const priceDelta = (prevCandle && lastCandle) ? (lastCandle.close - prevCandle.close) : null;
  const priceDeltaPct = (prevCandle && lastCandle && prevCandle.close) ? (priceDelta! / prevCandle.close) * 100.0 : null;

  const regime = rec?.regime;
  const plan = rec?.plan;
  const selected = rec?.selected;
  const notes: string[] = Array.isArray(rec?.notes) ? rec.notes : [];
  const candidates = useMemo(() => (Array.isArray(rec?.candidates) ? rec.candidates : []), [rec]);
  const selectedRule = String(selected?.ready_rule || plan?.ready_rule || '-').toUpperCase();
  const selectedRuleMeta = READY_RULE_INFO[selectedRule];
  const selectedRuleMdd = selected?.ready_rule_mdd_pct ?? plan?.ready_rule_mdd_pct;
  const selectedRecommendedTp = selectedRuleMeta?.recommendedTp ?? '-';
  const isNoStopRule = Boolean(selectedRuleMeta?.noStop && selected?.status === 'ready');
  const popupPromoItems = useMemo(() => {
    if (COUPANG_PROMO_ITEMS.length === 0) return [];
    const size = Math.min(6, COUPANG_PROMO_ITEMS.length);
    return Array.from({ length: size }, (_, idx) => {
      const offset = (promoSeed + idx) % COUPANG_PROMO_ITEMS.length;
      return COUPANG_PROMO_ITEMS[offset];
    });
  }, [promoSeed]);
  const bannerOpenRef = useRef(bannerOpen);

  useEffect(() => {
    bannerOpenRef.current = bannerOpen;
  }, [bannerOpen]);

  function renderTpValue(value: any, isRecommended: boolean) {
    const text = fmt(value);
    if (!text || text === '-') {
      return text;
    }
    return isRecommended ? `${text} (추천)` : text;
  }

  function formatRuleMdd(value: any): string {
    const n = Number(value);
    if (!Number.isFinite(n)) return '-';
    return `${n.toFixed(2)}%`;
  }

  function openGlossary(term?: string) {
    setGlossaryQuery(term ?? '');
    setGlossaryOpen(true);
  }

  function startBannerCooldown() {
    const until = Date.now() + BANNER_COOLDOWN_MS;
    setBannerCooldownUntil(until);
    try {
      localStorage.setItem(BANNER_COOLDOWN_KEY, String(until));
    } catch {
      // ignore
    }
    setBannerOpen(false);
  }

  function openBannerIfAllowed() {
    if (Date.now() < bannerCooldownUntil) return;
    if (COUPANG_PROMO_ITEMS.length > 0) setPromoSeed((prev) => (prev + 3) % COUPANG_PROMO_ITEMS.length);
    setBannerOpen(true);
  }

  useEffect(() => {
    if (bannerOpen) return;

    const handler = (event: MouseEvent) => {
      if (bannerOpenRef.current) return;
      if (Date.now() < bannerCooldownUntil) return;

      const target = event.target as HTMLElement | null;
      if (!target) return;
      if (target.closest('.cpbOverlay')) return;

      const clickable = target.closest('button, [role="button"], a');
      if (!clickable) return;
      if ((clickable as HTMLElement).closest('[data-cp-ignore]')) return;

      window.setTimeout(() => openBannerIfAllowed(), 0);
    };

    document.addEventListener('click', handler, true);
    return () => document.removeEventListener('click', handler, true);
  }, [bannerOpen, bannerCooldownUntil]);

  function Term({ label, term }: { label: string; term: string }) {
    return (
      <span className="termLabel">
        <span>{label}</span>
        <button className="helpBtn" onClick={() => openGlossary(term)} aria-label={`${term} 설명`}>
          ?
        </button>
      </span>
    );
  }

  async function refreshLatestUI(): Promise<any | null> {
    try {
      const data = await fetchLatest();
      setLatest(data);

      const latest1mTs = Number(data?.latest?.['1m']?.ts);
      if (Number.isFinite(latest1mTs) && latest1mTs > 0) {
        // TradingView time is bar open-time. Alert arrives on bar close.
        // Next alert is expected at next bar close => latest_open + 120s.
        setNextUpdateAtMs((latest1mTs + 120) * 1000);
      } else {
        setNextUpdateAtMs(null);
      }
      return data;
    } catch {
      return null;
    }
  }

  async function runRecommend(nextSide: Side) {
    setBusy(true);
    setErr(null);
    setNotifyMsg(null);
    try {
      const data = await fetchRecommend(nextSide, riskPct);
      if (!data.ok) {
        setRec(data);
        setScenario(null);
        setErr(data.error ?? 'unknown error');
        return;
      }

      setRec(data);
      const tf = data.plan?.tf;
      setScenario(data.plan?.scenario ?? null);
      if (tf) setChartTf(tf);
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
      // Refresh latest after heavy compute so UI shows up-to-date timestamps.
      refreshLatestUI();
    }
  }

  async function selectTimeframe(tf: string) {
    if (!tf) return;
    setBusy(true);
    setErr(null);
    setNotifyMsg(null);
    try {
      const data = await fetchRecommend(side, riskPct, tf);
      if (!data.ok) {
        setRec(data);
        setScenario(null);
        setErr(data.error ?? 'unknown error');
        return;
      }
      setRec(data);
      setScenario(data.plan?.scenario ?? null);
      if (data.plan?.tf) setChartTf(data.plan.tf);
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
      refreshLatestUI();
    }
  }

  async function sendDiscord() {
    setNotifyMsg(null);
    try {
      const res = await notifyRecommend(side, riskPct, rec?.plan?.tf);
      if (!res.ok) {
        setNotifyMsg(formatDiscordDetail(res.detail));
        return;
      }
      if (res.recommend?.ok) setRec(res.recommend);
      setNotifyMsg('디스코드 전송 완료');
    } catch (e: any) {
      setNotifyMsg(e?.message ?? String(e));
    }
  }

  // Apply base font size (A-/A+)
  useEffect(() => {
    document.documentElement.style.setProperty('--font-base', `${fontBasePx}px`);
    try {
      localStorage.setItem('wonyodd_font_base_px', String(fontBasePx));
    } catch {
      // ignore
    }
  }, [fontBasePx]);

  useEffect(() => {
    if (!bannerOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [bannerOpen]);

  // Initial load
  useEffect(() => {
    refreshLatestUI();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Server clock sync
  useEffect(() => {
    let cancelled = false;
    const syncServerTime = async () => {
      try {
        const apiBase = (import.meta as any).env?.VITE_API_BASE ?? '';
        const res = await fetch(`${apiBase}/api/health`);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled && data?.ts) {
          const offset = Number(data.ts) * 1000 - Date.now();
          setServerOffsetMs(offset);
        }
      } catch {
        // ignore
      }
    };
    syncServerTime();
    const id = setInterval(syncServerTime, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // Countdown + lag indicator
  useEffect(() => {
    const tick = () => {
      const nowMs = Date.now() + serverOffsetMs;
      const fallbackNext = Math.floor(nowMs / 60000) * 60000 + 60000;
      const nextMs = nextUpdateAtMs ?? fallbackNext;
      setCountdownSec(Math.max(0, Math.ceil((nextMs - nowMs) / 1000)));

      const latest1mTs = Number(latest?.latest?.['1m']?.ts);
      if (Number.isFinite(latest1mTs) && latest1mTs > 0) {
        const lastCloseMs = (latest1mTs + 60) * 1000;
        setLastUpdateAgeSec(Math.max(0, Math.round((nowMs - lastCloseMs) / 1000)));
      } else {
        setLastUpdateAgeSec(null);
      }
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [latest, nextUpdateAtMs, serverOffsetMs]);

  // Auto-refresh chart data near 1m boundaries
  useEffect(() => {
    if (!chartTf) return;
    let cancelled = false;
    let timer: number | undefined;

    const tick = async () => {
      const data = await refreshLatestUI();

      try {
        const c = await fetchCandles(chartTf, 5000);
        if (!cancelled) setCandles(normalizeCandles(c.candles ?? [], chartTf));
      } catch {
        // ignore
      }

      if (cancelled) return;

      const nowMs = Date.now() + serverOffsetMs;
      const fallbackNext = Math.floor(nowMs / 60000) * 60000 + 60000;

      const latest1mTs = Number(data?.latest?.['1m']?.ts);
      const nextMs =
        (Number.isFinite(latest1mTs) && latest1mTs > 0) ? (latest1mTs + 120) * 1000 : fallbackNext;

      const delayMs = Math.max(2000, nextMs - nowMs + 700);
      timer = window.setTimeout(tick, delayMs);
    };

    tick();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [chartTf, serverOffsetMs]);

  const updateBadge = (() => {
    if (lastUpdateAgeSec === null) return { label: 'NO DATA', cls: 'badge' };
    if (lastUpdateAgeSec <= 15) return { label: 'LIVE', cls: 'badge badgeLive' };
    if (lastUpdateAgeSec <= 90) return { label: 'DELAY', cls: 'badge badgeWarn' };
    return { label: 'STALE', cls: 'badge badgeDanger' };
  })();

  return (
    <>
      {bannerOpen ? (
        <div className="cpbOverlay" role="dialog" aria-modal="true" aria-label="쿠팡 프로모션 (광고)">
          <div className="cpbModal" onClick={(e) => e.stopPropagation()}>
            <button
              className="cpbClose"
              onClick={(e) => {
                e.stopPropagation();
                startBannerCooldown();
              }}
              aria-label="닫기"
            >
              ×
            </button>
            <div className="cpbHeader">
              <div className="cpbTitle">쿠팡 프로모션</div>
              <p className="cpbSubtitle">쿠팡광고2026 gif + 링크 기반 추천 상품입니다.</p>
            </div>
            <div className="cpbGrid">
              {popupPromoItems.map((item, idx) => (
                <a
                  key={`${item.id}-${item.link}`}
                  className={`cpbCard ${idx === 0 ? 'cpbCardPrimary' : ''}`}
                  href={item.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => startBannerCooldown()}
                >
                  <img className="cpbThumb" src={item.image} alt={item.title} loading="lazy" />
                  <div className="cpbCopy">
                    <span className="cpbBadge">{idx === 0 ? 'BEST' : `AD ${idx + 1}`}</span>
                    <div className="cpbCardTitle">{item.title}</div>
                    <span className="cpbCta">바로 보기</span>
                  </div>
                </a>
              ))}
            </div>
            <p className="cpbDisclosure">
              이 포스팅은 쿠팡파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받을 수 있습니다.
            </p>
          </div>
        </div>
      ) : null}
      <header className="topBar">
        <div className="wrap topBarInner">
          <div className="brand">
            <div className="brandTitle">Wonyodd Reco</div>
            <div className="muted brandSub">
              1D 레짐 + 30m/60m/180m 후보 중 “지금 진입이 쉬운 TF”를 고르고 Entry/Stop/TP를 제안합니다.
            </div>
          </div>

          <div className="topControls">
            <div className="segmented controlSide">
              <button
                className={`segBtn ${side === 'long' ? 'segBtnActiveLong' : ''}`}
                onClick={() => {
                  setSide('long');
                  openBannerIfAllowed();
                  runRecommend('long');
                }}
                disabled={busy}
              >
                LONG
              </button>
              <button
                className={`segBtn ${side === 'short' ? 'segBtnActiveShort' : ''}`}
                onClick={() => {
                  setSide('short');
                  openBannerIfAllowed();
                  runRecommend('short');
                }}
                disabled={busy}
              >
                SHORT
              </button>
            </div>

            <div className="inputGroup controlRisk">
              <div className="muted inputLabel">리스크(%)</div>
              <input
                className="numInput"
                type="number"
                step={0.05}
                min={0.05}
                max={2}
                value={riskPct}
                onChange={(e) => setRiskPct(Number(e.target.value))}
                disabled={busy}
              />
            </div>

            <button className="btn btnPrimary controlRecommend" onClick={() => runRecommend(side)} disabled={busy}>
              {busy ? '계산 중...' : '추천 계산'}
            </button>

            <a
              className="btn controlDiscord"
              href="https://discord.gg/cAPcXQh7K"
              target="_blank"
              rel="noopener noreferrer"
            >
              디스코드 알람받기
            </a>

            <a
              className="btn controlOkx"
              href="https://okx.com/join/84237472"
              target="_blank"
              rel="noopener noreferrer"
            >
              OKX 가입
            </a>

            <div className="fontControls controlFont">
              <button className="btn btnTiny" onClick={() => setFontBasePx((v) => clampInt(v - 1, 14, 20))}>
                A-
              </button>
              <div className="muted fontValue">{fontBasePx}px</div>
              <button className="btn btnTiny" onClick={() => setFontBasePx((v) => clampInt(v + 1, 14, 20))}>
                A+
              </button>
              <button className="btn btnTiny" onClick={() => setFontBasePx(16)}>
                Reset
              </button>
            </div>

            <button className="btn controlGlossary" onClick={() => openGlossary()}>
              용어사전
            </button>

          </div>
        </div>
      </header>

      <main className="wrap">
        <div className="statusRow">
          <div className="statusItem">
            <span className={updateBadge.cls}>{updateBadge.label}</span>
            <span className="muted">
              다음 업데이트 {fmtCountdown(countdownSec)} (1m)
              {lastUpdateAgeSec !== null ? ` · 마지막 수신 ${lastUpdateAgeSec}s 전` : ''}
            </span>
          </div>

          <div className="statusItem muted statusRight">
            {latest?.latest ? (
              <>
                1m {fmtTs(latest.latest['1m']?.ts)} · 30m {fmtTs(latest.latest['30m']?.ts)} · 60m {fmtTs(latest.latest['60m']?.ts)} · 180m{' '}
                {fmtTs(latest.latest['180m']?.ts)}
              </>
            ) : (
              '데이터 상태: -'
            )}
          </div>
        </div>

        {notifyMsg ? <div className="toast">{notifyMsg}</div> : null}
        {err ? <div className="toast toastError">오류: {err}</div> : null}

        <div className="layoutGrid">
          <section className="panel">
            <div className="panelHeader">
              <div>
                <div className="panelTitle">Chart</div>
                <div className="muted panelSub">
                  TF <b>{selectedTf}</b>
                  {regime?.bias ? (
                    <span className="pill">
                      <Term label={`Regime: ${regime.bias}`} term="Regime" />
                    </span>
                  ) : null}
                  {regime?.confidence !== undefined ? (
                    <span className="pill">
                      <Term label={`conf ${regime.confidence}`} term="Conf" />
                    </span>
                  ) : null}
                  {selectedRuleMeta ? (
                    <span className="pill">
                      <Term label={selectedRuleMeta.title} term="Ready Rule" />
                    </span>
                  ) : null}
                </div>
              </div>

              <div className="priceHeader">
                <div className="priceTopRow">
                  <div className="priceNow">{fmt(lastPrice)}</div>
                  <div className="mobileQuickLinks">
                    <a
                      className="btn discordCtaMobile"
                      href="https://discord.gg/cAPcXQh7K"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      디스코드 알람
                    </a>
                    <a
                      className="btn okxCtaMobile"
                      href="https://okx.com/join/84237472"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      OKX 가입
                    </a>
                  </div>
                </div>
                {priceDeltaPct !== null ? (
                  <div className={`priceDelta ${priceDeltaPct >= 0 ? 'up' : 'down'}`}>
                    {priceDeltaPct >= 0 ? '+' : ''}
                    {fmtPct(priceDeltaPct, 2)}
                  </div>
                ) : null}
              </div>
            </div>

            <div className="chartBox">
              <PriceChart candles={candles} scenario={hasPlan ? scenario : null} windowBars={chartWindowBars} />
            </div>

            <div className="muted panelFoot">
              {hasPlan
                ? '추천 후: Entry/Stop/TP 라인이 표시됩니다. (SMA5/SMA200은 항상 표시)'
                : '추천 전: 현재 가격과 SMA 라인만 표시됩니다. LONG/SHORT를 눌러 추천을 생성하세요.'}
            </div>

            <div className="kpiGrid">
              <div className="kpi">
                <div className="muted">
                  <Term label="상태" term="Score" />
                </div>
                <div className={`kpiValue ${selected?.status === 'ready' ? 'ok' : 'wait'}`}>
                  {selected?.status?.toUpperCase?.() ?? '-'}
                </div>
              </div>
              <div className="kpi">
                <div className="muted">
                  <Term label="신뢰도" term="Conf" />
                </div>
                <div className="kpiValue">{selected?.confidence !== undefined ? `${selected.confidence}` : '-'}</div>
              </div>
              <div className="kpi">
                <div className="muted">
                  <Term label="ATR%" term="ATR%" />
                </div>
                <div className="kpiValue">{fmtPct(selected?.atr_pct, 3)}</div>
              </div>
              <div className="kpi">
                <div className="muted">다음 봉까지</div>
                <div className="kpiValue">
                  {selected?.time_to_next_sec !== undefined ? `${Math.round(selected.time_to_next_sec / 60)}m` : '-'}
                </div>
              </div>
            </div>
          </section>

          <aside className="panel">
            <div className="panelHeader">
              <div>
                <div className="panelTitle">Recommendation</div>
                <div className="muted panelSub">
                  {hasPlan ? (
                    <>
                      방향 <b>{plan?.side?.toUpperCase?.()}</b> · TF <b>{plan?.tf}</b>
                    </>
                  ) : (
                    <>LONG/SHORT 버튼을 누르면 Entry/Stop/TP가 표시됩니다.</>
                  )}
                </div>
              </div>
            </div>

            {notes.length > 0 ? (
              <div className="notice">
                {notes.map((n, i) => (
                  <div key={`${n}-${i}`}>• {n}</div>
                ))}
              </div>
            ) : null}

            {hasPlan ? (
              <>
                <div className="priceGrid">
                  <div className="priceCard">
                    <div className="muted">
                      <Term label="Entry" term="ATR(14)" /> <span className="muted">({plan?.entry_type})</span>
                    </div>
                    <div className="priceValue">{fmt(plan?.entry_price)}</div>
                    <div className="muted">
                      k={plan?.params?.entry_atr_k ?? '-'} · 거리 {plan?.entry_distance_pct ?? '-'}%
                    </div>
                  </div>

                  <div className="priceCard">
                    <div className="muted">
                      <Term label="Stop" term="ATR(14)" />
                    </div>
                    <div className="priceValue">{fmt(plan?.stop_price)}</div>
                    <div className="muted">
                      ATR x {plan?.params?.stop_atr_mult ?? '-'} · {plan?.stop_distance_pct ?? '-'}%
                    </div>
                  </div>

                  <div className="priceCard">
                    <div className="muted">
                      <Term label="TP1" term="SMA5" />
                    </div>
                    <div className="priceValue">{fmt(plan?.tp1_price)}</div>
                    <div className="muted">
                      <Term label="R:R" term="R:R" /> {plan?.reward_risk_to_tp1 ?? '-'}
                    </div>
                  </div>
                </div>

                <div className="planMeta">
                  <div className="metaRow">
                    <span className="muted">TP2/TP3</span>
                    <span>
                      <b>{renderTpValue(plan?.tp2_price, selectedRecommendedTp === 'TP2' && selected?.status === 'ready')}</b> / <b>{fmt(plan?.tp3_price)}</b>
                    </span>
                  </div>
                  <div className="metaRow">
                    <span className="muted">TP1</span>
                    <span>
                      <b>{renderTpValue(plan?.tp1_price, selectedRecommendedTp === 'TP1' && selected?.status === 'ready')}</b>
                    </span>
                  </div>
                  <div className="metaRow">
                    <span className="muted">
                      <Term label="Ready Rule" term="Ready Rule" />
                    </span>
                    <span>
                      <b>{selectedRuleMeta?.title ?? '-'}</b>{' '}
                      <span className="muted">
                        {selectedRuleMdd != null ? `· MDD ${formatRuleMdd(selectedRuleMdd)}` : ''}
                      </span>
                    </span>
                  </div>
                  <div className="metaRow">
                    <span className="muted">추천 TP</span>
                    <span>
                      <b>{selectedRecommendedTp}</b>{' '}
                      {selected?.status === 'ready' ? (
                        <span className="muted">
                          ({selectedRecommendedTp === 'TP2' ? fmt(plan?.tp2_price) : fmt(plan?.tp1_price)})
                        </span>
                      ) : null}
                    </span>
                  </div>
                  {isNoStopRule ? (
                    <div className="metaRow">
                      <span className="muted">청산 방식</span>
                      <span>No Stop({selectedRuleMeta?.title})</span>
                    </div>
                  ) : null}
                </div>
              </>
            ) : null}
          </aside>
        </div>

        {hasPlan ? (
          <section className="panel" style={{ marginTop: '1rem' }}>
            <div className="panelHeader">
              <div>
                <div className="panelTitle">Timeframe Ranking</div>
                <div className="muted panelSub">TF 후보 점수(진입 용이성 + 백테스트 + 레짐 + 변동성)</div>
              </div>
            </div>

            <div className="tableScroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>TF</th>
                    <th>
                      <Term label="Score" term="Score" />
                    </th>
                    <th>
                      <Term label="Comp" term="Comp" />
                    </th>
                    <th>
                      <Term label="Conf" term="Conf" />
                    </th>
                    <th>
                      <Term label="BT" term="BT" />
                    </th>
                    <th>Rule</th>
                    <th>Rule MDD</th>
                    <th>Signal</th>
                    <th>Close</th>
                    <th>
                      <Term label="SMA5" term="SMA5" />
                    </th>
                    <th>
                      <Term label="RSI2" term="RSI(2)" />
                    </th>
                    <th>
                      <Term label="ATR%" term="ATR%" />
                    </th>
                    <th>Next</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((c: any) => (
                    <tr
                      key={c.tf}
                      className={c.tf === rec?.plan?.tf ? 'rowActive' : ''}
                      onClick={() => selectTimeframe(String(c.tf))}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') selectTimeframe(String(c.tf));
                      }}
                    >
                      <td>
                        <b>{c.tf}</b>
                      </td>
                      <td>{c.entry_ease_score}</td>
                      <td>{c.composite_score ?? '-'}</td>
                      <td>{c.confidence ?? '-'}</td>
                      <td>
                        <div className="barWrap" title="최근 백테스트 점수(정규화)">
                          <div className="barFill" style={{ width: `${Math.round((Number(c.backtest_score_norm) || 0) * 100)}%` }} />
                        </div>
                      </td>
                      <td>{(c.ready_rule ?? '-').toUpperCase?.() ?? '-'}</td>
                      <td>{formatRuleMdd(c.ready_rule_mdd_pct)}</td>
                      <td>{c.trigger_now ? 'READY' : 'WAIT'}</td>
                      <td>{fmt(c.close)}</td>
                      <td>{fmt(c.sma5)}</td>
                      <td>{Number(c.rsi2).toFixed(2)}</td>
                      <td>{fmtPct(c.atr_pct, 3)}</td>
                      <td>{Math.round(Number(c.time_to_next_sec) / 60)}m</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ) : null}
      </main>

      <GlossaryModal open={glossaryOpen} initialQuery={glossaryQuery} onClose={() => setGlossaryOpen(false)} />
    </>
  );
}

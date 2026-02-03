import React, { useEffect, useMemo, useState } from 'react';
import { fetchCandles, fetchLatest, fetchRecommend, notifyRecommend, type Candle, type Scenario } from './api';
import PriceChart from './components/PriceChart';
import GlossaryModal from './components/GlossaryModal';

type Side = 'long' | 'short';

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

  function openGlossary(term?: string) {
    setGlossaryQuery(term ?? '');
    setGlossaryOpen(true);
  }

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
        if (!cancelled) setCandles(c.candles ?? []);
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
      <header className="topBar">
        <div className="wrap topBarInner">
          <div className="brand">
            <div className="brandTitle">Wonyodd Reco</div>
            <div className="muted brandSub">
              1D 레짐 + 30m/60m/180m 후보 중 “지금 진입이 쉬운 TF”를 고르고 Entry/Stop/TP를 제안합니다.
            </div>
          </div>

          <div className="topControls">
            <div className="segmented">
              <button
                className={`segBtn ${side === 'long' ? 'segBtnActiveLong' : ''}`}
                onClick={() => {
                  setSide('long');
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
                  runRecommend('short');
                }}
                disabled={busy}
              >
                SHORT
              </button>
            </div>

            <div className="inputGroup">
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

            <button className="btn btnPrimary" onClick={() => runRecommend(side)} disabled={busy}>
              {busy ? '계산 중...' : '추천 계산'}
            </button>

            <button className="btn" onClick={sendDiscord} disabled={busy || !hasPlan}>
              디스코드 전송
            </button>

            <div className="fontControls">
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

            <button className="btn" onClick={() => openGlossary()}>
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

          <div className="statusItem muted" style={{ marginLeft: 'auto' }}>
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
                </div>
              </div>

              <div className="priceHeader">
                <div className="priceNow">{fmt(lastPrice)}</div>
                {priceDeltaPct !== null ? (
                  <div className={`priceDelta ${priceDeltaPct >= 0 ? 'up' : 'down'}`}>
                    {priceDeltaPct >= 0 ? '+' : ''}
                    {fmtPct(priceDeltaPct, 2)}
                  </div>
                ) : null}
              </div>
            </div>

            <div className="chartBox">
              <PriceChart candles={candles} scenario={hasPlan ? scenario : null} />
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
                      <b>{fmt(plan?.tp2_price)}</b> / <b>{fmt(plan?.tp3_price)}</b>
                    </span>
                  </div>
                  <div className="metaRow">
                    <span className="muted">권장 최대 배율</span>
                    <span>
                      <b>{plan?.max_leverage_by_risk ?? '-'}</b>x <span className="muted">(리스크 {plan?.risk_pct ?? '-'}%)</span>
                    </span>
                  </div>
                  <div className="metaRow">
                    <span className="muted">청산 룰</span>
                    <span>{plan?.tp_rule ?? '-'}</span>
                  </div>
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

            <div style={{ overflow: 'auto' }}>
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

import React, { useEffect, useMemo, useState } from 'react';
import { fetchCandles, fetchLatest, fetchRecommend, type Candle, type Scenario } from './api';
import PriceChart from './components/PriceChart';

type Side = 'long' | 'short';

function fmt(x: any): string {
  const n = Number(x);
  if (!Number.isFinite(n)) return '-';
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function fmtTs(ts: number | undefined): string {
  if (!ts) return '-';
  return new Date(ts * 1000).toLocaleString();
}

export default function App() {
  const [side, setSide] = useState<Side>('long');
  const [riskPct, setRiskPct] = useState<number>(0.5);
  const [latest, setLatest] = useState<any>(null);
  const [rec, setRec] = useState<any>(null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const selectedTf = rec?.plan?.tf;

  async function refreshLatestUI() {
    try {
      const data = await fetchLatest();
      setLatest(data);
    } catch (e: any) {
      // ignore
    }
  }

  async function runRecommend(nextSide: Side) {
    setBusy(true);
    setErr(null);
    try {
      const data = await fetchRecommend(nextSide, riskPct);
      if (!data.ok) {
        setRec(data);
        setCandles([]);
        setScenario(null);
        setErr(data.error ?? 'unknown error');
        return;
      }
      setRec(data);

      const tf = data.plan?.tf;
      const scen = data.plan?.scenario ?? null;
      setScenario(scen);

      if (tf) {
        const c = await fetchCandles(tf, 220);
        setCandles(c.candles ?? []);
      } else {
        setCandles([]);
      }
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
      refreshLatestUI();
    }
  }

  useEffect(() => {
    refreshLatestUI();
    // initial load
    runRecommend('long');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const regime = rec?.regime;
  const plan = rec?.plan;
  const candidates = useMemo(() => (Array.isArray(rec?.candidates) ? rec.candidates : []), [rec]);

  return (
    <>
      <header>
        <div className="wrap">
          <div className="title">진입 가격 추천 (차트 UI · LONG/SHORT 선택)</div>
          <div className="muted">
            1D 레짐(SMA200) + 30m/60m/180m 진입 용이성 점수로 TF 1개를 고른 뒤, Entry/Stop/TP/배율을 제안합니다.
          </div>
        </div>
      </header>

      <div className="wrap">
        <div className="row" style={{ marginBottom: 12, alignItems: 'center' }}>
          <button
            className={`btn ${side === 'long' ? 'btnPrimary' : ''}`}
            onClick={() => {
              setSide('long');
              runRecommend('long');
            }}
            disabled={busy}
          >
            LONG
          </button>
          <button
            className={`btn ${side === 'short' ? 'btnPrimary' : ''}`}
            onClick={() => {
              setSide('short');
              runRecommend('short');
            }}
            disabled={busy}
          >
            SHORT
          </button>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span className="muted">리스크(%)</span>
            <input
              type="number"
              step={0.05}
              min={0.05}
              max={2}
              value={riskPct}
              onChange={(e) => setRiskPct(Number(e.target.value))}
              style={{ width: 90 }}
              disabled={busy}
            />
            <button className="btn" onClick={() => runRecommend(side)} disabled={busy}>
              다시 계산
            </button>
          </div>

          <div className="muted" style={{ marginLeft: 'auto' }}>
            {latest?.latest ? (
              <>
                1D: {fmtTs(latest.latest['1D']?.ts)} · 30m: {fmtTs(latest.latest['30m']?.ts)} · 60m:{' '}
                {fmtTs(latest.latest['60m']?.ts)} · 180m: {fmtTs(latest.latest['180m']?.ts)}
              </>
            ) : (
              '데이터 상태: -'
            )}
          </div>
        </div>

        <div className="grid2">
          <div className="card">
            <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 650 }}>차트</div>
                <div className="muted">
                  선택 TF: <b>{selectedTf ?? '-'}</b>
                  {regime?.bias ? <span className="pill">1D {regime.bias}</span> : null}
                  {regime?.confidence !== undefined ? <span className="pill">conf {regime.confidence}</span> : null}
                </div>
              </div>
              {busy ? <span className="muted">계산 중…</span> : null}
            </div>

            <div className="chartBox" style={{ marginTop: 10 }}>
              <PriceChart candles={candles} scenario={scenario} />
            </div>
            <div className="muted" style={{ marginTop: 10 }}>
              차트 위 점선: Entry/Stop/TP1 · 가이드 라인: (현재가 → Entry → TP1) 시나리오
            </div>
          </div>

          <div className="card">
            <div style={{ fontSize: 16, fontWeight: 650 }}>추천 플랜</div>
            <div className="muted" style={{ marginTop: 6 }}>
              {regime?.last_close !== undefined && regime?.sma200 !== undefined ? (
                <>1D close={fmt(regime.last_close)} / SMA200={fmt(regime.sma200)}</>
              ) : (
                '1D 레짐 데이터가 부족하면 추천이 보수적으로 바뀔 수 있습니다.'
              )}
            </div>

            {err ? (
              <div className="muted" style={{ marginTop: 10 }}>
                오류: {err}
              </div>
            ) : null}

            <div style={{ marginTop: 10 }}>
              <table>
                <tbody>
                  <tr>
                    <th>방향</th>
                    <td>
                      <b>{plan?.side?.toUpperCase?.() ?? '-'}</b>
                    </td>
                  </tr>
                  <tr>
                    <th>TF</th>
                    <td>
                      <b>{plan?.tf ?? '-'}</b>
                    </td>
                  </tr>
                  <tr>
                    <th>Entry</th>
                    <td>
                      <b>{fmt(plan?.entry_price)}</b> <span className="muted">({plan?.entry_type})</span>
                    </td>
                  </tr>
                  <tr>
                    <th>Stop</th>
                    <td>
                      <b>{fmt(plan?.stop_price)}</b> <span className="muted">(ATR×{plan?.params?.stop_atr_mult})</span>
                    </td>
                  </tr>
                  <tr>
                    <th>TP1</th>
                    <td>
                      <b>{fmt(plan?.tp1_price)}</b> <span className="muted">(SMA5 회복)</span>
                    </td>
                  </tr>
                  <tr>
                    <th>손절폭</th>
                    <td>{plan?.stop_distance_pct ?? '-'}%</td>
                  </tr>
                  <tr>
                    <th>권장 최대 배율</th>
                    <td>
                      <b>{plan?.max_leverage_by_risk ?? '-'}</b>x <span className="muted">(리스크 {plan?.risk_pct ?? '-'}%)</span>
                    </td>
                  </tr>
                  <tr>
                    <th>R:R(대략)</th>
                    <td>{plan?.reward_risk_to_tp1 ?? '-'}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="muted" style={{ marginTop: 10 }}>
              청산 룰: {plan?.tp_rule ?? '-'}
            </div>
          </div>
        </div>

        <div className="card" style={{ marginTop: 12 }}>
          <div style={{ fontSize: 16, fontWeight: 650 }}>TF 후보 점수</div>
          <div className="muted" style={{ marginTop: 6 }}>
            entry_ease_score가 높은 TF가 우선이며, 상위 후보는 최근 백테스트 점수(수익/MDD 균형)로 2차 선별합니다.
          </div>

          <div style={{ marginTop: 10, overflow: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>TF</th>
                  <th>Score</th>
                  <th>Signal</th>
                  <th>Close</th>
                  <th>SMA5</th>
                  <th>RSI2</th>
                  <th>Next</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((c: any) => (
                  <tr key={c.tf}
                    style={c.tf === selectedTf ? { background: '#0b0f19' } : undefined}
                  >
                    <td>
                      <b>{c.tf}</b>
                    </td>
                    <td>{c.entry_ease_score}</td>
                    <td>{c.trigger_now ? 'READY' : 'WAIT'}</td>
                    <td>{fmt(c.close)}</td>
                    <td>{fmt(c.sma5)}</td>
                    <td>{Number(c.rsi2).toFixed(2)}</td>
                    <td>{Math.round(Number(c.time_to_next_sec) / 60)}m</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}

import React, { useEffect, useMemo, useRef } from 'react';
import {
  ColorType,
  createChart,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts';
import type { Candle, Scenario } from '../api';

function toTs(t: number): UTCTimestamp {
  return t as UTCTimestamp;
}

export default function PriceChart({
  candles,
  scenario,
}: {
  candles: Candle[];
  scenario?: Scenario | null;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const pathSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const sma5SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const sma200SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const priceLineCleanupRef = useRef<(() => void) | null>(null);

  const candleData = useMemo(
    () =>
      candles.map((c) => ({
        time: toTs(c.ts),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
        ...(c.is_partial
          ? {
              color: '#2d86ff',
              borderColor: '#2d86ff',
              wickColor: '#2d86ff',
            }
          : {}),
      })),
    [candles],
  );

  const closeSeries = useMemo(() => candles.map((c) => c.close), [candles]);
  const timeSeries = useMemo(() => candles.map((c) => toTs(c.ts)), [candles]);

  function sma(values: number[], period: number): Array<number | null> {
    if (values.length < period) return values.map(() => null);
    const out: Array<number | null> = Array(values.length).fill(null);
    let sum = 0;
    for (let i = 0; i < values.length; i++) {
      sum += values[i];
      if (i >= period) sum -= values[i - period];
      if (i >= period - 1) out[i] = sum / period;
    }
    return out;
  }

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;

    const el = containerRef.current;
    const chart = createChart(el, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#e7e9ee',
      },
      grid: {
        vertLines: { color: '#24304f' },
        horzLines: { color: '#24304f' },
      },
      rightPriceScale: {
        borderColor: '#24304f',
      },
      timeScale: {
        borderColor: '#24304f',
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        vertLine: { color: '#2b3b63' },
        horzLine: { color: '#2b3b63' },
      },
      width: el.clientWidth,
      height: el.clientHeight,
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
      borderUpColor: '#26a69a',
      borderDownColor: '#ef5350',
    });

    const pathSeries = chart.addLineSeries({
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
    });
    const sma5Series = chart.addLineSeries({
      color: '#3f6bf6',
      lineWidth: 1,
    });
    const sma200Series = chart.addLineSeries({
      color: '#8a93a9',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    pathSeriesRef.current = pathSeries;
    sma5SeriesRef.current = sma5Series;
    sma200SeriesRef.current = sma200Series;

    // ResizeObserver for responsive layout
    const ro = new ResizeObserver(() => {
      if (!containerRef.current || !chartRef.current) return;
      chartRef.current.applyOptions({
        width: containerRef.current.clientWidth,
        height: containerRef.current.clientHeight,
      });
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      pathSeriesRef.current = null;
      sma5SeriesRef.current = null;
      sma200SeriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const candleSeries = candleSeriesRef.current;
    const chart = chartRef.current;
    if (!candleSeries || !chart) return;
    candleSeries.setData(candleData);
    const sma5Series = sma5SeriesRef.current;
    const sma200Series = sma200SeriesRef.current;
    if (sma5Series && sma200Series) {
      const sma5 = sma(closeSeries, 5);
      const sma200 = sma(closeSeries, 200);
      sma5Series.setData(
        sma5
          .map((v, i) => (v === null ? null : { time: timeSeries[i], value: v }))
          .filter((v): v is { time: UTCTimestamp; value: number } => v !== null),
      );
      sma200Series.setData(
        sma200
          .map((v, i) => (v === null ? null : { time: timeSeries[i], value: v }))
          .filter((v): v is { time: UTCTimestamp; value: number } => v !== null),
      );
    }
    chart.timeScale().fitContent();
  }, [candleData, closeSeries, timeSeries]);

  useEffect(() => {
    // Clean old price lines
    if (priceLineCleanupRef.current) priceLineCleanupRef.current();
    priceLineCleanupRef.current = null;

    const candleSeries = candleSeriesRef.current;
    const pathSeries = pathSeriesRef.current;
    if (!candleSeries || !pathSeries) return;

    if (!scenario) {
      pathSeries.setData([]);
      return;
    }

    // Scenario path (guide line)
    pathSeries.setData(
      scenario.path.map((p) => ({
        time: toTs(p.ts),
        value: p.value,
      })),
    );

    // Horizontal levels: Entry/Stop/TP1
    const lines = [
      { price: scenario.levels.entry, title: 'Entry' },
      { price: scenario.levels.stop, title: 'Stop' },
      { price: scenario.levels.tp1, title: 'TP1' },
      ...(scenario.levels.tp2 ? [{ price: scenario.levels.tp2, title: 'TP2' }] : []),
    ].map((x) => candleSeries.createPriceLine({
      price: x.price,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: x.title,
    }));

    priceLineCleanupRef.current = () => {
      try {
        for (const ln of lines) candleSeries.removePriceLine(ln);
      } catch {
        // ignore
      }
    };
  }, [scenario]);

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />;
}

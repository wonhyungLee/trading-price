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
  const priceLineCleanupRef = useRef<(() => void) | null>(null);

  const candleData = useMemo(
    () =>
      candles.map((c) => ({
        time: toTs(c.ts),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    [candles],
  );

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
      // keep defaults; only set subtle borders so it reads on dark background
      borderVisible: false,
      wickVisible: true,
    });

    const pathSeries = chart.addLineSeries({
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    pathSeriesRef.current = pathSeries;

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
    };
  }, []);

  useEffect(() => {
    const candleSeries = candleSeriesRef.current;
    const chart = chartRef.current;
    if (!candleSeries || !chart) return;
    candleSeries.setData(candleData);
    chart.timeScale().fitContent();
  }, [candleData]);

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

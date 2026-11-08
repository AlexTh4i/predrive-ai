import { useCallback, useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import { DriverAnalyzer } from '../ai/driverAnalyzer';
import type { AnalysisResult } from '../ai/driverAnalyzer';

export type AiStatus = 'idle' | 'loading' | 'ready' | 'error';

/** ~10 lần phân tích mỗi giây là đủ cho ngưỡng 1s/2s và nhẹ pin hơn chạy mọi khung hình */
const ANALYZE_INTERVAL_MS = 100;

function isSame(a: AnalysisResult | null, b: AnalysisResult): boolean {
  return (
    a !== null &&
    a.state === b.state &&
    a.alertLevel === b.alertLevel &&
    a.faceVisible === b.faceVisible &&
    a.imageQuality === b.imageQuality
  );
}

export function useDriverAI(videoRef: RefObject<HTMLVideoElement | null>) {
  const analyzerRef = useRef<DriverAnalyzer | null>(null);
  const timerRef = useRef<number | null>(null);
  const [aiStatus, setAiStatus] = useState<AiStatus>('idle');
  const [aiError, setAiError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);

  const load = useCallback(async (): Promise<boolean> => {
    if (analyzerRef.current) return true;
    setAiStatus('loading');
    setAiError(null);
    try {
      analyzerRef.current = await DriverAnalyzer.create();
      setAiStatus('ready');
      return true;
    } catch (err) {
      console.error('Không tải được AI:', err);
      setAiStatus('error');
      setAiError(err instanceof Error ? err.message : String(err));
      return false;
    }
  }, []);

  const stop = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    analyzerRef.current?.reset();
    setResult(null);
  }, []);

  const start = useCallback(() => {
    if (timerRef.current !== null) return;
    analyzerRef.current?.reset();
    timerRef.current = window.setInterval(() => {
      const video = videoRef.current;
      const analyzer = analyzerRef.current;
      if (!video || !analyzer) return;
      const next = analyzer.analyze(video);
      setResult((prev) => (isSame(prev, next) ? prev : next));
    }, ANALYZE_INTERVAL_MS);
  }, [videoRef]);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearInterval(timerRef.current);
      analyzerRef.current?.close();
      analyzerRef.current = null;
    };
  }, []);

  return { aiStatus, aiError, result, load, start, stop };
}


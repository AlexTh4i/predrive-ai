import { useState, useRef, useCallback, useEffect } from 'react';
import type { 
  DriverState, 
  AlertLevel, 
  BackendConnectionStatus, 
  AnalysisResultPayload,
  SystemDiagnostics,
  ImageQuality
} from '../types/monitor';
import { MonitorSocketClient } from '../services/monitorSocket';
import { createSession } from '../services/api';
import { CONFIG } from '../config/env';

interface UseMonitorSocketProps {
  onStateChange: (state: DriverState, alertLevel: AlertLevel) => void;
  getFrameBase64: () => string | null;
}

export function useMonitorSocket({ onStateChange, getFrameBase64 }: UseMonitorSocketProps) {
  const [backendStatus, setBackendStatus] = useState<BackendConnectionStatus>('disconnected');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [diagnostics, setDiagnostics] = useState<SystemDiagnostics>({
    fps: 0,
    rttMs: null,
    framesSent: 0,
    framesReceived: 0,
    lastCapturedAt: null,
    lastProcessedAt: null,
    modelVersion: 'none',
    imageQuality: 'UNKNOWN',
    processingMs: null,
  });

  const socketClientRef = useRef<MonitorSocketClient | null>(null);
  const frameIntervalRef = useRef<number | null>(null);
  const frameCounterRef = useRef<number>(0);
  const isMockModeRef = useRef<boolean>(false);
  const fpsWindowRef = useRef<number[]>([]);

  // Cleanup khi ngắt kết nối
  const stopStreaming = useCallback(() => {
    setIsStreaming(false);
    if (frameIntervalRef.current) {
      window.clearInterval(frameIntervalRef.current);
      frameIntervalRef.current = null;
    }
    if (socketClientRef.current) {
      socketClientRef.current.disconnect();
      socketClientRef.current = null;
    }
    setBackendStatus('disconnected');
    setSessionId(null);
    frameCounterRef.current = 0;
    isMockModeRef.current = false;
  }, []);

  // Xử lý khi có kết quả phân tích
  const handleAnalysisResult = useCallback((result: AnalysisResultPayload) => {
    const now = Date.now();
    const sentTime = new Date(result.captured_at).getTime();
    const rtt = !isNaN(sentTime) ? Math.max(0, now - sentTime) : null;

    setDiagnostics(prev => {
      const updatedReceived = prev.framesReceived + 1;
      // Đo FPS nhận thực tế
      const curSeconds = Math.floor(now / 1000);
      fpsWindowRef.current.push(curSeconds);
      fpsWindowRef.current = fpsWindowRef.current.filter(t => t >= curSeconds - 2);
      const calculatedFps = Math.round(fpsWindowRef.current.length / 2);

      return {
        ...prev,
        framesReceived: updatedReceived,
        fps: calculatedFps,
        rttMs: rtt,
        lastProcessedAt: result.processed_at,
        modelVersion: result.model_version,
        imageQuality: result.image_quality as ImageQuality,
        processingMs: result.processing_ms,
      };
    });

    onStateChange(result.state, result.alert_level);
  }, [onStateChange]);

  // Vòng lặp gửi frame định kỳ
  const startFrameLoop = useCallback((activeSessionId: string, isMock: boolean) => {
    if (frameIntervalRef.current) {
      window.clearInterval(frameIntervalRef.current);
    }

    frameIntervalRef.current = window.setInterval(() => {
      const base64Img = getFrameBase64();
      if (!base64Img) return;

      frameCounterRef.current += 1;
      const curFrameId = frameCounterRef.current;
      const capturedAt = new Date().toISOString();

      setDiagnostics(prev => ({
        ...prev,
        framesSent: prev.framesSent + 1,
        lastCapturedAt: capturedAt,
      }));

      if (isMock) {
        // Mô phỏng phản hồi mock-v0 theo đúng hợp đồng MVP v0.1
        // Trễ mô phỏng 25ms, trả về NOT_EVALUATED, alert NONE
        setTimeout(() => {
          const mockResult: AnalysisResultPayload = {
            type: 'analysis_result',
            session_id: activeSessionId,
            frame_id: curFrameId,
            captured_at: capturedAt,
            processed_at: new Date().toISOString(),
            model_version: CONFIG.DEMO_MOCK_VERSION, // 'mock-v0'
            state: 'NOT_EVALUATED',
            alert_level: 'NONE',
            face_visible: null,
            image_quality: 'UNKNOWN',
            risk_score: null,
            processing_ms: 25,
          };
          handleAnalysisResult(mockResult);
        }, 25);
      } else {
        if (socketClientRef.current) {
          socketClientRef.current.sendFrame(curFrameId, base64Img, capturedAt);
        }
      }
    }, CONFIG.FRAME_INTERVAL_MS);
  }, [getFrameBase64, handleAnalysisResult]);

  // Bắt đầu phiên giám sát (thử nối backend thật, fallback sang mock nếu offline)
  const startStreaming = useCallback(async (): Promise<{ isMock: boolean; sessionId: string }> => {
    setErrorMessage(null);
    setBackendStatus('connecting');
    frameCounterRef.current = 0;
    fpsWindowRef.current = [];

    setDiagnostics({
      fps: 0,
      rttMs: null,
      framesSent: 0,
      framesReceived: 0,
      lastCapturedAt: null,
      lastProcessedAt: null,
      modelVersion: 'none',
      imageQuality: 'UNKNOWN',
      processingMs: null,
    });

    let activeSessionId: string;
    let isMock = false;

    try {
      // 1. Cố gắng tạo phiên thật từ FastAPI Backend
      const sessionData = await createSession();
      activeSessionId = sessionData.session_id;
      setSessionId(activeSessionId);

      // 2. Mở kết nối WebSocket thật
      const client = new MonitorSocketClient({
        sessionId: activeSessionId,
        onStatusChange: (status, msg) => {
          setBackendStatus(status);
          if (msg) setErrorMessage(msg);
        },
        onAnalysisResult: handleAnalysisResult,
        onError: (err) => {
          setErrorMessage(err.message);
        },
      });

      socketClientRef.current = client;
      client.connect();
    } catch {
      // Backend offline -> Fallback chế độ Demo Mock v0
      isMock = true;
      isMockModeRef.current = true;
      activeSessionId = `mock-session-${Date.now()}`;
      setSessionId(activeSessionId);
      setBackendStatus('mock_demo');
      setErrorMessage(null);
    }

    setIsStreaming(true);
    startFrameLoop(activeSessionId, isMock);

    return { isMock, sessionId: activeSessionId };
  }, [handleAnalysisResult, startFrameLoop]);

  // Dọn dẹp khi unmount
  useEffect(() => {
    return () => {
      stopStreaming();
    };
  }, [stopStreaming]);

  return {
    backendStatus,
    sessionId,
    isStreaming,
    errorMessage,
    diagnostics,
    startStreaming,
    stopStreaming,
  };
}

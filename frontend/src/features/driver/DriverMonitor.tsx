import React, { useState, useCallback } from 'react';
import { useCamera } from '../../hooks/useCamera';
import { useSessionTimer } from '../../hooks/useSessionTimer';
import { useAlertSound } from '../../hooks/useAlertSound';
import { useMonitorSocket } from '../../hooks/useMonitorSocket';
import type { DriverState, AlertLevel, UnavailableReason } from '../../types/monitor';

import { Header } from '../../components/Header';
import { CameraPreview } from '../../components/CameraPreview';
import { MonitoringControls } from '../../components/MonitoringControls';
import { StatusBadge } from '../../components/StatusBadge';
import { DiagnosticsPanel } from '../../components/DiagnosticsPanel';
import { Footer } from '../../components/Footer';
import { AlertTriangle, HelpCircle, CheckCircle2, EyeOff, Radio } from 'lucide-react';

interface DriverMonitorProps {
  currentView: 'driver' | 'admin';
  onViewChange: (view: 'driver' | 'admin') => void;
}

export const DriverMonitor: React.FC<DriverMonitorProps> = ({
  currentView,
  onViewChange,
}) => {
  const [driverState, setDriverState] = useState<DriverState>('NOT_EVALUATED');
  const [alertLevel, setAlertLevel] = useState<AlertLevel>('NONE');
  const [unavailableReason, setUnavailableReason] = useState<UnavailableReason | null>(null);
  const [showDiagnostics, setShowDiagnostics] = useState<boolean>(false);

  // Hook cảnh báo âm thanh
  const { isMuted, toggleMute, triggerAlertSound } = useAlertSound();

  // Hook đếm thời gian phiên
  const { formattedDuration, startTimer, stopTimer, resetTimer } = useSessionTimer();

  // Xử lý gián đoạn camera (tab ẩn, ngắt kết nối...)
  const handleCameraInterrupted = useCallback((reason: UnavailableReason) => {
    setUnavailableReason(reason);
    setDriverState('MONITORING_UNAVAILABLE');
    setAlertLevel('WARNING');
  }, []);

  // Hook Camera thật
  const {
    videoRef,
    isCameraActive,
    isLoadingCamera,
    cameraError,
    cameraErrorMessage,
    startCamera,
    stopCamera,
    captureFrameBase64,
  } = useCamera(handleCameraInterrupted);

  // Xử lý phản hồi trạng thái từ WebSocket Gateway
  const handleStateChange = useCallback((newState: DriverState, newAlertLevel: AlertLevel) => {
    setDriverState(newState);
    setAlertLevel(newAlertLevel);
    if (newState !== 'MONITORING_UNAVAILABLE') {
      setUnavailableReason(null);
    }
    // Phát âm thanh cảnh báo khi có mức cảnh báo từ INFO trở lên
    if (newAlertLevel !== 'NONE') {
      triggerAlertSound(newAlertLevel);
    }
  }, [triggerAlertSound]);

  // Hook WebSocket & Frame streaming
  const {
    backendStatus,
    sessionId,
    isStreaming,
    diagnostics,
    startStreaming,
    stopStreaming,
  } = useMonitorSocket({
    onStateChange: handleStateChange,
    getFrameBase64: captureFrameBase64,
  });

  // Bắt đầu giám sát
  const handleStart = async () => {
    setUnavailableReason(null);
    setDriverState('NOT_EVALUATED');
    setAlertLevel('NONE');

    // 1. Kích hoạt camera thật
    const cameraSuccess = await startCamera();
    if (!cameraSuccess) {
      return;
    }

    // 2. Bắt đầu timer
    startTimer();

    // 3. Khởi tạo phiên gửi frame qua WebSocket
    await startStreaming();
  };

  // Dừng giám sát
  const handleStop = () => {
    stopCamera();
    stopStreaming();
    stopTimer();
    resetTimer();
    setDriverState('NOT_EVALUATED');
    setAlertLevel('NONE');
    setUnavailableReason(null);
  };

  // Render Compact Status Banner dành riêng cho màn hình Mobile (< 1024px)
  const renderMobileStatusBanner = () => {
    if (!isStreaming) {
      return (
        <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-900/90 border border-slate-800 text-xs font-mono text-slate-400">
          <div className="flex items-center gap-2">
            <Radio className="w-3.5 h-3.5 text-slate-500" />
            <span>Hệ thống: Sẵn sàng</span>
          </div>
          <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-400">IDLE</span>
        </div>
      );
    }

    if (driverState === 'CRITICAL' || driverState === 'DROWSINESS_SIGNS') {
      return (
        <div className="flex items-center justify-between p-2.5 rounded-xl bg-rose-950/90 border border-rose-500 text-rose-200 text-xs font-bold animate-pulse shadow-automotive-danger">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-rose-400" />
            <span>CẢNH BÁO BUỒN NGỦ ({alertLevel})</span>
          </div>
          <span className="text-[10px] px-2 py-0.5 rounded bg-rose-900 text-rose-100 font-mono">DANGER</span>
        </div>
      );
    }

    if (driverState === 'DISTRACTED') {
      return (
        <div className="flex items-center justify-between p-2.5 rounded-xl bg-amber-950/90 border border-amber-500 text-amber-200 text-xs font-bold">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            <span>MẤT TẬP TRUNG</span>
          </div>
          <span className="text-[10px] px-2 py-0.5 rounded bg-amber-900 text-amber-100 font-mono">WARNING</span>
        </div>
      );
    }

    if (driverState === 'NORMAL') {
      return (
        <div className="flex items-center justify-between p-2.5 rounded-xl bg-emerald-950/90 border border-emerald-500 text-emerald-200 text-xs font-bold">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <span>TỈNH TÁO & AN TOÀN</span>
          </div>
          <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-900 text-emerald-100 font-mono">NORMAL</span>
        </div>
      );
    }

    if (driverState === 'MONITORING_UNAVAILABLE') {
      return (
        <div className="flex items-center justify-between p-2.5 rounded-xl bg-amber-950/90 border border-amber-500/70 text-amber-200 text-xs font-bold">
          <div className="flex items-center gap-2">
            <EyeOff className="w-4 h-4 text-amber-400" />
            <span>GIÁM SÁT TẠM DỪNG ({unavailableReason || 'generic'})</span>
          </div>
          <span className="text-[10px] px-2 py-0.5 rounded bg-amber-900 text-amber-200 font-mono">PAUSED</span>
        </div>
      );
    }

    // Trạng thái NOT_EVALUATED: Phân biệt rõ ràng Backend thật vs Demo Mock
    const isBackendConnected = backendStatus === 'connected';

    return (
      <div className={`flex items-center justify-between p-2.5 rounded-xl border text-xs font-mono ${
        isBackendConnected 
          ? 'bg-sky-950/70 border-sky-500/40 text-sky-300' 
          : 'bg-amber-950/60 border-amber-500/35 text-amber-300'
      }`}>
        <div className="flex items-center gap-2 truncate">
          <HelpCircle className={`w-3.5 h-3.5 shrink-0 ${isBackendConnected ? 'text-sky-400 animate-pulse' : 'text-amber-400'}`} />
          <span className="truncate">
            {isBackendConnected 
              ? 'Đang test frame truyền tải (Chưa có AI)' 
              : 'Chế độ demo cục bộ (Chưa có AI)'}
          </span>
        </div>
        <span className={`text-[10px] px-2 py-0.5 rounded font-bold shrink-0 ${
          isBackendConnected 
            ? 'bg-sky-900/80 text-sky-200' 
            : 'bg-amber-900/80 text-amber-200'
        }`}>
          {isBackendConnected ? 'CONNECTED' : 'MOCK'}
        </span>
      </div>
    );
  };

  return (
    <div className="min-h-screen flex flex-col bg-automotive-dark text-slate-100 automotive-grid-bg">
      {/* Header Bar Tinh tế */}
      <Header
        backendStatus={backendStatus}
        isMuted={isMuted}
        toggleMute={toggleMute}
        showDiagnostics={showDiagnostics}
        toggleDiagnostics={() => setShowDiagnostics(prev => !prev)}
        currentView={currentView}
        onViewChange={onViewChange}
      />

      {/* Main Monitoring Cockpit */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-3 sm:p-5 lg:p-6 flex flex-col gap-3 sm:gap-4">
        {/* COMPACT STATUS BANNER TRÊN MOBILE (Không cần cuộn trang vẫn thấy rõ) */}
        <div className="block lg:hidden">
          {renderMobileStatusBanner()}
        </div>

        {/* Desktop Layout: 2 Cột cân đối | Mobile Layout: 1 Cột tối ưu */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-3.5 sm:gap-4 lg:gap-6 items-start">
          
          {/* CỘT CHÍNH (Trái trên Desktop - 7/12): Camera Preview trung tâm */}
          <section className="lg:col-span-7 flex flex-col gap-3.5 sm:gap-4">
            <CameraPreview
              videoRef={videoRef}
              isCameraActive={isCameraActive}
              isLoadingCamera={isLoadingCamera}
              cameraError={cameraError}
              cameraErrorMessage={cameraErrorMessage}
              fps={diagnostics.fps}
              driverState={driverState}
              alertLevel={alertLevel}
              formattedDuration={formattedDuration}
              isStreaming={isStreaming}
              backendStatus={backendStatus}
              onStartClick={handleStart}
              onStopClick={handleStop}
            />

            {/* Diagnostics Panel trên Desktop nằm ngay dưới Camera */}
            {showDiagnostics && (
              <div className="hidden lg:block">
                <DiagnosticsPanel
                  diagnostics={diagnostics}
                  sessionId={sessionId}
                  backendStatus={backendStatus}
                  onClose={() => setShowDiagnostics(false)}
                />
              </div>
            )}
          </section>

          {/* CỘT PHỤ (Phải trên Desktop - 5/12): Cockpit Telemetry & Controls */}
          <section className="lg:col-span-5 flex flex-col gap-3.5 sm:gap-4">
            {/* 1. Monitoring Controls & Session Duration */}
            <MonitoringControls
              isStreaming={isStreaming}
              formattedDuration={formattedDuration}
              onStart={handleStart}
              onStop={handleStop}
            />

            {/* 2. Driver Status & Alert Telemetry Card chi tiết */}
            <StatusBadge
              state={driverState}
              alertLevel={alertLevel}
              unavailableReason={unavailableReason}
              modelVersion={diagnostics.modelVersion}
              isStreaming={isStreaming}
              backendStatus={backendStatus}
            />

            {/* Diagnostics Panel trên Mobile hiển thị dưới cùng */}
            {showDiagnostics && (
              <div className="block lg:hidden">
                <DiagnosticsPanel
                  diagnostics={diagnostics}
                  sessionId={sessionId}
                  backendStatus={backendStatus}
                  onClose={() => setShowDiagnostics(false)}
                />
              </div>
            )}
          </section>

        </div>
      </main>

      {/* Footer disclaimer */}
      <Footer />
    </div>
  );
};

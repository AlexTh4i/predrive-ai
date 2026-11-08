import React from 'react';
import { Terminal, Cpu, Clock, Layers, Zap, X } from 'lucide-react';
import type { SystemDiagnostics, BackendConnectionStatus } from '../types/monitor';
import { CONFIG } from '../config/env';

interface DiagnosticsPanelProps {
  diagnostics: SystemDiagnostics;
  sessionId: string | null;
  backendStatus: BackendConnectionStatus;
  onClose?: () => void;
}

export const DiagnosticsPanel: React.FC<DiagnosticsPanelProps> = ({
  diagnostics,
  sessionId,
  backendStatus,
  onClose,
}) => {
  return (
    <div className="w-full bg-slate-950/95 border border-cyan-500/30 rounded-2xl p-4 sm:p-5 shadow-card-glow animate-in fade-in duration-200">
      <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-3.5">
        <div className="flex items-center gap-2 text-cyan-400 font-mono text-xs sm:text-sm font-semibold">
          <Terminal className="w-4 h-4" />
          <span>BẢNG CHẨN ĐOÁN KỸ THUẬT (TELEMETRY)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-900 text-slate-400 border border-slate-800">
            Contract v0.1
          </span>
          {onClose && (
            <button
              onClick={onClose}
              aria-label="Đóng bảng chẩn đoán"
              className="p-1 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-900 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 mb-3.5">
        {/* Metric 1: FPS */}
        <div className="bg-slate-900/90 rounded-xl p-3 border border-slate-800/80">
          <div className="flex items-center gap-1.5 text-slate-400 text-[10px] mb-1">
            <Zap className="w-3 h-3 text-cyan-400" />
            <span>Target / Actual FPS</span>
          </div>
          <div className="text-base sm:text-lg font-mono font-bold text-slate-100">
            {CONFIG.TARGET_FPS} / <span className="text-cyan-400">{diagnostics.fps > 0 ? diagnostics.fps : '0'}</span>
          </div>
        </div>

        {/* Metric 2: RTT Latency */}
        <div className="bg-slate-900/90 rounded-xl p-3 border border-slate-800/80">
          <div className="flex items-center gap-1.5 text-slate-400 text-[10px] mb-1">
            <Clock className="w-3 h-3 text-sky-400" />
            <span>Độ trễ khứ hồi (RTT)</span>
          </div>
          <div className="text-base sm:text-lg font-mono font-bold text-slate-100">
            {diagnostics.rttMs !== null ? `${diagnostics.rttMs} ms` : 'N/A'}
          </div>
        </div>

        {/* Metric 3: Model Version */}
        <div className="bg-slate-900/90 rounded-xl p-3 border border-slate-800/80">
          <div className="flex items-center gap-1.5 text-slate-400 text-[10px] mb-1">
            <Cpu className="w-3 h-3 text-amber-400" />
            <span>Model Version</span>
          </div>
          <div className="text-sm sm:text-base font-mono font-bold text-amber-300 truncate" title={diagnostics.modelVersion}>
            {diagnostics.modelVersion}
          </div>
        </div>

        {/* Metric 4: Image Quality */}
        <div className="bg-slate-900/90 rounded-xl p-3 border border-slate-800/80">
          <div className="flex items-center gap-1.5 text-slate-400 text-[10px] mb-1">
            <Layers className="w-3 h-3 text-emerald-400" />
            <span>Chất lượng ảnh</span>
          </div>
          <div className="text-sm sm:text-base font-mono font-bold text-emerald-300">
            {diagnostics.imageQuality}
          </div>
        </div>
      </div>

      {/* Frame Counter & Session Details */}
      <div className="space-y-1.5 text-[11px] font-mono text-slate-400 bg-slate-900/50 p-3 rounded-xl border border-slate-800/60">
        <div className="flex justify-between items-center">
          <span>Session UUID:</span>
          <span className="text-slate-200 truncate max-w-[200px] sm:max-w-none">{sessionId || 'Chưa khởi tạo'}</span>
        </div>
        <div className="flex justify-between items-center">
          <span>Frames Gửi / Nhận:</span>
          <span className="text-slate-200">{diagnostics.framesSent} / {diagnostics.framesReceived}</span>
        </div>
        <div className="flex justify-between items-center">
          <span>Trạng thái Gateway:</span>
          <span className="text-cyan-400 font-semibold uppercase">{backendStatus}</span>
        </div>
        <div className="flex justify-between items-center">
          <span>Inference Time:</span>
          <span className="text-slate-200">{diagnostics.processingMs !== null ? `${diagnostics.processingMs} ms` : 'Chờ AI'}</span>
        </div>
      </div>
    </div>
  );
};

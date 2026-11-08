import React from 'react';
import { Shield, Radio, Volume2, VolumeX, Activity, Server, AlertCircle, UserCheck } from 'lucide-react';
import type { BackendConnectionStatus } from '../types/monitor';
import { CONFIG } from '../config/env';

interface HeaderProps {
  backendStatus: BackendConnectionStatus;
  isMuted: boolean;
  toggleMute: () => void;
  showDiagnostics: boolean;
  toggleDiagnostics: () => void;
  currentView: 'driver' | 'admin';
  onViewChange: (view: 'driver' | 'admin') => void;
}

export const Header: React.FC<HeaderProps> = ({
  backendStatus,
  isMuted,
  toggleMute,
  showDiagnostics,
  toggleDiagnostics,
  currentView,
  onViewChange,
}) => {
  const getBackendBadge = () => {
    switch (backendStatus) {
      case 'connected':
        return (
          <div className="flex items-center gap-1.5 px-2 py-0.5 sm:px-2.5 sm:py-1 rounded-md text-[10px] sm:text-[11px] font-mono bg-emerald-950/70 text-emerald-400 border border-emerald-500/30 whitespace-nowrap">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
            <span>Server: Đã kết nối</span>
          </div>
        );
      case 'connecting':
        return (
          <div className="flex items-center gap-1.5 px-2 py-0.5 sm:px-2.5 sm:py-1 rounded-md text-[10px] sm:text-[11px] font-mono bg-sky-950/70 text-sky-400 border border-sky-500/30 whitespace-nowrap">
            <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-ping"></span>
            <span>Server: Đang nối...</span>
          </div>
        );
      case 'mock_demo':
        return (
          <div 
            className="flex items-center gap-1.5 px-2 py-0.5 sm:px-2.5 sm:py-1 rounded-md text-[10px] sm:text-[11px] font-mono bg-amber-950/60 text-amber-300 border border-amber-500/40 cursor-help whitespace-nowrap"
            title="Chế độ Demo Mock v0: Chưa có Backend/AI server, dữ liệu mô phỏng để test UI"
          >
            <AlertCircle className="w-3 h-3 text-amber-400 shrink-0" />
            <span>Demo Mock (Offline)</span>
          </div>
        );
      case 'error':
        return (
          <div className="flex items-center gap-1.5 px-2 py-0.5 sm:px-2.5 sm:py-1 rounded-md text-[10px] sm:text-[11px] font-mono bg-rose-950/70 text-rose-400 border border-rose-500/30 whitespace-nowrap">
            <Server className="w-3 h-3 text-rose-400 shrink-0" />
            <span>Lỗi kết nối</span>
          </div>
        );
      case 'disconnected':
      default:
        return (
          <div className="flex items-center gap-1.5 px-2 py-0.5 sm:px-2.5 sm:py-1 rounded-md text-[10px] sm:text-[11px] font-mono bg-slate-900/90 text-slate-400 border border-slate-800 whitespace-nowrap">
            <Radio className="w-3 h-3 text-slate-500 shrink-0" />
            <span>Server: Chưa kết nối</span>
          </div>
        );
    }
  };

  return (
    <header className="w-full bg-automotive-card/95 backdrop-blur-md border-b border-automotive-border sticky top-0 z-30 px-3 sm:px-6 py-2 shadow-card-glow">
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        {/* HÀNG 1: Brand Logo & View Switcher (Trên mobile gom thành 1 hàng sắc nét) */}
        <div className="flex items-center justify-between gap-2">
          {/* Logo & Tag MVP */}
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 via-sky-500/10 to-transparent border border-cyan-500/30 flex items-center justify-center text-cyan-400 shadow-automotive-cyan shrink-0">
              <Shield className="w-4 h-4 text-cyan-400" />
            </div>
            <div className="flex items-center gap-1.5 whitespace-nowrap">
              <span className="font-extrabold text-base tracking-wider text-slate-100 font-mono">
                {CONFIG.APP_NAME}
              </span>
              <span className="text-[9px] uppercase font-mono px-1.5 py-0.2 rounded bg-cyan-950 text-cyan-400 border border-cyan-800/40 font-semibold shrink-0">
                MVP v0.1
              </span>
            </div>
          </div>

          {/* View Switcher: Driver / Admin Tab (Gọn gàng không ép mép) */}
          <nav className="flex items-center bg-slate-950/90 p-0.5 sm:p-1 rounded-lg border border-slate-800 shrink-0">
            <button
              onClick={() => onViewChange('driver')}
              aria-label="Chuyển sang giao diện tài xế"
              className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold transition-all ${
                currentView === 'driver'
                  ? 'bg-cyan-500 text-slate-950 shadow-automotive-cyan'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Shield className="w-3 h-3" />
              <span>Tài xế</span>
            </button>
            <button
              onClick={() => onViewChange('admin')}
              aria-label="Chuyển sang giao diện quản trị"
              className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold transition-all ${
                currentView === 'admin'
                  ? 'bg-slate-800 text-cyan-400 border border-cyan-500/30'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <UserCheck className="w-3 h-3" />
              <span>Quản trị</span>
            </button>
          </nav>
        </div>

        {/* HÀNG 2: Telemetry status badge & Quick controls (Desktop gom chung hàng, Mobile nằm dòng 2) */}
        <div className="flex items-center justify-between sm:justify-end gap-2 pt-1 sm:pt-0 border-t border-slate-800/40 sm:border-t-0">
          {/* Server Badge (Rộng rãi trên mobile, không bao giờ bị cắt chữ) */}
          <div className="overflow-hidden">
            {getBackendBadge()}
          </div>

          {/* Mute & Diagnostics Action Buttons */}
          <div className="flex items-center gap-1.5 shrink-0">
            {/* Toggle Mute */}
            <button
              onClick={toggleMute}
              aria-label={isMuted ? 'Bật âm thanh cảnh báo' : 'Tắt âm thanh cảnh báo'}
              title={isMuted ? 'Bật âm thanh cảnh báo' : 'Tắt âm thanh cảnh báo (Mute)'}
              className={`p-1.5 sm:p-2 rounded-lg border transition-all ${
                isMuted
                  ? 'bg-rose-950/50 border-rose-500/40 text-rose-400 hover:bg-rose-900/60'
                  : 'bg-slate-900/90 border-slate-800 text-slate-300 hover:text-cyan-400 hover:border-cyan-500/30'
              }`}
            >
              {isMuted ? <VolumeX className="w-3.5 h-3.5" /> : <Volume2 className="w-3.5 h-3.5" />}
            </button>

            {/* Diagnostics toggle */}
            <button
              onClick={toggleDiagnostics}
              aria-label="Bật tắt bảng chẩn đoán hệ thống"
              title="Bật/Tắt bảng thông số kỹ thuật chẩn đoán"
              className={`p-1.5 sm:p-2 rounded-lg border transition-all ${
                showDiagnostics
                  ? 'bg-cyan-950/60 border-cyan-500/50 text-cyan-400 shadow-automotive-cyan'
                  : 'bg-slate-900/90 border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700'
              }`}
            >
              <Activity className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
};

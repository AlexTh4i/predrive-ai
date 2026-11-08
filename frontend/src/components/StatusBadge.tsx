import React from 'react';
import { 
  CheckCircle2, 
  AlertTriangle, 
  Flame, 
  AlertOctagon, 
  HelpCircle, 
  EyeOff, 
  RadioTower, 
  WifiOff 
} from 'lucide-react';
import type { DriverState, AlertLevel, UnavailableReason, BackendConnectionStatus } from '../types/monitor';

interface StatusBadgeProps {
  state: DriverState;
  alertLevel: AlertLevel;
  unavailableReason?: UnavailableReason | null;
  modelVersion?: string;
  isStreaming: boolean;
  backendStatus: BackendConnectionStatus;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  state,
  alertLevel,
  unavailableReason,
  modelVersion = 'none',
  isStreaming,
  backendStatus,
}) => {
  // 1. Trạng thái IDLE (Chưa bắt đầu)
  if (!isStreaming) {
    return (
      <div className="w-full bg-automotive-card border border-automotive-border rounded-2xl p-4 sm:p-5 shadow-card-glow">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] font-mono text-slate-400 uppercase tracking-widest">
            TRẠNG THÁI GIÁM SÁT
          </span>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-900 text-slate-400 border border-slate-800">
            CHỜ KHỞI ĐỘNG
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-slate-900 border border-slate-800 flex items-center justify-center text-slate-500 shrink-0">
            <EyeOff className="w-5 h-5" />
          </div>
          <div>
            <h4 className="text-sm font-semibold text-slate-200">Hệ thống đang ở chế độ nghỉ</h4>
            <p className="text-xs text-slate-400 mt-0.5">
              Nhấn Bắt đầu để mở camera và khởi tạo phiên giám sát.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // 2. Trạng thái MONITORING_UNAVAILABLE
  if (state === 'MONITORING_UNAVAILABLE' || unavailableReason) {
    let reasonText = 'Hệ thống tạm dừng giám sát an toàn.';
    let icon = <WifiOff className="w-5 h-5 text-amber-400" />;

    switch (unavailableReason) {
      case 'tab_hidden':
        reasonText = 'Trình duyệt bị ẩn hoặc khóa màn hình — Giám sát đã tạm dừng.';
        icon = <EyeOff className="w-5 h-5 text-amber-400" />;
        break;
      case 'camera_denied':
        reasonText = 'Quyền camera bị từ chối trong cài đặt trình duyệt.';
        icon = <EyeOff className="w-5 h-5 text-rose-400" />;
        break;
      case 'camera_stopped':
        reasonText = 'Luồng camera bị gián đoạn hoặc phần cứng ngắt kết nối.';
        icon = <EyeOff className="w-5 h-5 text-rose-400" />;
        break;
      case 'network_lost':
        reasonText = 'Mất kết nối mạng tới server AI.';
        icon = <WifiOff className="w-5 h-5 text-rose-400" />;
        break;
      case 'server_error':
        reasonText = 'Máy chủ phân tích phản hồi lỗi kết nối.';
        icon = <RadioTower className="w-5 h-5 text-rose-400" />;
        break;
      case 'stale_result':
        reasonText = 'Dữ liệu nhận về bị quá hạn trễ (stale frame).';
        icon = <AlertTriangle className="w-5 h-5 text-amber-400" />;
        break;
      default:
        break;
    }

    return (
      <div className="w-full bg-amber-950/30 border border-amber-500/40 rounded-2xl p-4 sm:p-5 shadow-card-glow">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] font-mono text-amber-400 uppercase tracking-widest">
            CẢNH BÁO HỆ THỐNG
          </span>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-500/40 font-bold">
            UNAVAILABLE
          </span>
        </div>
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-900/40 border border-amber-500/30 flex items-center justify-center shrink-0 mt-0.5">
            {icon}
          </div>
          <div>
            <h4 className="text-sm font-bold text-amber-300">GIÁM SÁT KHÔNG KHẢ DỤNG</h4>
            <p className="text-xs text-amber-200/90 mt-1 leading-relaxed">{reasonText}</p>
            <div className="text-[10px] font-mono text-slate-400 mt-2">
              Mã kỹ thuật: <span className="text-amber-400">{unavailableReason || 'generic'}</span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // 3. Trạng thái NOT_EVALUATED (Phân biệt rõ: Backend Connected vs Demo Mock Offline)
  if (state === 'NOT_EVALUATED') {
    const isBackendConnected = backendStatus === 'connected';

    return (
      <div className={`w-full bg-automotive-card border rounded-2xl p-4 sm:p-5 shadow-card-glow ${
        isBackendConnected ? 'border-sky-500/40' : 'border-amber-500/35'
      }`}>
        <div className="flex items-center justify-between mb-2">
          <span className={`text-[10px] font-mono uppercase tracking-widest ${
            isBackendConnected ? 'text-sky-400' : 'text-amber-400'
          }`}>
            TRẠNG THÁI AI
          </span>
          <span className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold ${
            isBackendConnected 
              ? 'bg-sky-950/80 text-sky-300 border border-sky-700/50' 
              : 'bg-amber-950/80 text-amber-300 border border-amber-600/40'
          }`}>
            {isBackendConnected ? 'NỐI BACKEND (CHỜ AI)' : 'DEMO MOCK CỤC BỘ'}
          </span>
        </div>
        <div className="flex items-start gap-3">
          <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 mt-0.5 ${
            isBackendConnected 
              ? 'bg-sky-950/60 border border-sky-500/40 text-sky-400 shadow-automotive-cyan' 
              : 'bg-amber-950/50 border border-amber-500/30 text-amber-400'
          }`}>
            <HelpCircle className="w-5 h-5 animate-pulse" />
          </div>
          <div>
            <h4 className="text-sm font-bold text-slate-100">
              {isBackendConnected ? 'ĐÃ KẾT NỐI MÁY CHỦ GATEWAY' : 'CHẾ ĐỘ DEMO CỤC BỘ'}
            </h4>
            <p className="text-xs text-slate-300 mt-1 leading-relaxed">
              {isBackendConnected
                ? 'Đã kết nối máy chủ FastAPI. Đang kiểm thử truyền dữ liệu khung hình (4 FPS), chưa có kết quả nhận diện AI.'
                : 'Camera đang hoạt động ở chế độ demo cục bộ. Chưa kết nối máy chủ AI và chưa có kết quả phân tích.'}
            </p>
            <div className="inline-flex items-center gap-1.5 mt-2.5 px-2 py-0.5 rounded bg-slate-900 text-[10px] font-mono text-slate-300 border border-slate-800">
              <span>Model ID:</span> <span className={isBackendConnected ? "text-sky-400" : "text-amber-400"}>{modelVersion}</span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // 4. Trạng thái NORMAL (Khi có AI thật xác nhận)
  if (state === 'NORMAL') {
    return (
      <div className="w-full bg-emerald-950/30 border border-emerald-500/40 rounded-2xl p-4 sm:p-5 shadow-automotive-normal">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] font-mono text-emerald-400 uppercase tracking-widest">
            TRẠNG THÁI TÀI XẾ
          </span>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-200 border border-emerald-500/40 font-bold">
            NORMAL
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-emerald-900/40 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shrink-0">
            <CheckCircle2 className="w-5 h-5" />
          </div>
          <div>
            <h4 className="text-sm font-bold text-emerald-300">TỈNH TÁO & TẬP TRUNG</h4>
            <p className="text-xs text-emerald-200/80 mt-0.5">
              Tài xế đang quan sát tốt và không có dấu hiệu mệt mỏi.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // 5. Trạng thái DISTRACTED
  if (state === 'DISTRACTED') {
    return (
      <div className="w-full bg-amber-950/40 border border-amber-500/50 rounded-2xl p-4 sm:p-5 shadow-card-glow">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] font-mono text-amber-400 uppercase tracking-widest">
            CẢNH BÁO CHÚ Ý
          </span>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-900 text-amber-200 border border-amber-500 font-bold">
            DISTRACTED
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-900/60 border border-amber-500/50 flex items-center justify-center text-amber-300 shrink-0">
            <AlertTriangle className="w-5 h-5 animate-bounce" />
          </div>
          <div>
            <h4 className="text-sm font-bold text-amber-300">PHÁT HIỆN MẤT TẬP TRUNG</h4>
            <p className="text-xs text-amber-200/90 mt-0.5">
              Hướng nhìn hoặc góc đầu lệch khỏi làn đường lái xe.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // 6. Trạng thái DROWSINESS_SIGNS hoặc CRITICAL
  return (
    <div className="w-full bg-rose-950/50 border-2 border-rose-500 rounded-2xl p-4 sm:p-5 shadow-automotive-danger animate-pulse">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-mono text-rose-400 uppercase tracking-widest font-bold">
          CẢNH BÁO NGUY HIỂM
        </span>
        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-rose-900 text-rose-100 border border-rose-400 font-bold uppercase">
          {alertLevel}
        </span>
      </div>
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-xl bg-rose-900/80 border border-rose-400 flex items-center justify-center text-rose-200 shrink-0 mt-0.5">
          {state === 'CRITICAL' ? <AlertOctagon className="w-6 h-6" /> : <Flame className="w-5 h-5" />}
        </div>
        <div>
          <h4 className="text-sm font-black text-rose-300">
            {state === 'CRITICAL' ? 'NGUY HIỂM: BUỒN NGỦ NGHIÊM TRỌNG' : 'CẢNH BÁO: DẤU HIỆU BUỒN NGỦ'}
          </h4>
          <p className="text-xs text-rose-200 mt-1 leading-relaxed">
            Phát hiện nhắm mắt kéo dài hoặc gục đầu. Vui lòng giảm tốc và đỗ xe an toàn!
          </p>
        </div>
      </div>
    </div>
  );
};

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { 
  CameraOff, 
  Eye, 
  EyeOff, 
  Maximize2, 
  Minimize2, 
  Video, 
  Square, 
  AlertTriangle, 
  HelpCircle, 
  CheckCircle2, 
  Clock 
} from 'lucide-react';
import type { UnavailableReason, DriverState, AlertLevel, BackendConnectionStatus } from '../types/monitor';

interface CameraPreviewProps {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  isCameraActive: boolean;
  isLoadingCamera: boolean;
  cameraError: UnavailableReason | null;
  cameraErrorMessage: string | null;
  fps: number;
  driverState: DriverState;
  alertLevel: AlertLevel;
  formattedDuration: string;
  isStreaming: boolean;
  backendStatus: BackendConnectionStatus;
  onStartClick: () => void;
  onStopClick: () => void;
}

export const CameraPreview: React.FC<CameraPreviewProps> = ({
  videoRef,
  isCameraActive,
  isLoadingCamera,
  cameraError,
  cameraErrorMessage,
  fps,
  driverState,
  alertLevel,
  formattedDuration,
  isStreaming,
  backendStatus,
  onStartClick,
  onStopClick,
}) => {
  // State chế độ Focus Mode (Phóng to tập trung)
  const [isFocused, setIsFocused] = useState<boolean>(false);
  // State bật/tắt khung hướng dẫn căn chỉnh khuôn mặt
  const [showGuide, setShowGuide] = useState<boolean>(true);
  // Tỷ lệ thực tế của nguồn video (width / height)
  const [videoAspectRatio, setVideoAspectRatio] = useState<number | null>(null);

  const containerRef = useRef<HTMLDivElement | null>(null);

  // Cập nhật tỷ lệ khung hình video thực tế
  const updateAspectRatio = useCallback(() => {
    const video = videoRef.current;
    if (video && video.videoWidth > 0 && video.videoHeight > 0) {
      setVideoAspectRatio(video.videoWidth / video.videoHeight);
    }
  }, [videoRef]);

  useEffect(() => {
    if (isCameraActive) {
      updateAspectRatio();
    }
  }, [isCameraActive, updateAspectRatio]);

  // Xử lý đóng Focus Mode
  const handleCloseFocus = useCallback(() => {
    setIsFocused(false);
  }, []);

  // Xử lý dừng giám sát từ bên trong Focus Mode
  const handleStopFromFocus = useCallback(() => {
    setIsFocused(false);
    onStopClick();
  }, [onStopClick]);

  // Lắng nghe phím Escape & khóa cuộn khi mở Focus Mode
  useEffect(() => {
    if (isFocused) {
      document.body.style.overflow = 'hidden';
      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === 'Escape') {
          handleCloseFocus();
        }
      };
      window.addEventListener('keydown', handleKeyDown);
      return () => {
        document.body.style.overflow = '';
        window.removeEventListener('keydown', handleKeyDown);
      };
    } else {
      document.body.style.overflow = '';
    }
  }, [isFocused, handleCloseFocus]);

  // Huy hiệu trạng thái tóm tắt trong Focus Mode (cập nhật theo trạng thái kết nối thực tế)
  const renderFocusStatusBadge = () => {
    if (driverState === 'CRITICAL' || driverState === 'DROWSINESS_SIGNS') {
      return (
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-rose-950/90 border border-rose-500 text-rose-200 text-xs font-bold animate-pulse">
          <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
          <span>CẢNH BÁO BUỒN NGỦ ({alertLevel})</span>
        </div>
      );
    }
    if (driverState === 'DISTRACTED') {
      return (
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-amber-950/90 border border-amber-500 text-amber-200 text-xs font-bold">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
          <span>MẤT TẬP TRUNG</span>
        </div>
      );
    }
    if (driverState === 'NORMAL') {
      return (
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-950/90 border border-emerald-500 text-emerald-200 text-xs font-bold">
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
          <span>TỈNH TÁO</span>
        </div>
      );
    }
    if (driverState === 'MONITORING_UNAVAILABLE') {
      return (
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-amber-950/90 border border-amber-500/70 text-amber-200 text-xs font-bold">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
          <span>GIÁM SÁT TẠM DỪNG</span>
        </div>
      );
    }

    // Trạng thái NOT_EVALUATED: Phân biệt rõ Backend thật vs Demo Mock
    if (backendStatus === 'connected') {
      return (
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-sky-950/80 border border-sky-500/50 text-sky-300 text-xs font-mono">
          <HelpCircle className="w-3.5 h-3.5 text-sky-400 animate-pulse" />
          <span>ĐÃ NỐI BACKEND (CHƯA CÓ AI)</span>
        </div>
      );
    }

    return (
      <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-amber-950/70 border border-amber-500/40 text-amber-300 text-xs font-mono">
        <HelpCircle className="w-3.5 h-3.5 text-amber-400" />
        <span>DEMO CỤC BỘ (CHƯA CÓ AI)</span>
      </div>
    );
  };

  // Xác định có thể hiển thị Face Guide hay không
  // Trong Focus Mode, chỉ hiển thị nếu đã xác định được videoAspectRatio chính xác, tránh hiển thị lệch ra dải đen
  const canShowGuideInFocus = isFocused ? (showGuide && videoAspectRatio !== null && videoAspectRatio > 0) : showGuide;

  return (
    <>
      <div 
        ref={containerRef}
        className={
          isFocused
            ? "fixed inset-0 z-50 bg-slate-950/98 backdrop-blur-2xl flex flex-col justify-between p-3 sm:p-5 overflow-hidden animate-in fade-in duration-200"
            : "relative w-full bg-slate-950 rounded-2xl overflow-hidden border border-automotive-border shadow-card-glow flex items-center justify-center transition-all aspect-[4/3] sm:aspect-[16/10] lg:aspect-video max-h-[460px]"
        }
      >
        {/* ============================================================== */}
        {/* TOP BAR TRONG CHẾ ĐỘ FOCUS MODE */}
        {/* ============================================================== */}
        {isFocused && (
          <div className="w-full flex items-center justify-between gap-2 pb-2.5 border-b border-slate-800/80 shrink-0">
            <div className="flex items-center gap-2 font-mono text-xs">
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-emerald-950/80 border border-emerald-500/40 text-emerald-300 font-bold">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                <span>LIVE CAMERA</span>
              </div>
              <span className="text-slate-400 hidden xs:inline">{fps > 0 ? `${fps} FPS` : '4 FPS'}</span>
            </div>

            <div className="flex items-center gap-2">
              {/* Nút bật/tắt khung căn chỉnh */}
              <button
                onClick={() => setShowGuide(prev => !prev)}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-mono transition-all ${
                  showGuide
                    ? 'bg-cyan-950/80 border-cyan-500/50 text-cyan-300'
                    : 'bg-slate-900 border-slate-800 text-slate-400'
                }`}
              >
                {showGuide ? <Eye className="w-3.5 h-3.5 text-cyan-400" /> : <EyeOff className="w-3.5 h-3.5" />}
                <span className="hidden sm:inline">Khung căn chỉnh</span>
              </button>

              {/* Nút Thu nhỏ / Đóng Focus Mode */}
              <button
                onClick={handleCloseFocus}
                aria-label="Đóng chế độ phóng to (Esc)"
                title="Thu nhỏ chế độ tập trung (Esc)"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-100 text-xs font-semibold border border-slate-600 transition-all shadow-sm"
              >
                <Minimize2 className="w-3.5 h-3.5 text-cyan-400" />
                <span>Thu nhỏ</span>
                <kbd className="hidden sm:inline-block px-1 py-0.2 rounded bg-slate-900 text-[9px] font-mono text-slate-400">Esc</kbd>
              </button>
            </div>
          </div>
        )}

        {/* ============================================================== */}
        {/* VÙNG VIDEO STREAM TRUNG TÂM */}
        {/* ============================================================== */}
        <div 
          className={
            isFocused
              ? "flex-1 min-h-0 w-full flex items-center justify-center relative overflow-hidden my-2 sm:my-3 rounded-2xl bg-black border border-slate-800/80 shadow-2xl"
              : "relative w-full h-full flex items-center justify-center overflow-hidden"
          }
        >
          {/* 
            INNER VIDEO WRAPPER:
            Khi isFocused: Khóa đúng tỷ lệ thực tế videoAspectRatio với maxWidth 100%, maxHeight 100%.
            Nhờ đó phần tử này ôm khít 100% vùng video thực tế đang hiển thị,
            không chứa bất kỳ khoảng trống đen nào bên trong!
          */}
          <div 
            className="relative flex items-center justify-center overflow-hidden"
            style={
              isFocused && videoAspectRatio
                ? {
                    aspectRatio: `${videoAspectRatio}`,
                    maxWidth: '100%',
                    maxHeight: '100%',
                    width: 'auto',
                    height: 'auto',
                  }
                : {
                    width: '100%',
                    height: '100%',
                  }
            }
          >
            {/* Thẻ Video Stream duy nhất: luôn giữ kết nối stream, không unmount */}
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              onLoadedMetadata={updateAspectRatio}
              onResize={updateAspectRatio}
              className={`w-full h-full transition-opacity duration-300 ${
                isFocused ? 'object-contain' : 'object-cover'
              } ${isCameraActive ? 'opacity-100' : 'opacity-0'}`}
            />

            {/* HUD và Khung Căn Chỉnh khi Camera đang hoạt động */}
            {isCameraActive && (
              <div className="absolute inset-0 pointer-events-none">
                {/* 4 góc target reticle thanh lịch */}
                <div className="absolute top-2.5 left-2.5 w-4 h-4 border-t border-l border-cyan-400/70 rounded-tl-sm"></div>
                <div className="absolute top-2.5 right-2.5 w-4 h-4 border-t border-r border-cyan-400/70 rounded-tr-sm"></div>
                <div className="absolute bottom-2.5 left-2.5 w-4 h-4 border-b border-l border-cyan-400/70 rounded-bl-sm"></div>
                <div className="absolute bottom-2.5 right-2.5 w-4 h-4 border-b border-r border-cyan-400/70 rounded-br-sm"></div>

                {/* 
                  Face Alignment Guide:
                  Nằm chính xác trên bề mặt video hiển thị thực tế, không chạm vào vùng đen!
                */}
                {canShowGuideInFocus && (
                  <div 
                    className="absolute inset-x-[22%] sm:inset-x-[25%] inset-y-[12%] sm:inset-y-[14%] border border-cyan-400/25 rounded-2xl sm:rounded-3xl flex flex-col justify-between p-2 sm:p-2.5 transition-all"
                  >
                    <div className="flex justify-between items-center text-[8px] sm:text-[9px] font-mono text-cyan-400/60 uppercase">
                      <span>Driver FOV</span>
                      <span>Alignment Only</span>
                    </div>
                    <div className="self-center w-6 h-6 sm:w-7 sm:h-7 border border-dashed border-cyan-400/35 rounded-full flex items-center justify-center">
                      <div className="w-1 h-1 rounded-full bg-cyan-400/70"></div>
                    </div>
                    <div className="text-center text-[8px] sm:text-[9px] font-mono text-cyan-400/50">
                      CĂN CHỈNH KHUÔN MẶT
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Top Bar bên trong Card thông thường (Chỉ hiện khi isFocused === false) */}
          {!isFocused && isCameraActive && (
            <div className="absolute top-3 left-3 right-3 flex items-center justify-between pointer-events-auto z-10">
              <div className="flex items-center gap-1.5 bg-slate-950/85 backdrop-blur-md px-2.5 py-1 rounded-md border border-slate-800 text-[11px] font-mono">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                <span className="font-semibold text-emerald-300 uppercase">
                  LIVE CAMERA
                </span>
                <span className="text-slate-600">|</span>
                <span className="text-slate-300">
                  {fps > 0 ? `${fps} FPS` : '4 FPS'}
                </span>
              </div>

              <div className="flex items-center gap-1.5">
                {/* Toggle Guide button */}
                <button
                  onClick={() => setShowGuide(prev => !prev)}
                  aria-label={showGuide ? 'Ẩn khung căn chỉnh khuôn mặt' : 'Hiện khung căn chỉnh khuôn mặt'}
                  title={showGuide ? 'Ẩn khung căn chỉnh' : 'Hiện khung căn chỉnh'}
                  className={`p-1.5 rounded-md border text-xs transition-colors backdrop-blur-md ${
                    showGuide 
                      ? 'bg-slate-900/80 border-slate-700 text-cyan-400' 
                      : 'bg-slate-950/80 border-slate-800 text-slate-500'
                  }`}
                >
                  {showGuide ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
                </button>

                {/* Expand Focus Button */}
                <button
                  onClick={() => setIsFocused(true)}
                  aria-label="Phóng to camera sang chế độ tập trung"
                  title="Chế độ tập trung (Focus Mode)"
                  className="bg-slate-900/85 backdrop-blur-md p-1.5 rounded-md border border-slate-700 text-slate-300 hover:text-cyan-400 hover:border-cyan-500/50 transition-colors shadow-sm"
                >
                  <Maximize2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )}

          {/* Trạng thái 1: Đang xin quyền camera */}
          {isLoadingCamera && (
            <div className="absolute inset-0 bg-slate-950/90 backdrop-blur-sm flex flex-col items-center justify-center p-6 text-center z-10">
              <div className="w-10 h-10 rounded-full border-2 border-cyan-500/20 border-t-cyan-400 animate-spin mb-3"></div>
              <h4 className="text-sm font-semibold text-slate-100 mb-1">
                Đang kích hoạt camera...
              </h4>
              <p className="text-xs text-slate-400 max-w-xs leading-relaxed">
                Vui lòng nhấn <span className="text-cyan-400 font-semibold">"Cho phép" (Allow)</span> khi trình duyệt yêu cầu cấp quyền webcam.
              </p>
            </div>
          )}

          {/* Trạng thái 2: Lỗi camera hoặc bị từ chối */}
          {cameraError && !isLoadingCamera && (
            <div className="absolute inset-0 bg-slate-950/95 flex flex-col items-center justify-center p-6 text-center z-10">
              <div className="w-12 h-12 rounded-xl bg-rose-950/40 border border-rose-500/30 flex items-center justify-center text-rose-400 mb-3 shadow-automotive-danger">
                <CameraOff className="w-6 h-6" />
              </div>
              <h4 className="text-sm font-bold text-rose-300 mb-1">
                Không thể truy cập Camera
              </h4>
              <p className="text-xs text-slate-300 max-w-sm mb-4 leading-relaxed">
                {cameraErrorMessage || 'Vui lòng kiểm tra quyền truy cập webcam trong cài đặt trình duyệt.'}
              </p>
              <button
                onClick={onStartClick}
                className="py-2 px-5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-600 transition-colors"
              >
                Thử lại quyền camera
              </button>
            </div>
          )}

          {/* Trạng thái 3: Màn hình chờ bắt đầu */}
          {!isCameraActive && !isLoadingCamera && !cameraError && (
            <div className="absolute inset-0 bg-gradient-to-b from-slate-900/60 to-slate-950 flex flex-col items-center justify-center p-6 text-center z-10">
              <div className="w-12 h-12 rounded-2xl bg-slate-900/90 border border-slate-800 flex items-center justify-center text-slate-400 mb-3 shadow-inner">
                <Video className="w-6 h-6 text-cyan-400/80" />
              </div>
              <h3 className="text-sm font-bold text-slate-200 mb-1">
                Camera Giám sát Chưa Bật
              </h3>
              <p className="text-xs text-slate-400 max-w-xs mb-3 leading-relaxed">
                Nhấn nút <span className="text-cyan-400 font-semibold">"BẮT ĐẦU GIÁM SÁT"</span> để mở camera và bắt đầu phiên phân tích.
              </p>
              <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[10px] font-mono text-slate-500 bg-slate-900 border border-slate-800">
                <span>Bảo mật: Hình ảnh xử lý trực tiếp trên phiên làm việc an toàn</span>
              </div>
            </div>
          )}
        </div>

        {/* ============================================================== */}
        {/* BOTTOM BAR TRONG CHẾ ĐỘ FOCUS MODE */}
        {/* ============================================================== */}
        {isFocused && (
          <div className="w-full bg-automotive-card/95 border border-slate-800 rounded-xl p-2.5 sm:p-3 flex flex-wrap items-center justify-between gap-2.5 sm:gap-4 shrink-0 shadow-card-glow">
            {/* Tóm tắt trạng thái an toàn AI */}
            <div className="flex items-center gap-2">
              {renderFocusStatusBadge()}
            </div>

            {/* Đồng hồ thời lượng phiên */}
            <div className="flex items-center gap-2 font-mono text-slate-200 text-sm sm:text-base">
              <Clock className="w-4 h-4 text-cyan-400" />
              <span className="text-xs text-slate-400 uppercase hidden xs:inline">Thời lượng:</span>
              <span className="font-bold tracking-wider">{formattedDuration}</span>
            </div>

            {/* NÚT KẾT THÚC GIÁM SÁT KHẨN CẤP TRONG FOCUS MODE */}
            {isStreaming && (
              <button
                onClick={handleStopFromFocus}
                className="flex items-center gap-2 px-4 py-2 sm:py-2.5 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs sm:text-sm shadow-automotive-danger transition-all active:scale-95 border border-rose-400/40 min-h-[44px]"
              >
                <Square className="w-4 h-4 fill-white" />
                <span>KẾT THÚC GIÁM SÁT</span>
              </button>
            )}
          </div>
        )}
      </div>
    </>
  );
};

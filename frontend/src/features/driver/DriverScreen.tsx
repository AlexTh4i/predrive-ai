import { useCallback, useEffect, useState } from 'react';
import { ParrotMascot } from '../../components/ParrotMascot';
import type { ParrotMood } from '../../components/ParrotMascot';
import { useCamera } from '../../hooks/useCamera';
import { useDriverAI } from '../../hooks/useDriverAI';
import { useBellAlarm } from '../../hooks/useBellAlarm';
import { useWakeLock } from '../../hooks/useWakeLock';

export function DriverScreen() {
  const [isMonitoring, setIsMonitoring] = useState(false);

  const {
    videoRef,
    isCameraActive,
    isLoadingCamera,
    facing,
    isFlipping,
    cameraErrorMessage,
    startCamera,
    stopCamera,
    flipCamera,
  } = useCamera();

  const { aiStatus, aiError, result, load: loadAI, start: startAI, stop: stopAI } = useDriverAI(videoRef);
  const { isMuted, toggleMute, unlock, startRing, stopRing } = useBellAlarm();

  useWakeLock(isMonitoring && isCameraActive);

  // Tải trước model MediaPipe ngay khi mở ứng dụng để bấm nút là chạy ngay
  useEffect(() => {
    void loadAI();
  }, [loadAI]);

  const state = isMonitoring && isCameraActive ? (result?.state ?? 'NORMAL') : 'NOT_EVALUATED';
  const imageQuality = result?.imageQuality ?? 'GOOD';
  const isAlarm = isMonitoring && state === 'CRITICAL';
  const isWarn =
    isMonitoring && (state === 'DROWSINESS_SIGNS' || state === 'DISTRACTED');
  const isUnavailable = isMonitoring && state === 'MONITORING_UNAVAILABLE';

  // Đồng bộ chuông báo động khi CRITICAL
  useEffect(() => {
    if (isAlarm) {
      startRing();
    } else {
      stopRing();
    }
  }, [isAlarm, startRing, stopRing]);

  const handleToggleMonitoring = useCallback(async () => {
    unlock();
    if (isMonitoring) {
      stopAI();
      stopRing();
      stopCamera();
      setIsMonitoring(false);
      return;
    }

    const [camOk, aiOk] = await Promise.all([startCamera(), loadAI()]);
    if (camOk && aiOk) {
      setIsMonitoring(true);
      startAI();
    }
  }, [isMonitoring, unlock, stopAI, stopRing, stopCamera, startCamera, loadAI, startAI]);

  const handleFlipCamera = useCallback(async () => {
    await flipCamera();
  }, [flipCamera]);

  // Xác định tâm trạng và vị trí của chú vẹt xanh
  const parrotMood: ParrotMood = isAlarm ? 'alarm' : isWarn ? 'warn' : 'peek';
  const parrotPositionClass = !isMonitoring || isUnavailable
    ? 'translate-x-24 opacity-50 rotate-[-12deg]'
    : isAlarm || isWarn
      ? 'translate-x-4 rotate-[-10deg]'
      : 'translate-x-14 rotate-[-16deg]';

  // Nội dung viên trạng thái góc trên trái
  let statusText = 'Chưa giám sát';
  let dotColor = '#8A8F93';

  if (isLoadingCamera || (isMonitoring && aiStatus === 'loading')) {
    statusText = 'Đang khởi động...';
    dotColor = '#F5A623';
  } else if (isMonitoring) {
    if (isAlarm) {
      statusText = 'Phát hiện ngủ gật';
      dotColor = '#FFFFFF';
    } else if (state === 'DROWSINESS_SIGNS') {
      statusText = 'Có dấu hiệu mỏi mắt';
      dotColor = '#F5A623';
    } else if (state === 'DISTRACTED') {
      statusText = 'Đang mất tập trung';
      dotColor = '#F5A623';
    } else if (isUnavailable) {
      statusText = imageQuality === 'TOO_DARK' ? 'Quá tối, khó nhìn' : 'Chưa thấy khuôn mặt';
      dotColor = '#8A8F93';
    } else {
      statusText = 'Tài xế tỉnh táo';
      dotColor = '#00B14F';
    }
  }

  // Nội dung thẻ thông báo ngay dưới viên trạng thái
  let bannerTitle: string | null = null;
  let bannerSub: string | null = null;
  let bannerColor = '#F5A623';

  if (cameraErrorMessage) {
    bannerTitle = 'Không mở được camera';
    bannerSub = cameraErrorMessage;
    bannerColor = '#E5372B';
  } else if (aiStatus === 'error' && aiError) {
    bannerTitle = 'Lỗi khởi tạo bộ nhận diện AI';
    bannerSub = aiError;
    bannerColor = '#E5372B';
  } else if (isAlarm) {
    bannerTitle = 'Dậy đi bác tài ơi!';
    bannerSub = 'Bạn đang nhắm mắt khi lái xe';
    bannerColor = '#E5372B';
  } else if (state === 'DROWSINESS_SIGNS') {
    bannerTitle = 'Chíu chíu! Hơi lim dim rồi đó';
    bannerSub = 'Tấp vào nghỉ chút nhé?';
    bannerColor = '#F5A623';
  } else if (state === 'DISTRACTED') {
    bannerTitle = 'Chíu chíu! Nhìn thẳng đường nhé';
    bannerSub = 'Giữ mắt hướng về phía trước';
    bannerColor = '#F5A623';
  } else if (isUnavailable) {
    bannerTitle =
      imageQuality === 'TOO_DARK'
        ? 'Hình ảnh quá tối, không giám sát được'
        : 'Chưa thấy rõ khuôn mặt trong khung hình';
    bannerSub = 'Hãy chỉnh lại góc điện thoại hoặc ánh sáng';
    bannerColor = '#8A8F93';
  }

  return (
    <div
      className={`grab-scope relative w-screen h-[100dvh] bg-[#111315] overflow-hidden select-none ${
        isAlarm ? 'danger-border' : ''
      }`}
    >
      {/* Luồng video camera toàn màn hình */}
      <div className={`absolute inset-0 z-0 ${isFlipping ? 'cam-flipping' : ''}`}>
        <video
          ref={videoRef}
          playsInline
          muted
          autoPlay
          className={`w-full h-full object-cover ${facing === 'user' ? '-scale-x-100' : ''} ${
            isCameraActive ? 'opacity-100' : 'opacity-0'
          } transition-opacity duration-300`}
        />

        {/* Khung ngắm nhẹ giữa màn hình khi chưa mở camera */}
        {!isCameraActive && (
          <div className="absolute inset-0 flex flex-col items-center justify-center px-8 text-center bg-gradient-to-b from-[#23292C] to-[#111315]">
            <div className="w-40 h-52 rounded-[72px] border-2 border-dashed border-white/20 flex items-center justify-center mb-4">
              <div className="w-24 h-32 rounded-full bg-white/5" />
            </div>
            <p className="text-sm font-medium text-white/75">
              Đặt điện thoại hướng về khuôn mặt và bấm <span className="text-[#00B14F] font-bold">Bắt đầu giám sát</span>
            </p>
          </div>
        )}
      </div>

      {/* Chú vẹt xanh phụ xe núp ở mép phải */}
      <div className="absolute right-0 top-[44%] -translate-y-1/2 z-20 flex items-center pointer-events-none">
        <div className={`w-36 h-36 smooth ${parrotPositionClass}`}>
          <ParrotMascot mood={parrotMood} />
        </div>
      </div>

      {/* Thanh trên: Viên trạng thái trắng kiểu Grab + Nhãn camera trước/sau */}
      <div
        className="absolute top-0 inset-x-0 z-30 px-4 flex items-center justify-between"
        style={{ paddingTop: 'max(1rem, env(safe-area-inset-top))' }}
      >
        <div
          className="inline-flex items-center gap-2 pl-3 pr-4 h-10 rounded-full grab-shadow smooth"
          style={{ background: isAlarm ? 'var(--grab-red)' : '#FFFFFF' }}
        >
          <span
            className="w-2.5 h-2.5 rounded-full"
            style={{ background: dotColor }}
          />
          <span
            className="text-sm font-semibold"
            style={{ color: isAlarm ? '#FFFFFF' : 'var(--grab-ink)' }}
          >
            {statusText}
          </span>
        </div>

        <div className="inline-flex items-center h-8 px-3 rounded-full bg-black/45 backdrop-blur-sm text-white text-xs font-medium">
          {facing === 'user' ? 'Camera trước' : 'Camera sau'}
        </div>
      </div>

      {/* Thẻ thông báo ngay dưới viên trạng thái (không che mặt tài xế) */}
      {bannerTitle && (
        <div
          className="absolute inset-x-4 z-30 flex justify-center pointer-events-none"
          style={{ top: 'calc(max(1rem, env(safe-area-inset-top)) + 52px)' }}
        >
          <div className="bubble-pop max-w-[320px] w-full rounded-2xl bg-white grab-shadow overflow-hidden flex">
            <div className="w-1.5 shrink-0" style={{ background: bannerColor }} />
            <div className="px-3.5 py-3">
              <div
                className="text-sm font-bold leading-snug"
                style={{ color: isAlarm ? 'var(--grab-red)' : 'var(--grab-ink)' }}
              >
                {bannerTitle}
              </div>
              {bannerSub && (
                <div className="text-xs mt-0.5" style={{ color: 'var(--grab-ink-2)' }}>
                  {bannerSub}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Cụm 3 nút điều khiển dưới đáy kiểu Grab: Âm thanh — Bắt đầu/Dừng — Đổi cam */}
      <div
        className="absolute bottom-0 inset-x-0 z-30 bg-white rounded-t-3xl grab-sheet-shadow px-4 pt-3"
        style={{ paddingBottom: 'max(1.25rem, env(safe-area-inset-bottom))' }}
      >
        <div
          className="mx-auto w-10 h-1 rounded-full mb-3"
          style={{ background: 'var(--grab-line)' }}
        />

        <div className="flex items-center gap-3">
          {/* Nút bật/tắt âm thanh */}
          <button
            type="button"
            onClick={toggleMute}
            aria-label={isMuted ? 'Bật tiếng cảnh báo' : 'Tắt tiếng cảnh báo'}
            aria-pressed={!isMuted}
            className="cursor-pointer w-14 h-14 shrink-0 rounded-full flex items-center justify-center border smooth active:scale-95"
            style={{
              borderColor: 'var(--grab-line)',
              color: isMuted ? 'var(--grab-red)' : 'var(--grab-ink)',
              background: isMuted ? '#FDECEA' : '#FFFFFF',
            }}
          >
            {isMuted ? (
              <svg
                className="w-6 h-6"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                <line x1="22" x2="16" y1="9" y2="15" />
                <line x1="16" x2="22" y1="9" y2="15" />
              </svg>
            ) : (
              <svg
                className="w-6 h-6"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
                <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
              </svg>
            )}
          </button>

          {/* Nút chính: Bắt đầu / Dừng giám sát */}
          <button
            type="button"
            onClick={() => void handleToggleMonitoring()}
            disabled={isLoadingCamera}
            className="cursor-pointer flex-1 h-14 rounded-full flex items-center justify-center gap-2 text-base font-bold smooth active:scale-[0.98] disabled:opacity-60"
            style={
              isMonitoring
                ? isAlarm
                  ? { background: 'var(--grab-red)', color: '#FFFFFF' }
                  : { background: 'var(--grab-green-tint)', color: 'var(--grab-green-pressed)' }
                : { background: 'var(--grab-green)', color: '#FFFFFF' }
            }
          >
            {isMonitoring ? (
              <>
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <rect width="16" height="16" x="4" y="4" rx="3" />
                </svg>
                <span>Dừng giám sát</span>
              </>
            ) : (
              <>
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <path d="M7 4.75a1.25 1.25 0 0 1 1.92-1.05l10.5 7.25a1.25 1.25 0 0 1 0 2.1L8.92 20.3A1.25 1.25 0 0 1 7 19.25V4.75Z" />
                </svg>
                <span>{isLoadingCamera ? 'Đang mở camera...' : 'Bắt đầu giám sát'}</span>
              </>
            )}
          </button>

          {/* Nút đổi camera trước/sau */}
          <button
            type="button"
            onClick={() => void handleFlipCamera()}
            aria-label="Đổi camera trước/sau"
            className="cursor-pointer w-14 h-14 shrink-0 rounded-full flex items-center justify-center border smooth active:scale-95"
            style={{
              borderColor: 'var(--grab-line)',
              color: 'var(--grab-ink)',
              background: '#FFFFFF',
            }}
          >
            <svg
              className="w-6 h-6"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M11 19H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5" />
              <path d="M13 5h7a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-5" />
              <circle cx="12" cy="12" r="3" />
              <path d="m18 22-3-3 3-3" />
              <path d="m6 2 3 3-3 3" />
            </svg>
          </button>
        </div>

        <div
          className="mt-2 flex justify-between px-1 text-xs"
          style={{ color: 'var(--grab-ink-2)' }}
        >
          <span className="w-14 text-center">{isMuted ? 'Đã tắt' : 'Âm thanh'}</span>
          <span className="w-14 text-center">Đổi cam</span>
        </div>
      </div>
    </div>
  );
}


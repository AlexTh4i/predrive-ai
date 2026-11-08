import { useEffect } from 'react';

/** Giữ màn hình luôn sáng khi đang giám sát (điện thoại gắn trên xe không được tự tắt màn hình) */
export function useWakeLock(active: boolean) {
  useEffect(() => {
    if (!active || !('wakeLock' in navigator)) return;

    let lock: WakeLockSentinel | null = null;

    const request = async () => {
      try {
        lock = await navigator.wakeLock.request('screen');
      } catch {
        // Thiết bị không cho phép (pin yếu, chế độ tiết kiệm pin...) — bỏ qua
      }
    };

    const onVisibility = () => {
      if (document.visibilityState === 'visible') void request();
    };

    void request();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      void lock?.release().catch(() => undefined);
    };
  }, [active]);
}


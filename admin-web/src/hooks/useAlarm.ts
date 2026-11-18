import { useCallback, useEffect, useRef, useState } from 'react';
import { eventLabels } from '../components/ui';
import type { AlertEvent } from '../types';

const baseTitle = 'PreDrive AI · Điều hành đội xe';

export function useAlarm() {
  const [enabled, setEnabled] = useState(false);
  const [error, setError] = useState('');
  const audio = useRef<AudioContext | null>(null);
  const active = useRef(false);
  const unread = useRef(0);
  useEffect(() => {
    const clearTitle = () => {
      if (document.hidden) return;
      unread.current = 0;
      document.title = baseTitle;
    };
    document.addEventListener('visibilitychange', clearTitle);
    return () => {
      document.removeEventListener('visibilitychange', clearTitle);
      if (audio.current) void audio.current.close().catch(() => undefined);
      audio.current = null;
      document.title = baseTitle;
    };
  }, []);
  async function toggle(next: boolean) {
    setError('');
    active.current = next;
    if (!next) {
      setEnabled(false);
      return;
    }
    if (
      typeof Notification !== 'undefined' &&
      Notification.permission === 'default' &&
      typeof Notification.requestPermission === 'function'
    ) {
      void Notification.requestPermission().catch(() => undefined);
    }
    try {
      audio.current ??= new AudioContext();
      await audio.current.resume();
      if (audio.current.state !== 'running') throw new Error();
      setEnabled(active.current);
    } catch {
      active.current = false;
      setEnabled(false);
      setError('Trình duyệt chưa cho phép phát âm báo.');
    }
  }
  const notify = useCallback((alert?: AlertEvent) => {
    if (document.hidden) {
      unread.current += 1;
      document.title = `(${unread.current}) Cảnh báo nguy hiểm · PreDrive AI`;
      if (
        active.current &&
        typeof Notification !== 'undefined' &&
        Notification.permission === 'granted'
      ) {
        try {
          const title = alert
            ? `NGUY HIỂM: ${alert.driverName}`
            : 'Cảnh báo nguy hiểm · PreDrive AI';
          const body = alert
            ? `${alert.vehicleName} · ${eventLabels[alert.type]} — Bấm để mở trung tâm điều hành`
            : 'Phát hiện tài xế có dấu hiệu nguy hiểm cần liên hệ ngay.';
          const notification = new Notification(title, {
            body,
            tag: alert?.id ?? 'predrive-critical',
            requireInteraction: true,
          });
          notification.onclick = () => {
            window.focus();
            notification.close();
          };
        } catch {
          // Bỏ qua nếu môi trường trình duyệt không hỗ trợ khởi tạo Notification trực tiếp
        }
      }
    }
    const context = audio.current;
    if (!active.current || context?.state !== 'running') return;
    for (const [index, frequency] of [660, 880, 660].entries()) {
      const start = context.currentTime + index * 0.17;
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.frequency.value = frequency;
      gain.gain.setValueAtTime(0.001, start);
      gain.gain.exponentialRampToValueAtTime(0.14, start + 0.025);
      gain.gain.exponentialRampToValueAtTime(0.001, start + 0.14);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start(start);
      oscillator.stop(start + 0.15);
      oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
    }
  }, []);
  return { enabled, error, toggle, notify };
}

export type Alarm = ReturnType<typeof useAlarm>;

import { useCallback, useEffect, useRef, useState } from 'react';

/** Hoạ âm lệch nhau (tỉ lệ so với tần số gốc) tạo âm sắc kim loại giống chuông */
const PARTIALS = [
  { ratio: 1, gain: 0.3 },
  { ratio: 2.0, gain: 0.16 },
  { ratio: 2.76, gain: 0.12 },
  { ratio: 4.07, gain: 0.07 },
] as const;
const BASE_FREQ = 1040;
const STRIKE_OFFSETS_SEC = [0, 0.22, 0.44] as const;
const REPEAT_MS = 1500;

/** Tiếng reng chuông cảnh báo: 3 hồi "reng-reng-reng", lặp lại cho đến khi tài xế tỉnh lại */
export function useBellAlarm() {
  const [isMuted, setIsMuted] = useState(false);
  const mutedRef = useRef(false);
  const ctxRef = useRef<AudioContext | null>(null);
  const loopRef = useRef<number | null>(null);

  const getContext = useCallback((): AudioContext | null => {
    if (!ctxRef.current) {
      const Ctor =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctor) return null;
      ctxRef.current = new Ctor();
    }
    return ctxRef.current;
  }, []);

  /** Phải gọi trong lúc xử lý cú chạm của người dùng (nút Bắt đầu) để trình duyệt cho phép phát âm thanh */
  const unlock = useCallback(() => {
    const ctx = getContext();
    if (ctx && ctx.state === 'suspended') void ctx.resume();
  }, [getContext]);

  const ringOnce = useCallback(() => {
    const ctx = getContext();
    if (!ctx || mutedRef.current) return;
    const now = ctx.currentTime;
    for (const offset of STRIKE_OFFSETS_SEC) {
      for (const partial of PARTIALS) {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = BASE_FREQ * partial.ratio;
        gain.gain.setValueAtTime(0.0001, now + offset);
        gain.gain.linearRampToValueAtTime(partial.gain, now + offset + 0.008);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.55);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(now + offset);
        osc.stop(now + offset + 0.6);
      }
    }
  }, [getContext]);

  const stopRing = useCallback(() => {
    if (loopRef.current !== null) {
      window.clearInterval(loopRef.current);
      loopRef.current = null;
    }
  }, []);

  const startRing = useCallback(() => {
    if (loopRef.current !== null) return;
    ringOnce();
    loopRef.current = window.setInterval(ringOnce, REPEAT_MS);
  }, [ringOnce]);

  const toggleMute = useCallback(() => {
    mutedRef.current = !mutedRef.current;
    setIsMuted(mutedRef.current);
  }, []);

  useEffect(() => stopRing, [stopRing]);

  return { isMuted, toggleMute, unlock, startRing, stopRing };
}


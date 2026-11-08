import { useState, useRef, useCallback } from 'react';
import type { AlertLevel } from '../types/monitor';

export function useAlertSound() {
  const [isMuted, setIsMuted] = useState<boolean>(false);
  const audioCtxRef = useRef<AudioContext | null>(null);

  const getAudioContext = useCallback(() => {
    if (!audioCtxRef.current) {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (AudioCtx) {
        audioCtxRef.current = new AudioCtx();
      }
    }
    if (audioCtxRef.current && audioCtxRef.current.state === 'suspended') {
      audioCtxRef.current.resume();
    }
    return audioCtxRef.current;
  }, []);

  const playTone = useCallback((freq: number, durationSec: number, type: OscillatorType = 'sine') => {
    if (isMuted) return;
    try {
      const ctx = getAudioContext();
      if (!ctx) return;

      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = type;
      osc.frequency.setValueAtTime(freq, ctx.currentTime);

      gain.gain.setValueAtTime(0.12, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + durationSec);

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start();
      osc.stop(ctx.currentTime + durationSec);
    } catch {
      // Ignore audio policy errors
    }
  }, [isMuted, getAudioContext]);

  const triggerAlertSound = useCallback((level: AlertLevel) => {
    if (isMuted) return;
    if (level === 'INFO') {
      playTone(587.33, 0.2, 'sine'); // Note D5
    } else if (level === 'WARNING') {
      playTone(659.25, 0.25, 'triangle'); // Note E5
      setTimeout(() => playTone(880, 0.25, 'triangle'), 150); // Note A5
    } else if (level === 'CRITICAL') {
      // 3 tiếng beep dồn dập
      playTone(987.77, 0.15, 'sawtooth');
      setTimeout(() => playTone(987.77, 0.15, 'sawtooth'), 180);
      setTimeout(() => playTone(987.77, 0.25, 'sawtooth'), 360);
    }
  }, [isMuted, playTone]);

  const toggleMute = useCallback(() => {
    setIsMuted(prev => !prev);
  }, []);

  return {
    isMuted,
    toggleMute,
    triggerAlertSound,
  };
}

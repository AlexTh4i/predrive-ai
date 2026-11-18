import { Capacitor } from '@capacitor/core';

const SERVER_URL_STORAGE_KEY = 'predrive:driver:server-url';

export function isNativeApp(): boolean {
  try {
    return Capacitor.isNativePlatform();
  } catch {
    return false;
  }
}

export function normalizeServerUrl(raw: string): string {
  let cleaned = raw.trim();
  if (!cleaned) return '';
  if (!/^https?:\/\//i.test(cleaned)) {
    cleaned = `http://${cleaned}`;
  }
  cleaned = cleaned.replace(/\/+$/, '');
  if (cleaned.endsWith('/api/v1')) {
    cleaned = cleaned.slice(0, -'/api/v1'.length);
  }
  return cleaned.replace(/\/+$/, '');
}

export function getSavedServerUrl(): string {
  if (typeof window === 'undefined') return '';
  try {
    return normalizeServerUrl(window.localStorage.getItem(SERVER_URL_STORAGE_KEY) ?? '');
  } catch {
    return '';
  }
}

export function getDefaultServerUrl(): string {
  const envUrl = import.meta.env.VITE_BACKEND_URL as string | undefined;
  if (envUrl && envUrl.trim()) {
    return normalizeServerUrl(envUrl);
  }
  if (!isNativeApp() && typeof window !== 'undefined') {
    return normalizeServerUrl(window.location.origin);
  }
  return '';
}

export function getServerUrl(): string {
  return getSavedServerUrl() || getDefaultServerUrl();
}

export function setServerUrl(raw: string): string {
  const normalized = normalizeServerUrl(raw);
  if (typeof window !== 'undefined') {
    try {
      if (normalized) {
        window.localStorage.setItem(SERVER_URL_STORAGE_KEY, normalized);
      } else {
        window.localStorage.removeItem(SERVER_URL_STORAGE_KEY);
      }
    } catch {
      // Bỏ qua nếu trình duyệt chặn storage
    }
  }
  return normalized || getDefaultServerUrl();
}

const getWsUrl = (): string => {
  if (import.meta.env.VITE_WS_URL) {
    return import.meta.env.VITE_WS_URL as string;
  }
  if (typeof window === 'undefined') return 'ws://127.0.0.1:8000/ws/monitor';
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${wsProtocol}//${window.location.host}/ws/monitor`;
};

export const CONFIG = {
  APP_NAME: 'PREDRIVE AI',
  APP_VERSION: '0.3.0',
  SLOGAN: 'Smarter Driving, Safer Journeys.',
  get BACKEND_URL() {
    return getServerUrl();
  },
  WS_URL: getWsUrl(),
  TARGET_FPS: 4,
  FRAME_INTERVAL_MS: 1000 / 4,
  FRAME_MAX_WIDTH: 480,
  FRAME_JPEG_QUALITY: 0.65,
  MAX_STALE_FRAME_MS: 3000,
  DEMO_MOCK_VERSION: 'mock-v0',
};

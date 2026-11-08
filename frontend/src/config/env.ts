/**
 * Environment configuration for PREDRIVE AI
 */

const getBackendUrl = (): string => {
  if (import.meta.env.VITE_BACKEND_URL) {
    return import.meta.env.VITE_BACKEND_URL as string;
  }
  // Dùng proxy của Vite để qua cùng domain HTTPS, tương thích iOS/Android
  return window.location.origin;
};

const getWsUrl = (): string => {
  if (import.meta.env.VITE_WS_URL) {
    return import.meta.env.VITE_WS_URL as string;
  }
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  return `${wsProtocol}//${host}/ws/monitor`;
};

export const CONFIG = {
  APP_NAME: 'PREDRIVE AI',
  APP_VERSION: '0.1.0-alpha',
  SLOGAN: 'Smarter Driving, Safer Journeys.',
  BACKEND_URL: getBackendUrl(),
  WS_URL: getWsUrl(),
  // 3-5 FPS để kiểm thử truyền tải theo hợp đồng MVP v0.1
  TARGET_FPS: 4,
  FRAME_INTERVAL_MS: 1000 / 4, // 250ms
  FRAME_MAX_WIDTH: 480,
  FRAME_JPEG_QUALITY: 0.65,
  MAX_STALE_FRAME_MS: 3000,
  DEMO_MOCK_VERSION: 'mock-v0',
};

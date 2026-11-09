import { createParser } from 'eventsource-parser';
import type { AlertEvent, LiveDriverState } from '../types';
import { ApiError, SESSION_EXPIRED } from './contract';
import type { AdminApi } from './contract';

const baseUrl = (import.meta.env.VITE_API_URL || '/api/v1').replace(/\/+$/, '');
const streamIdleMs = 75_000;
let accessToken: string | null = null;

function queryString(values: object) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) query.set(key, String(value));
  }
  return query.size ? `?${query}` : '';
}

async function fetchApi(path: string, init: RequestInit) {
  const token = accessToken;
  const headers = new Headers(init.headers);
  if (token && path !== '/auth/login') headers.set('Authorization', `Bearer ${token}`);
  if (init.body) headers.set('Content-Type', 'application/json');
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers, cache: 'no-store', redirect: 'error' });
  if (response.ok) return response;

  const body = await response.json().catch(() => null);
  if (response.status === 401 && token && token === accessToken && path !== '/auth/login') {
    window.dispatchEvent(new Event(SESSION_EXPIRED));
  }
  const fallbacks: Record<number, string> = {
    401: path === '/auth/login' ? 'Tên đăng nhập hoặc mật khẩu không đúng.' : 'Phiên đăng nhập đã hết hạn.',
    403: 'Tài khoản không có quyền thực hiện thao tác này.',
    404: 'Máy chủ không tìm thấy dữ liệu hoặc chưa hỗ trợ chức năng này.',
  };
  throw new ApiError(fallbacks[response.status] ?? `Máy chủ trả về lỗi (${response.status}).`, response.status, body?.error?.code);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const timeout = AbortSignal.timeout(12_000);
  const signal = init.signal ? AbortSignal.any([timeout, init.signal]) : timeout;
  const response = await fetchApi(path, { ...init, signal, headers: { Accept: 'application/json' } });
  return response.json() as Promise<T>;
}

export const httpApi: AdminApi = {
  setAccessToken(token) { accessToken = token; },
  login: (username, password) => request('/auth/login', {
    method: 'POST', body: JSON.stringify({ username, password }),
  }),
  me: (signal) => request('/auth/me', { signal }),
  getLive: (signal) => request('/live', { signal }),
  async stream(handlers, signal) {
    const idle = new AbortController();
    const abortSignal = AbortSignal.any([signal, idle.signal]);
    let idleTimer: ReturnType<typeof setTimeout>;
    const resetIdleTimer = () => {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => idle.abort(new Error('Luồng dữ liệu đã ngừng phản hồi.')), streamIdleMs);
    };
    resetIdleTimer();
    try {
      const response = await fetchApi('/live/stream', { signal: abortSignal, headers: { Accept: 'text/event-stream' } });
      if (!response.body || !response.headers.get('content-type')?.includes('text/event-stream')) {
        throw new Error('Máy chủ chưa cung cấp luồng dữ liệu trực tiếp.');
      }
      const parser = createParser({
        onEvent({ event, data }) {
          if (event === 'driver_state') {
            const driver = JSON.parse(data) as LiveDriverState;
            if (!driver?.driverId) throw new Error('Luồng trạng thái tài xế không hợp lệ.');
            handlers.onDriver(driver);
          }
          if (event === 'alert') {
            const alert = JSON.parse(data) as AlertEvent;
            if (!alert?.id) throw new Error('Luồng cảnh báo không hợp lệ.');
            if (!alert.delayed) handlers.onAlert(alert);
          }
        },
      });
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      try {
        handlers.onOpen();
        while (!abortSignal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          resetIdleTimer();
          parser.feed(value);
        }
      } finally {
        await reader.cancel().catch(() => undefined);
        reader.releaseLock();
      }
    } finally {
      clearTimeout(idleTimer!);
    }
  },
  getEvents: (query, signal) => request(`/events${queryString(query)}`, { signal }),
  ackEvent: (id, note) => request(`/events/${encodeURIComponent(id)}/ack`, {
    method: 'POST', body: JSON.stringify({ note }),
  }),
  getDrivers: (signal) => request('/drivers', { signal }),
  getDriver: (id, signal) => request(`/drivers/${encodeURIComponent(id)}`, { signal }),
  getDriverStats: (id, range, signal) => request(`/drivers/${encodeURIComponent(id)}/stats${queryString(range)}`, { signal }),
  getHourly: (range, signal) => request(`/stats/hourly${queryString(range)}`, { signal }),
  getRanking: (range, signal) => request(`/stats/ranking${queryString(range)}`, { signal }),
  getSystemHealth: (range, signal) => request(`/stats/system-health${queryString(range)}`, { signal }),
  getSettings: (signal) => request('/settings', { signal }),
  updateSettings: (settings) => request('/settings', { method: 'PUT', body: JSON.stringify(settings) }),
};

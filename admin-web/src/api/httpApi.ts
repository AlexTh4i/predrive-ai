import { createParser } from 'eventsource-parser';
import type { AlertEvent, LiveDriverState, LoginResult } from '../types';
import { ApiError, SESSION_EXPIRED, SESSION_REFRESHED } from './contract';
import type { AdminApi } from './contract';

const baseUrl = (import.meta.env.VITE_API_URL || '/api/v1').replace(/\/+$/, '');
const streamIdleMs = 75_000;
let accessToken: string | null = null;
let refreshToken: string | null = null;
let refreshInFlight: Promise<string | null> | null = null;

function queryString(values: object) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) query.set(key, String(value));
  }
  return query.size ? `?${query}` : '';
}

async function tryRotateToken(): Promise<string | null> {
  if (!refreshToken) return null;
  if (refreshInFlight) return refreshInFlight;

  const currentRefresh = refreshToken;
  refreshInFlight = (async () => {
    try {
      const res = await fetch(`${baseUrl}/auth/refresh`, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ refreshToken: currentRefresh }),
        cache: 'no-store',
      });
      if (!res.ok) {
        accessToken = null;
        refreshToken = null;
        return null;
      }
      const data = (await res.json()) as LoginResult;
      accessToken = data.accessToken;
      refreshToken = data.refreshToken ?? null;
      window.dispatchEvent(new CustomEvent(SESSION_REFRESHED, { detail: data }));
      return accessToken;
    } catch {
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

async function fetchApi(path: string, init: RequestInit, allowRefresh = true): Promise<Response> {
  const token = accessToken;
  const isPublicAuth = path === '/auth/login' || path === '/auth/refresh';
  const headers = new Headers(init.headers);
  if (token && !isPublicAuth) headers.set('Authorization', `Bearer ${token}`);
  if (init.body) headers.set('Content-Type', 'application/json');
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers, cache: 'no-store', redirect: 'error' });
  if (response.ok) return response;

  if (response.status === 401 && allowRefresh && !isPublicAuth && path !== '/auth/logout') {
    if (refreshToken) {
      const nextAccess = await tryRotateToken();
      if (nextAccess) {
        return fetchApi(path, init, false);
      }
    }
    if (token) {
      window.dispatchEvent(new Event(SESSION_EXPIRED));
    }
  }

  const body = await response.json().catch(() => null);
  const fallbacks: Record<number, string> = {
    401: path === '/auth/login' ? 'Tên đăng nhập hoặc mật khẩu không đúng.' : 'Phiên đăng nhập đã hết hạn.',
    403: 'Tài khoản không có quyền thực hiện thao tác này.',
    404: 'Máy chủ không tìm thấy dữ liệu hoặc chưa hỗ trợ chức năng này.',
  };
  throw new ApiError(
    body?.error?.message ?? fallbacks[response.status] ?? `Máy chủ trả về lỗi (${response.status}).`,
    response.status,
    body?.error?.code,
  );
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const timeout = AbortSignal.timeout(12_000);
  const signal = init.signal ? AbortSignal.any([timeout, init.signal]) : timeout;
  const response = await fetchApi(path, { ...init, signal, headers: { Accept: 'application/json' } });
  return response.json() as Promise<T>;
}

export const httpApi: AdminApi = {
  setAccessToken(token) { accessToken = token; },
  setRefreshToken(token) { refreshToken = token; },
  async logout(rt) {
    const tokenToRevoke = rt ?? refreshToken;
    try {
      if (accessToken) {
        await fetchApi('/auth/logout', {
          method: 'POST',
          body: JSON.stringify({ refreshToken: tokenToRevoke ?? undefined }),
        }, false);
      }
    } catch {
      // Ignore logout network error when clearing client session
    } finally {
      accessToken = null;
      refreshToken = null;
    }
  },
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
  createDriver: (payload) => request('/drivers', { method: 'POST', body: JSON.stringify(payload) }),
  createPairingCode: (payload = {}) => request('/pairing-codes', { method: 'POST', body: JSON.stringify(payload) }),
  getDriver: (id, signal) => request(`/drivers/${encodeURIComponent(id)}`, { signal }),
  getDriverStats: (id, range, signal) => request(`/drivers/${encodeURIComponent(id)}/stats${queryString(range)}`, { signal }),
  getHourly: (range, signal) => request(`/stats/hourly${queryString(range)}`, { signal }),
  getRanking: (range, signal) => request(`/stats/ranking${queryString(range)}`, { signal }),
  getSystemHealth: (range, signal) => request(`/stats/system-health${queryString(range)}`, { signal }),
  getSettings: (signal) => request('/settings', { signal }),
  updateSettings: (settings) => request('/settings', { method: 'PUT', body: JSON.stringify(settings) }),
  getLiveLocations: (signal) => request('/locations/live', { signal }),
  getLocationTrail: (query, signal) => request(`/locations/trail${queryString(query)}`, { signal }),
};

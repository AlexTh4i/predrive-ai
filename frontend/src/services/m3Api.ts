import { CapacitorHttp } from '@capacitor/core';
import { getServerUrl, isNativeApp, normalizeServerUrl } from '../config/env';
import type {
  AuthUser,
  BatchEventsResponse,
  CreateSessionResponse,
  EndSessionRequest,
  HeartbeatRequest,
  HeartbeatResponse,
  LoginResponse,
  PairResponse,
  SessionSummaryResponse,
  UpsertEventRequest,
} from '../types/m3';

export class M3ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = 'M3ApiError';
    this.status = status;
    this.code = code;
  }
}

export function isTransientSyncError(err: unknown): boolean {
  if (err instanceof M3ApiError) {
    return err.status === 0 || err.status >= 500 || err.status === 408 || err.status === 429;
  }
  return true;
}

function resolveBaseUrl(overrideUrl?: string): string {
  const base = overrideUrl !== undefined ? normalizeServerUrl(overrideUrl) : getServerUrl();
  if (!base) {
    throw new M3ApiError('Chưa nhập địa chỉ máy chủ.', 0, 'NO_SERVER_URL');
  }
  return base;
}

function parseErrorMessage(body: unknown, status: number, path: string): { message: string; code?: string } {
  if (body && typeof body === 'object' && 'error' in body) {
    const errObj = (body as { error?: { code?: string; message?: string } }).error;
    if (errObj?.message) {
      return { message: errObj.message, code: errObj.code };
    }
  }
  if (status === 401) {
    return {
      message: path === '/api/v1/auth/login' ? 'Tên đăng nhập hoặc mật khẩu không đúng.' : 'Phiên đăng nhập đã hết hạn.',
      code: 'UNAUTHORIZED',
    };
  }
  if (status === 403) {
    return { message: 'Tài khoản không có quyền thực hiện thao tác này.', code: 'FORBIDDEN' };
  }
  return { message: `Máy chủ trả về lỗi (${status}).` };
}

async function requestJson<T>(
  path: string,
  options: {
    method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
    token?: string;
    body?: unknown;
    serverUrl?: string;
    timeoutMs?: number;
  } = {},
): Promise<T> {
  const base = resolveBaseUrl(options.serverUrl);
  const url = `${base}${path}`;
  const method = options.method ?? 'GET';
  const timeoutMs = options.timeoutMs ?? 8000;

  const headers: Record<string, string> = {
    Accept: 'application/json',
  };
  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  if (isNativeApp()) {
    let response;
    try {
      response = await CapacitorHttp.request({
        url,
        method,
        headers,
        data: options.body,
        connectTimeout: timeoutMs,
        readTimeout: timeoutMs,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Không kết nối được tới máy chủ.';
      throw new M3ApiError(msg, 0, 'NETWORK_ERROR');
    }

    let parsed: unknown = response.data;
    if (typeof parsed === 'string' && parsed.trim()) {
      try {
        parsed = JSON.parse(parsed);
      } catch {
        // Giữ nguyên string nếu không phải JSON
      }
    }

    if (response.status >= 200 && response.status < 300) {
      return parsed as T;
    }

    const { message, code } = parseErrorMessage(parsed, response.status, path);
    throw new M3ApiError(message, response.status, code);
  }

  let response: Response;
  try {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      response = await fetch(url, {
        method,
        headers,
        body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
        signal: controller.signal,
        cache: 'no-store',
      });
    } finally {
      window.clearTimeout(timer);
    }
  } catch (err) {
    const msg = err instanceof Error && err.name === 'AbortError'
      ? 'Kết nối tới máy chủ bị quá thời gian.'
      : 'Không kết nối được tới máy chủ.';
    throw new M3ApiError(msg, 0, 'NETWORK_ERROR');
  }

  const parsed = await response.json().catch(() => null);
  if (response.ok) {
    return parsed as T;
  }

  const { message, code } = parseErrorMessage(parsed, response.status, path);
  throw new M3ApiError(message, response.status, code);
}

export const m3Api = {
  checkHealth(serverUrl?: string): Promise<{ status: string; service?: string }> {
    return requestJson('/health', { method: 'GET', serverUrl, timeoutMs: 4000 });
  },

  login(username: string, password: string, serverUrl?: string): Promise<LoginResponse> {
    return requestJson('/api/v1/auth/login', {
      method: 'POST',
      body: { username, password },
      serverUrl,
    });
  },

  getMe(token: string, serverUrl?: string): Promise<AuthUser> {
    return requestJson('/api/v1/auth/me', {
      method: 'GET',
      token,
      serverUrl,
    });
  },

  pairVehicle(token: string, code: string, serverUrl?: string): Promise<PairResponse> {
    return requestJson('/api/v1/auth/pair', {
      method: 'POST',
      token,
      body: { code },
      serverUrl,
    });
  },

  createSession(
    token: string,
    sessionId: string,
    startedAt: string,
    serverUrl?: string,
  ): Promise<CreateSessionResponse> {
    return requestJson('/api/v1/sessions', {
      method: 'POST',
      token,
      body: { sessionId, startedAt },
      serverUrl,
    });
  },

  postHeartbeat(
    token: string,
    sessionId: string,
    payload: HeartbeatRequest,
    serverUrl?: string,
  ): Promise<HeartbeatResponse> {
    return requestJson(`/api/v1/sessions/${encodeURIComponent(sessionId)}/heartbeat`, {
      method: 'POST',
      token,
      body: payload,
      serverUrl,
    });
  },

  postEventsBatch(
    token: string,
    sessionId: string,
    events: UpsertEventRequest[],
    serverUrl?: string,
  ): Promise<BatchEventsResponse> {
    return requestJson(`/api/v1/sessions/${encodeURIComponent(sessionId)}/events/batch`, {
      method: 'POST',
      token,
      body: { events },
      serverUrl,
    });
  },

  endSession(
    token: string,
    sessionId: string,
    payload: EndSessionRequest,
    serverUrl?: string,
  ): Promise<SessionSummaryResponse> {
    return requestJson(`/api/v1/sessions/${encodeURIComponent(sessionId)}/end`, {
      method: 'POST',
      token,
      body: payload,
      serverUrl,
    });
  },
};


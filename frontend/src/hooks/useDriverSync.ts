import { useCallback, useEffect, useRef, useState } from 'react';
import type { AnalysisResult } from '../ai/driverAnalyzer';
import { getServerUrl, setServerUrl as persistServerUrl } from '../config/env';
import { configureM3TokenRefresh, isTransientSyncError, m3Api, M3ApiError } from '../services/m3Api';
import {
  clearOfflineQueue,
  enqueueEvent,
  enqueueSessionCreate,
  enqueueSessionEnd,
  flushOfflineQueue,
  loadOfflineQueue,
} from '../services/offlineQueue';
import type { ImageQuality } from '../types/monitor';
import { DEFAULT_DRIVER_SETTINGS } from '../types/m3';
import type {
  ContractState,
  DriverAuthSession,
  DriverMode,
  DriverSettings,
  EventLevel,
  HeartbeatLocation,
  UpsertEventRequest,
} from '../types/m3';

const AUTH_STORAGE_KEY = 'predrive:driver:auth';
const MODE_STORAGE_KEY = 'predrive:driver:mode';

export type SyncStatus =
  | 'offline_demo'
  | 'unauthenticated'
  | 'ready'
  | 'syncing'
  | 'synced'
  | 'offline_queued'
  | 'auth_expired';

export type ServerHealthStatus = 'unknown' | 'checking' | 'ok' | 'error';

interface ActiveEpisode {
  eventId: string;
  startedAt: string;
  startMs: number;
  level: EventLevel;
  state: ContractState;
  riskScore: number | null;
}

interface ActiveSessionState {
  sessionId: string;
  startedAt: string;
  startMs: number;
  settings: DriverSettings;
  warningCount: number;
  criticalCount: number;
  unavailableSec: number;
  drowsyEpisode: ActiveEpisode | null;
  distractedEpisode: ActiveEpisode | null;
  longDrivingEventId: string | null;
  longDrivingLevel: EventLevel | null;
  longDrivingStartedAt: string | null;
}

function generateUuid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i += 1) {
      bytes[i] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function readStoredAuth(): DriverAuthSession | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as DriverAuthSession;
    return parsed?.accessToken && parsed?.user ? parsed : null;
  } catch {
    return null;
  }
}

function writeStoredAuth(auth: DriverAuthSession | null): void {
  if (typeof window === 'undefined') return;
  try {
    if (!auth) {
      window.localStorage.removeItem(AUTH_STORAGE_KEY);
    } else {
      window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(auth));
    }
  } catch {
    // Bỏ qua lỗi storage
  }
}

function readStoredMode(hasAuth: boolean): DriverMode {
  if (typeof window === 'undefined') return hasAuth ? 'online' : 'offline_demo';
  try {
    const raw = window.localStorage.getItem(MODE_STORAGE_KEY);
    if (raw === 'online' || raw === 'offline_demo') return raw;
  } catch {
    // Bỏ qua lỗi storage
  }
  return hasAuth ? 'online' : 'offline_demo';
}

function writeStoredMode(mode: DriverMode): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(MODE_STORAGE_KEY, mode);
  } catch {
    // Bỏ qua lỗi storage
  }
}

function readOptionalLocation(): Promise<HeartbeatLocation | null> {
  if (typeof navigator === 'undefined' || !('geolocation' in navigator)) {
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const rawSpeed = pos.coords.speed;
        const rawHeading = pos.coords.heading;
        resolve({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          speedKmh:
            typeof rawSpeed === 'number' && Number.isFinite(rawSpeed) && rawSpeed >= 0
              ? Math.round(rawSpeed * 3.6 * 10) / 10
              : null,
          headingDeg:
            typeof rawHeading === 'number' && Number.isFinite(rawHeading) && rawHeading >= 0
              ? Math.round(rawHeading * 10) / 10
              : null,
          at: new Date(pos.timestamp || Date.now()).toISOString(),
        });
      },
      () => resolve(null),
      { enableHighAccuracy: false, timeout: 3000, maximumAge: 15_000 },
    );
  });
}

function toContractState(result: AnalysisResult | null): ContractState {
  if (!result) return 'NORMAL';
  if (result.state === 'NOT_EVALUATED') return 'MONITORING_UNAVAILABLE';
  return result.state;
}

function hasDriverConsent(auth: DriverAuthSession | null): boolean {
  if (!auth) return false;
  return Boolean(auth.user.hasConsented || auth.consentedAt);
}

export function useDriverSync() {
  const initialAuth = readStoredAuth();
  const [auth, setAuth] = useState<DriverAuthSession | null>(initialAuth);
  const [mode, setModeState] = useState<DriverMode>(() => readStoredMode(Boolean(initialAuth)));
  const [serverUrl, setServerUrlState] = useState<string>(() => getServerUrl());
  const [healthStatus, setHealthStatus] = useState<ServerHealthStatus>('unknown');
  const [healthError, setHealthError] = useState<string | null>(null);
  const [pendingCount, setPendingCount] = useState<number>(() => loadOfflineQueue().length);
  const [syncStatus, setSyncStatus] = useState<SyncStatus>(() => {
    if (!initialAuth) return 'offline_demo';
    return readStoredMode(true) === 'online' ? 'ready' : 'offline_demo';
  });
  const [syncError, setSyncError] = useState<string | null>(null);
  const [settings, setSettings] = useState<DriverSettings>(DEFAULT_DRIVER_SETTINGS);

  const authRef = useRef(auth);
  const modeRef = useRef(mode);
  const serverUrlRef = useRef(serverUrl);
  const sessionRef = useRef<ActiveSessionState | null>(null);
  const latestStateRef = useRef<ContractState>('NORMAL');
  const latestQualityRef = useRef<ImageQuality>('GOOD');
  const latestLocationRef = useRef<HeartbeatLocation | null>(null);
  const tickTimerRef = useRef<number | null>(null);
  const heartbeatTimerRef = useRef<number | null>(null);
  const locationTimerRef = useRef<number | null>(null);
  const initialHeartbeatTimerRef = useRef<number | null>(null);

  useEffect(() => {
    authRef.current = auth;
    configureM3TokenRefresh(auth?.refreshToken ?? null, (rotated) => {
      const prev = authRef.current;
      if (!prev) return;
      const updated: DriverAuthSession = {
        ...prev,
        accessToken: rotated.accessToken,
        refreshToken: rotated.refreshToken ?? prev.refreshToken,
        user: rotated.user ?? prev.user,
      };
      authRef.current = updated;
      setAuth(updated);
      writeStoredAuth(updated);
    });
  }, [auth]);

  useEffect(() => {
    modeRef.current = mode;
  }, [mode]);

  useEffect(() => {
    serverUrlRef.current = serverUrl;
  }, [serverUrl]);

  const refreshPendingCount = useCallback(() => {
    setPendingCount(loadOfflineQueue().length);
  }, []);

  const setMode = useCallback((next: DriverMode) => {
    setModeState(next);
    modeRef.current = next;
    writeStoredMode(next);
    if (next === 'offline_demo') {
      setSyncStatus('offline_demo');
      setSyncError(null);
    } else {
      setSyncStatus(authRef.current ? 'ready' : 'unauthenticated');
    }
  }, []);

  const saveAndTestServer = useCallback(async (rawUrl: string): Promise<boolean> => {
    const normalized = persistServerUrl(rawUrl);
    setServerUrlState(normalized);
    serverUrlRef.current = normalized;

    if (!normalized) {
      setHealthStatus('error');
      setHealthError('Vui lòng nhập địa chỉ máy chủ (ví dụ http://192.168.1.100:8000).');
      return false;
    }

    setHealthStatus('checking');
    setHealthError(null);
    try {
      await m3Api.checkHealth(normalized);
      setHealthStatus('ok');
      return true;
    } catch (err) {
      setHealthStatus('error');
      setHealthError(err instanceof Error ? err.message : 'Không kết nối được tới máy chủ.');
      return false;
    }
  }, []);

  const flushNow = useCallback(async () => {
    const currentAuth = authRef.current;
    const url = serverUrlRef.current;
    if (!currentAuth?.accessToken || !url || !hasDriverConsent(currentAuth) || currentAuth.user.mustChangePassword) {
      refreshPendingCount();
      return;
    }
    const queue = loadOfflineQueue();
    if (queue.length === 0) {
      setPendingCount(0);
      return;
    }

    setSyncStatus('syncing');
    const result = await flushOfflineQueue(currentAuth.accessToken, url);
    setPendingCount(result.pendingCount);

    if (result.status === 'synced') {
      setSyncStatus('synced');
      setSyncError(null);
    } else if (result.status === 'auth_error') {
      setSyncStatus('auth_expired');
      setSyncError(result.errorMessage ?? 'Phiên đăng nhập hết hạn, vui lòng đăng nhập lại.');
    } else {
      setSyncStatus('offline_queued');
      setSyncError(result.errorMessage ?? 'Đang mất kết nối — đã lưu vào hàng đợi.');
    }
  }, [refreshPendingCount]);

  const login = useCallback(
    async (username: string, password: string, overrideServerUrl?: string): Promise<DriverAuthSession> => {
      const targetUrl = overrideServerUrl !== undefined ? persistServerUrl(overrideServerUrl) : serverUrlRef.current;
      if (overrideServerUrl !== undefined) {
        setServerUrlState(targetUrl);
        serverUrlRef.current = targetUrl;
      }

      const res = await m3Api.login(username.trim(), password, targetUrl);
      if (res.user.role !== 'driver') {
        throw new M3ApiError(
          'Tài khoản này không phải tài xế. Vui lòng đăng nhập tài khoản tài xế (ví dụ driver1).',
          403,
          'FORBIDDEN_ROLE',
        );
      }

      const nextAuth: DriverAuthSession = {
        accessToken: res.accessToken,
        refreshToken: res.refreshToken,
        user: res.user,
      };
      authRef.current = nextAuth;
      configureM3TokenRefresh(res.refreshToken ?? null);
      setAuth(nextAuth);
      writeStoredAuth(nextAuth);

      setModeState('online');
      modeRef.current = 'online';
      writeStoredMode('online');

      setHealthStatus('ok');
      setHealthError(null);
      setSyncStatus('ready');
      setSyncError(null);
      void flushNow();
      return nextAuth;
    },
    [flushNow],
  );

  const pairVehicle = useCallback(async (code: string): Promise<DriverAuthSession> => {
    const currentAuth = authRef.current;
    if (!currentAuth) {
      throw new M3ApiError('Cần đăng nhập tài xế trước khi ghép xe.', 401, 'UNAUTHORIZED');
    }
    const res = await m3Api.pairVehicle(currentAuth.accessToken, code.trim().toUpperCase(), serverUrlRef.current);
    const updated: DriverAuthSession = {
      ...currentAuth,
      user: { ...currentAuth.user, hasConsented: true },
      vehicleName: res.vehicleName,
      organizationName: res.organizationName,
      consentedAt: new Date().toISOString(),
      consentVersion: '2026-01',
    };
    authRef.current = updated;
    setAuth(updated);
    writeStoredAuth(updated);
    return updated;
  }, []);

  const acceptConsent = useCallback(async (locationConsent: boolean): Promise<DriverAuthSession> => {
    const currentAuth = authRef.current;
    if (!currentAuth) {
      throw new M3ApiError('Cần đăng nhập trước khi xác nhận đồng ý.', 401, 'UNAUTHORIZED');
    }
    const res = await m3Api.acceptConsent(
      currentAuth.accessToken,
      locationConsent,
      '2026-01',
      serverUrlRef.current,
    );
    const updated: DriverAuthSession = {
      ...currentAuth,
      user: { ...currentAuth.user, hasConsented: true },
      consentedAt: res.acceptedAt ?? new Date().toISOString(),
      consentVersion: res.version,
      locationConsent: res.locationConsent,
    };
    authRef.current = updated;
    setAuth(updated);
    writeStoredAuth(updated);
    setSyncError(null);
    return updated;
  }, []);

  const changePassword = useCallback(
    async (currentPassword: string, newPassword: string): Promise<DriverAuthSession> => {
      const currentAuth = authRef.current;
      if (!currentAuth) {
        throw new M3ApiError('Cần đăng nhập trước khi đổi mật khẩu.', 401, 'UNAUTHORIZED');
      }
      const updatedUser = await m3Api.changePassword(
        currentAuth.accessToken,
        currentPassword,
        newPassword,
        serverUrlRef.current,
      );
      const updated: DriverAuthSession = {
        ...currentAuth,
        user: updatedUser,
      };
      authRef.current = updated;
      setAuth(updated);
      writeStoredAuth(updated);
      setSyncError(null);
      return updated;
    },
    [],
  );

  const logout = useCallback(() => {
    const cur = authRef.current;
    if (cur?.accessToken && serverUrlRef.current) {
      void m3Api.logout(cur.accessToken, cur.refreshToken, serverUrlRef.current).catch(() => undefined);
    }
    configureM3TokenRefresh(null);
    authRef.current = null;
    setAuth(null);
    writeStoredAuth(null);
    clearOfflineQueue();
    setPendingCount(0);
    setMode('offline_demo');
  }, [setMode]);

  const clearTimers = useCallback(() => {
    if (tickTimerRef.current !== null) {
      window.clearInterval(tickTimerRef.current);
      tickTimerRef.current = null;
    }
    if (heartbeatTimerRef.current !== null) {
      window.clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
    if (locationTimerRef.current !== null) {
      window.clearInterval(locationTimerRef.current);
      locationTimerRef.current = null;
    }
    if (initialHeartbeatTimerRef.current !== null) {
      window.clearTimeout(initialHeartbeatTimerRef.current);
      initialHeartbeatTimerRef.current = null;
    }
  }, []);

  const sendLocationSample = useCallback(async () => {
    const sess = sessionRef.current;
    const currentAuth = authRef.current;
    const url = serverUrlRef.current;
    if (!sess || !currentAuth || modeRef.current !== 'online' || !url) return;
    if (!hasDriverConsent(currentAuth) || currentAuth.user.mustChangePassword) return;
    if (!sess.settings.shareLocation || currentAuth.locationConsent === false) return;

    const loc = await readOptionalLocation();
    if (!loc) return;
    latestLocationRef.current = loc;

    try {
      await m3Api.postLocations(
        currentAuth.accessToken,
        sess.sessionId,
        {
          lat: loc.lat,
          lng: loc.lng,
          speedKmh: loc.speedKmh ?? null,
          headingDeg: loc.headingDeg ?? null,
          at: loc.at ?? new Date().toISOString(),
        },
        url,
      );
    } catch {
      // Bỏ qua lỗi mạng tạm thời khi gửi tọa độ định kỳ (tiết kiệm pin)
    }
  }, []);

  const sendHeartbeat = useCallback(async () => {
    const sess = sessionRef.current;
    const currentAuth = authRef.current;
    const url = serverUrlRef.current;
    if (!sess || !currentAuth || modeRef.current !== 'online' || !url) return;
    if (!hasDriverConsent(currentAuth) || currentAuth.user.mustChangePassword) return;

    const elapsedSec = Math.max(0, Math.floor((Date.now() - sess.startMs) / 1000));
    const allowLoc = sess.settings.shareLocation && currentAuth.locationConsent !== false;
    const location = allowLoc ? await readOptionalLocation() : null;
    if (location) {
      latestLocationRef.current = location;
    }

    try {
      await m3Api.postHeartbeat(
        currentAuth.accessToken,
        sess.sessionId,
        {
          state: latestStateRef.current,
          imageQuality: latestQualityRef.current,
          continuousDrivingSec: elapsedSec,
          vehicleMoving: true,
          capturedAt: new Date().toISOString(),
          location,
        },
        url,
      );
      if (loadOfflineQueue().length > 0) {
        void flushNow();
      } else {
        setSyncStatus('synced');
        setSyncError(null);
      }
    } catch (err) {
      if (err instanceof M3ApiError && err.status === 401) {
        setSyncStatus('auth_expired');
        setSyncError(err.message);
        return;
      }
      if (err instanceof M3ApiError && err.status === 404) {
        enqueueSessionCreate(sess.sessionId, sess.startedAt);
        refreshPendingCount();
        void flushNow();
        return;
      }
      if (isTransientSyncError(err)) {
        setSyncStatus('offline_queued');
        setSyncError('Mất kết nối mạng — sự kiện mới sẽ được lưu tạm để gửi bù.');
      }
    }
  }, [flushNow, refreshPendingCount]);

  const queueAndFlushEvent = useCallback(
    (sess: ActiveSessionState, event: UpsertEventRequest) => {
      const currentAuth = authRef.current;
      if (!hasDriverConsent(currentAuth) || currentAuth?.user.mustChangePassword) {
        return;
      }
      const allowLoc = sess.settings.shareLocation && currentAuth?.locationConsent !== false;
      const loc = allowLoc ? latestLocationRef.current : null;
      const enriched: UpsertEventRequest = loc
        ? {
            ...event,
            lat: event.lat ?? loc.lat,
            lng: event.lng ?? loc.lng,
            speedKmh: event.speedKmh ?? loc.speedKmh ?? null,
            headingDeg: event.headingDeg ?? loc.headingDeg ?? null,
          }
        : event;
      enqueueEvent(sess.sessionId, sess.startedAt, enriched);
      refreshPendingCount();
      void flushNow();
    },
    [flushNow, refreshPendingCount],
  );

  const closeEpisode = useCallback(
    (sess: ActiveSessionState, episode: ActiveEpisode, nowMs: number) => {
      const durationSec = Math.max(1, Math.round((nowMs - episode.startMs) / 1000));
      queueAndFlushEvent(sess, {
        eventId: episode.eventId,
        type: 'DROWSINESS',
        level: episode.level,
        status: 'CLOSED',
        state: episode.state,
        riskScore: episode.riskScore,
        startedAt: episode.startedAt,
        durationSec,
        capturedAt: new Date(nowMs).toISOString(),
      });
    },
    [queueAndFlushEvent],
  );

  const scheduleHeartbeatInterval = useCallback(
    (intervalSec: number) => {
      if (heartbeatTimerRef.current !== null) {
        window.clearInterval(heartbeatTimerRef.current);
      }
      const ms = Math.max(5, intervalSec) * 1000;
      heartbeatTimerRef.current = window.setInterval(() => {
        void sendHeartbeat();
      }, ms);
    },
    [sendHeartbeat],
  );

  const scheduleLocationInterval = useCallback(
    (shareLocation: boolean, locationIntervalSec: number) => {
      if (locationTimerRef.current !== null) {
        window.clearInterval(locationTimerRef.current);
        locationTimerRef.current = null;
      }
      if (!shareLocation) return;
      const ms = Math.max(5, locationIntervalSec) * 1000;
      locationTimerRef.current = window.setInterval(() => {
        void sendLocationSample();
      }, ms);
    },
    [sendLocationSample],
  );

  const startSession = useCallback(async () => {
    clearTimers();
    latestStateRef.current = 'NORMAL';
    latestQualityRef.current = 'GOOD';

    const currentAuth = authRef.current;
    const url = serverUrlRef.current;
    if (
      modeRef.current !== 'online' ||
      !currentAuth?.accessToken ||
      !url ||
      !hasDriverConsent(currentAuth) ||
      currentAuth.user.mustChangePassword
    ) {
      sessionRef.current = null;
      return;
    }

    const sessionId = generateUuid();
    const nowMs = Date.now();
    const startedAt = new Date(nowMs).toISOString();

    const sess: ActiveSessionState = {
      sessionId,
      startedAt,
      startMs: nowMs,
      settings: DEFAULT_DRIVER_SETTINGS,
      warningCount: 0,
      criticalCount: 0,
      unavailableSec: 0,
      drowsyEpisode: null,
      distractedEpisode: null,
      longDrivingEventId: null,
      longDrivingLevel: null,
      longDrivingStartedAt: null,
    };
    sessionRef.current = sess;

    try {
      const res = await m3Api.createSession(currentAuth.accessToken, sessionId, startedAt, url);
      if (sessionRef.current?.sessionId === sessionId) {
        sess.settings = res.settings;
        setSettings(res.settings);
        setSyncStatus('synced');
        setSyncError(null);
      }
    } catch (err) {
      if (err instanceof M3ApiError && err.status === 401) {
        setSyncStatus('auth_expired');
        setSyncError(err.message);
      } else {
        enqueueSessionCreate(sessionId, startedAt);
        refreshPendingCount();
        setSyncStatus('offline_queued');
        setSyncError('Chưa kết nối được máy chủ — sẽ tự đồng bộ khi có mạng.');
      }
    }

    scheduleHeartbeatInterval(sess.settings.heartbeatIntervalSec);
    scheduleLocationInterval(
      sess.settings.shareLocation,
      sess.settings.locationIntervalSec ?? sess.settings.heartbeatIntervalSec,
    );
    initialHeartbeatTimerRef.current = window.setTimeout(() => {
      void sendHeartbeat();
    }, 1500);

    tickTimerRef.current = window.setInterval(() => {
      const active = sessionRef.current;
      if (!active) return;

      if (latestStateRef.current === 'MONITORING_UNAVAILABLE') {
        active.unavailableSec += 1;
      }

      const elapsedSec = Math.floor((Date.now() - active.startMs) / 1000);
      const { continuousWarnSec, continuousCriticalSec } = active.settings;

      if (elapsedSec >= continuousCriticalSec && active.longDrivingLevel !== 'CRITICAL') {
        const eventId = active.longDrivingEventId ?? generateUuid();
        const evStartedAt = active.longDrivingStartedAt ?? new Date().toISOString();
        if (active.longDrivingLevel === 'WARNING') {
          active.warningCount = Math.max(0, active.warningCount - 1);
        }
        active.criticalCount += 1;
        active.longDrivingEventId = eventId;
        active.longDrivingStartedAt = evStartedAt;
        active.longDrivingLevel = 'CRITICAL';
        queueAndFlushEvent(active, {
          eventId,
          type: 'LONG_DRIVING',
          level: 'CRITICAL',
          status: 'ESCALATED',
          state: latestStateRef.current,
          riskScore: null,
          startedAt: evStartedAt,
          durationSec: elapsedSec,
          capturedAt: new Date().toISOString(),
        });
      } else if (elapsedSec >= continuousWarnSec && active.longDrivingLevel === null) {
        const eventId = generateUuid();
        const evStartedAt = new Date().toISOString();
        active.warningCount += 1;
        active.longDrivingEventId = eventId;
        active.longDrivingStartedAt = evStartedAt;
        active.longDrivingLevel = 'WARNING';
        queueAndFlushEvent(active, {
          eventId,
          type: 'LONG_DRIVING',
          level: 'WARNING',
          status: 'OPEN',
          state: latestStateRef.current,
          riskScore: null,
          startedAt: evStartedAt,
          durationSec: elapsedSec,
          capturedAt: evStartedAt,
        });
      }
    }, 1000);
  }, [clearTimers, queueAndFlushEvent, refreshPendingCount, scheduleHeartbeatInterval, scheduleLocationInterval, sendHeartbeat]);

  const reportAIState = useCallback(
    (result: AnalysisResult | null, isMonitoring: boolean) => {
      const sess = sessionRef.current;
      if (!isMonitoring) return;

      const contractState = toContractState(result);
      latestStateRef.current = contractState;
      latestQualityRef.current = result?.imageQuality ?? 'GOOD';

      if (!sess || modeRef.current !== 'online') return;

      const nowMs = Date.now();
      const nowIso = new Date(nowMs).toISOString();

      if (contractState === 'DROWSINESS_SIGNS') {
        if (sess.distractedEpisode) {
          closeEpisode(sess, sess.distractedEpisode, nowMs);
          sess.distractedEpisode = null;
        }
        if (!sess.drowsyEpisode) {
          const eventId = generateUuid();
          sess.warningCount += 1;
          sess.drowsyEpisode = {
            eventId,
            startedAt: nowIso,
            startMs: nowMs,
            level: 'WARNING',
            state: 'DROWSINESS_SIGNS',
            riskScore: 0.8,
          };
          queueAndFlushEvent(sess, {
            eventId,
            type: 'DROWSINESS',
            level: 'WARNING',
            status: 'OPEN',
            state: 'DROWSINESS_SIGNS',
            riskScore: 0.8,
            startedAt: nowIso,
            durationSec: 1,
            capturedAt: nowIso,
          });
        }
      } else if (contractState === 'CRITICAL') {
        if (sess.distractedEpisode) {
          closeEpisode(sess, sess.distractedEpisode, nowMs);
          sess.distractedEpisode = null;
        }
        if (sess.drowsyEpisode) {
          if (sess.drowsyEpisode.level !== 'CRITICAL') {
            sess.warningCount = Math.max(0, sess.warningCount - 1);
            sess.criticalCount += 1;
            sess.drowsyEpisode.level = 'CRITICAL';
            sess.drowsyEpisode.state = 'CRITICAL';
            sess.drowsyEpisode.riskScore = 0.95;
            const durationSec = Math.max(2, Math.round((nowMs - sess.drowsyEpisode.startMs) / 1000));
            queueAndFlushEvent(sess, {
              eventId: sess.drowsyEpisode.eventId,
              type: 'DROWSINESS',
              level: 'CRITICAL',
              status: 'ESCALATED',
              state: 'CRITICAL',
              riskScore: 0.95,
              startedAt: sess.drowsyEpisode.startedAt,
              durationSec,
              capturedAt: nowIso,
            });
          }
        } else {
          const eventId = generateUuid();
          sess.criticalCount += 1;
          sess.drowsyEpisode = {
            eventId,
            startedAt: nowIso,
            startMs: nowMs,
            level: 'CRITICAL',
            state: 'CRITICAL',
            riskScore: 0.95,
          };
          queueAndFlushEvent(sess, {
            eventId,
            type: 'DROWSINESS',
            level: 'CRITICAL',
            status: 'ESCALATED',
            state: 'CRITICAL',
            riskScore: 0.95,
            startedAt: nowIso,
            durationSec: 2,
            capturedAt: nowIso,
          });
        }
      } else if (contractState === 'DISTRACTED') {
        if (sess.drowsyEpisode) {
          closeEpisode(sess, sess.drowsyEpisode, nowMs);
          sess.drowsyEpisode = null;
        }
        if (!sess.distractedEpisode) {
          const eventId = generateUuid();
          sess.warningCount += 1;
          sess.distractedEpisode = {
            eventId,
            startedAt: nowIso,
            startMs: nowMs,
            level: 'WARNING',
            state: 'DISTRACTED',
            riskScore: 0.65,
          };
          queueAndFlushEvent(sess, {
            eventId,
            type: 'DROWSINESS',
            level: 'WARNING',
            status: 'OPEN',
            state: 'DISTRACTED',
            riskScore: 0.65,
            startedAt: nowIso,
            durationSec: 2,
            capturedAt: nowIso,
          });
        }
      } else {
        if (sess.drowsyEpisode) {
          closeEpisode(sess, sess.drowsyEpisode, nowMs);
          sess.drowsyEpisode = null;
        }
        if (sess.distractedEpisode) {
          closeEpisode(sess, sess.distractedEpisode, nowMs);
          sess.distractedEpisode = null;
        }
      }
    },
    [closeEpisode, queueAndFlushEvent],
  );

  const stopSession = useCallback(async () => {
    clearTimers();
    const sess = sessionRef.current;
    sessionRef.current = null;
    if (!sess) return;

    const nowMs = Date.now();
    if (sess.drowsyEpisode) {
      closeEpisode(sess, sess.drowsyEpisode, nowMs);
      sess.drowsyEpisode = null;
    }
    if (sess.distractedEpisode) {
      closeEpisode(sess, sess.distractedEpisode, nowMs);
      sess.distractedEpisode = null;
    }

    const totalDrivingSec = Math.max(0, Math.floor((nowMs - sess.startMs) / 1000));
    enqueueSessionEnd(sess.sessionId, sess.startedAt, {
      endedAt: new Date(nowMs).toISOString(),
      summary: {
        totalDrivingSec,
        warningCount: sess.warningCount,
        criticalCount: sess.criticalCount,
        unavailableSec: sess.unavailableSec,
      },
    });
    refreshPendingCount();
    await flushNow();
  }, [clearTimers, closeEpisode, flushNow, refreshPendingCount]);

  // Kiểm tra token khi mở app và tự động flush hàng đợi offline khi có mạng lại
  useEffect(() => {
    const currentAuth = authRef.current;
    const url = serverUrlRef.current;
    if (currentAuth?.accessToken && url && modeRef.current === 'online') {
      void m3Api
        .getMe(currentAuth.accessToken, url)
        .then(() => {
          setHealthStatus('ok');
          void flushNow();
        })
        .catch((err) => {
          if (err instanceof M3ApiError && err.status === 401) {
            setSyncStatus('auth_expired');
            setSyncError('Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại.');
          }
        });
    }

    const handleOnline = () => {
      if (modeRef.current === 'online' && authRef.current?.accessToken) {
        void flushNow();
      }
    };
    window.addEventListener('online', handleOnline);

    const retryTimer = window.setInterval(() => {
      if (
        modeRef.current === 'online' &&
        authRef.current?.accessToken &&
        loadOfflineQueue().length > 0 &&
        (typeof navigator === 'undefined' || navigator.onLine !== false)
      ) {
        void flushNow();
      }
    }, 5000);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.clearInterval(retryTimer);
      clearTimers();
    };
  }, [clearTimers, flushNow]);

  return {
    auth,
    mode,
    setMode,
    serverUrl,
    healthStatus,
    healthError,
    pendingCount,
    syncStatus,
    syncError,
    settings,
    saveAndTestServer,
    login,
    pairVehicle,
    acceptConsent,
    changePassword,
    logout,
    flushNow,
    startSession,
    reportAIState,
    stopSession,
  };
}


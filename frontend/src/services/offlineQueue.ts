import { isTransientSyncError, m3Api, M3ApiError } from './m3Api';
import type { EndSessionRequest, UpsertEventRequest } from '../types/m3';

const QUEUE_STORAGE_KEY = 'predrive:driver:offline-queue';
const MAX_QUEUE_ITEMS = 500;
const BATCH_SIZE = 25;

export type OfflineQueueItem =
  | {
      kind: 'create_session';
      sessionId: string;
      startedAt: string;
    }
  | {
      kind: 'event';
      sessionId: string;
      sessionStartedAt: string;
      event: UpsertEventRequest;
    }
  | {
      kind: 'end_session';
      sessionId: string;
      sessionStartedAt: string;
      payload: EndSessionRequest;
    };

const LEVEL_RANK: Record<string, number> = { WARNING: 1, CRITICAL: 2 };
const STATUS_RANK: Record<string, number> = { OPEN: 1, ESCALATED: 2, CLOSED: 3 };

function mergeEvent(existing: UpsertEventRequest, incoming: UpsertEventRequest): UpsertEventRequest {
  const nextLevel =
    (LEVEL_RANK[incoming.level] ?? 1) > (LEVEL_RANK[existing.level] ?? 1)
      ? incoming.level
      : existing.level;
  const nextStatus =
    (STATUS_RANK[incoming.status] ?? 1) > (STATUS_RANK[existing.status] ?? 1)
      ? incoming.status
      : existing.status;
  const nextStarted =
    Date.parse(incoming.startedAt) < Date.parse(existing.startedAt)
      ? incoming.startedAt
      : existing.startedAt;
  const nextCaptured =
    Date.parse(incoming.capturedAt) >= Date.parse(existing.capturedAt)
      ? incoming.capturedAt
      : existing.capturedAt;

  let nextRisk = existing.riskScore;
  if (incoming.riskScore !== null) {
    nextRisk = existing.riskScore === null ? incoming.riskScore : Math.max(existing.riskScore, incoming.riskScore);
  }

  return {
    ...existing,
    level: nextLevel,
    status: nextStatus,
    state: nextLevel === 'CRITICAL' ? 'CRITICAL' : incoming.state,
    durationSec: Math.max(existing.durationSec, incoming.durationSec),
    startedAt: nextStarted,
    capturedAt: nextCaptured,
    riskScore: nextRisk,
  };
}

export function loadOfflineQueue(): OfflineQueueItem[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(QUEUE_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as OfflineQueueItem[]) : [];
  } catch {
    return [];
  }
}

export function saveOfflineQueue(items: OfflineQueueItem[]): void {
  if (typeof window === 'undefined') return;
  try {
    const trimmed = items.length > MAX_QUEUE_ITEMS ? items.slice(-MAX_QUEUE_ITEMS) : items;
    if (trimmed.length === 0) {
      window.localStorage.removeItem(QUEUE_STORAGE_KEY);
    } else {
      window.localStorage.setItem(QUEUE_STORAGE_KEY, JSON.stringify(trimmed));
    }
  } catch {
    // Bỏ qua nếu storage đầy
  }
}

export function clearOfflineQueue(): void {
  saveOfflineQueue([]);
}

export function enqueueSessionCreate(sessionId: string, startedAt: string): OfflineQueueItem[] {
  const items = loadOfflineQueue();
  const alreadyExists = items.some(
    (item) => item.kind === 'create_session' && item.sessionId === sessionId,
  );
  if (!alreadyExists) {
    items.push({ kind: 'create_session', sessionId, startedAt });
    saveOfflineQueue(items);
  }
  return items;
}

export function enqueueEvent(
  sessionId: string,
  sessionStartedAt: string,
  event: UpsertEventRequest,
): OfflineQueueItem[] {
  const items = loadOfflineQueue();
  const idx = items.findIndex(
    (item) =>
      item.kind === 'event' &&
      item.sessionId === sessionId &&
      item.event.eventId === event.eventId,
  );
  if (idx >= 0) {
    const existing = items[idx];
    if (existing.kind === 'event') {
      items[idx] = {
        ...existing,
        event: mergeEvent(existing.event, event),
      };
    }
  } else {
    items.push({ kind: 'event', sessionId, sessionStartedAt, event });
  }
  saveOfflineQueue(items);
  return items;
}

export function enqueueSessionEnd(
  sessionId: string,
  sessionStartedAt: string,
  payload: EndSessionRequest,
): OfflineQueueItem[] {
  const items = loadOfflineQueue();
  const idx = items.findIndex(
    (item) => item.kind === 'end_session' && item.sessionId === sessionId,
  );
  if (idx >= 0) {
    items[idx] = { kind: 'end_session', sessionId, sessionStartedAt, payload };
  } else {
    items.push({ kind: 'end_session', sessionId, sessionStartedAt, payload });
  }
  saveOfflineQueue(items);
  return items;
}

export interface FlushResult {
  status: 'synced' | 'offline' | 'auth_error';
  sentCount: number;
  pendingCount: number;
  errorMessage?: string;
}

let activeFlushPromise: Promise<FlushResult> | null = null;

async function ensureSessionAndSendBatch(
  token: string,
  sessionId: string,
  sessionStartedAt: string,
  events: UpsertEventRequest[],
  serverUrl?: string,
): Promise<void> {
  try {
    await m3Api.postEventsBatch(token, sessionId, events, serverUrl);
  } catch (err) {
    if (err instanceof M3ApiError && err.status === 404) {
      await m3Api.createSession(token, sessionId, sessionStartedAt, serverUrl);
      await m3Api.postEventsBatch(token, sessionId, events, serverUrl);
      return;
    }
    throw err;
  }
}

async function ensureSessionAndEnd(
  token: string,
  sessionId: string,
  sessionStartedAt: string,
  payload: EndSessionRequest,
  serverUrl?: string,
): Promise<void> {
  try {
    await m3Api.endSession(token, sessionId, payload, serverUrl);
  } catch (err) {
    if (err instanceof M3ApiError && err.status === 404) {
      await m3Api.createSession(token, sessionId, sessionStartedAt, serverUrl);
      await m3Api.endSession(token, sessionId, payload, serverUrl);
      return;
    }
    throw err;
  }
}

export function flushOfflineQueue(token: string, serverUrl?: string): Promise<FlushResult> {
  if (activeFlushPromise) {
    return activeFlushPromise;
  }

  activeFlushPromise = (async (): Promise<FlushResult> => {
    let sentCount = 0;

    while (true) {
      const queue = loadOfflineQueue();
      if (queue.length === 0) {
        return { status: 'synced', sentCount, pendingCount: 0 };
      }

      if (typeof navigator !== 'undefined' && navigator.onLine === false) {
        return {
          status: 'offline',
          sentCount,
          pendingCount: queue.length,
          errorMessage: 'Thiết bị đang ngoại tuyến.',
        };
      }

      const head = queue[0];
      try {
        if (head.kind === 'create_session') {
          await m3Api.createSession(token, head.sessionId, head.startedAt, serverUrl);
          const remaining = loadOfflineQueue();
          if (remaining[0]?.kind === 'create_session' && remaining[0].sessionId === head.sessionId) {
            remaining.shift();
            saveOfflineQueue(remaining);
          }
          sentCount += 1;
          continue;
        }

        if (head.kind === 'event') {
          const batchItems: UpsertEventRequest[] = [];
          for (const item of queue) {
            if (item.kind === 'event' && item.sessionId === head.sessionId) {
              batchItems.push(item.event);
              if (batchItems.length >= BATCH_SIZE) break;
            } else {
              break;
            }
          }

          await ensureSessionAndSendBatch(
            token,
            head.sessionId,
            head.sessionStartedAt,
            batchItems,
            serverUrl,
          );

          // Chỉ xóa những event đã gửi và chưa bị cập nhật thêm trong lúc đang gửi
          const currentQueue = loadOfflineQueue();
          const sentMap = new Map(batchItems.map((ev) => [ev.eventId, ev]));
          const nextQueue = currentQueue.filter((item) => {
            if (item.kind !== 'event' || item.sessionId !== head.sessionId) return true;
            const sentEv = sentMap.get(item.event.eventId);
            if (!sentEv) return true;
            // Nếu item trong queue có cập nhật mới hơn lúc bắt đầu gửi batch thì giữ lại để gửi tiếp
            return (
              item.event.status !== sentEv.status ||
              item.event.level !== sentEv.level ||
              item.event.durationSec > sentEv.durationSec ||
              Date.parse(item.event.capturedAt) > Date.parse(sentEv.capturedAt)
            );
          });
          saveOfflineQueue(nextQueue);
          sentCount += batchItems.length;
          continue;
        }

        if (head.kind === 'end_session') {
          await ensureSessionAndEnd(
            token,
            head.sessionId,
            head.sessionStartedAt,
            head.payload,
            serverUrl,
          );
          const currentQueue = loadOfflineQueue();
          if (currentQueue[0]?.kind === 'end_session' && currentQueue[0].sessionId === head.sessionId) {
            currentQueue.shift();
            saveOfflineQueue(currentQueue);
          }
          sentCount += 1;
        }
      } catch (err) {
        const pendingCount = loadOfflineQueue().length;
        if (err instanceof M3ApiError && err.status === 401) {
          return {
            status: 'auth_error',
            sentCount,
            pendingCount,
            errorMessage: err.message,
          };
        }
        if (isTransientSyncError(err)) {
          return {
            status: 'offline',
            sentCount,
            pendingCount,
            errorMessage: err instanceof Error ? err.message : 'Lỗi kết nối máy chủ.',
          };
        }
        // Lỗi dữ liệu không thể retry (400/403/409/422): bỏ phần tử lỗi để không kẹt hàng đợi
        const currentQueue = loadOfflineQueue();
        currentQueue.shift();
        saveOfflineQueue(currentQueue);
      }
    }
  })().finally(() => {
    activeFlushPromise = null;
  });

  return activeFlushPromise;
}

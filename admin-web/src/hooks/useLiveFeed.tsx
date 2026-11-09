import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from '../api';
import { ApiError, defaultSettings } from '../api/contract';
import { dayKey, localDateTime, shiftDay } from '../lib/format';
import type { AlertEvent, DriverState, LiveDriverState, Settings } from '../types';

export type Connection = 'connecting' | 'live' | 'reconnecting';
export type DisplayState = DriverState | 'UNCONFIRMED';
const recentLimit = 5;
const eligible = (event: AlertEvent) => !event.delayed && event.type !== 'REST_CLAIM_REJECTED';

function recentAlerts(items: AlertEvent[]) {
  return items.filter(eligible).sort((a, b) => Date.parse(b.capturedAt) - Date.parse(a.capturedAt)).slice(0, recentLimit);
}

function mergeAlert(map: Map<string, AlertEvent>, incoming: AlertEvent) {
  const previous = map.get(incoming.id);
  if (previous?.ackAt && !incoming.ackAt) {
    map.set(incoming.id, { ...incoming, ackAt: previous.ackAt, ackBy: previous.ackBy, note: previous.note });
  } else {
    map.set(incoming.id, incoming);
  }
}

async function getRecent(signal: AbortSignal) {
  const result: AlertEvent[] = [];
  const pageSize = 25;
  const from = localDateTime(shiftDay(dayKey(), -6));
  for (let page = 1; ; page += 1) {
    const { items, total } = await api.getEvents({ from, page, pageSize }, signal);
    result.push(...items.filter(eligible));
    if (result.length >= recentLimit || page * pageSize >= total || items.length === 0) break;
  }
  return recentAlerts(result);
}

export function displayState(driver: LiveDriverState, connection: Connection, now: number, heartbeatIntervalSec: number): DisplayState {
  if (connection !== 'live') return 'UNCONFIRMED';
  if (driver.state === 'OFFLINE' || driver.state === 'DISCONNECTED') return driver.state;
  const heartbeat = driver.lastHeartbeatAt ? Date.parse(driver.lastHeartbeatAt) : NaN;
  const fresh = Number.isFinite(heartbeat) && now - heartbeat <= heartbeatIntervalSec * 2000 && heartbeat - now < 60_000;
  return driver.sessionId && fresh ? driver.state : 'UNCONFIRMED';
}

function newerDriver(previous: LiveDriverState | undefined, next: LiveDriverState) {
  if (!previous || previous.sessionId !== next.sessionId || !previous.lastHeartbeatAt || !next.lastHeartbeatAt) return next;
  return Date.parse(previous.lastHeartbeatAt) > Date.parse(next.lastHeartbeatAt) ? previous : next;
}

export function useLiveFeed(onCritical: () => void) {
  const [connection, setConnection] = useState<Connection>('connecting');
  const [drivers, setDrivers] = useState<LiveDriverState[]>([]);
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const [settings, setSettings] = useState<Settings>(defaultSettings);
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const acks = useRef(new Map<string, AlertEvent>());
  const seenCritical = useRef(new Set<string>());
  const notify = useRef(onCritical);
  useEffect(() => { notify.current = onCritical; }, [onCritical]);

  useEffect(() => {
    let closed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let current: AbortController | undefined;
    const stop = () => {
      clearTimeout(timer);
      current?.abort();
    };
    const run = () => {
      if (closed || !navigator.onLine) {
        setConnection('reconnecting');
        return;
      }
      const controller = new AbortController();
      current = controller;
      const signal = controller.signal;
      let ready = false;
      const pendingDrivers = new Map<string, LiveDriverState>();
      const pendingAlerts = new Map<string, AlertEvent>();

      const publishAlert = (alert: AlertEvent) => {
        if (!eligible(alert)) return;
        if (alert.level === 'CRITICAL' && !alert.ackAt && !acks.current.has(alert.id) && !seenCritical.current.has(alert.id)) {
          seenCritical.current.add(alert.id);
          notify.current();
        }
        setAlerts((previous) => {
          const map = new Map(previous.map((item) => [item.id, item]));
          const ack = acks.current.get(alert.id);
          if (ack) mergeAlert(map, ack);
          mergeAlert(map, alert);
          return recentAlerts([...map.values()]);
        });
      };

      const schedule = (error?: unknown) => {
        if (closed || signal.aborted) return;
        controller.abort();
        setConnection('reconnecting');
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) return;
        if (navigator.onLine) {
          timer = setTimeout(run, Math.min(1000 * 2 ** attempt, 15_000));
          attempt += 1;
        }
      };

      api.stream({
        onOpen() {
          Promise.all([api.getLive(signal), getRecent(signal), api.getSettings(signal)]).then(([snapshot, recent, config]) => {
            if (signal.aborted) return;
            const map = new Map(snapshot.map((driver) => [driver.driverId, driver]));
            for (const driver of pendingDrivers.values()) map.set(driver.driverId, newerDriver(map.get(driver.driverId), driver));
            const alertsById = new Map(recent.map((alert) => [alert.id, alert]));
            for (const alert of recent) {
              const ack = acks.current.get(alert.id);
              if (ack) mergeAlert(alertsById, ack);
              if (alert.level === 'CRITICAL' && !pendingAlerts.has(alert.id)) seenCritical.current.add(alert.id);
            }
            setDrivers([...map.values()]);
            setAlerts(recentAlerts([...alertsById.values()]));
            setSettings(config);
            setLastSync(Date.now());
            ready = true;
            attempt = 0;
            setConnection('live');
            for (const alert of pendingAlerts.values()) publishAlert(alert);
            pendingAlerts.clear();
            pendingDrivers.clear();
          }).catch(schedule);
        },
        onDriver(driver) {
          if (signal.aborted) return;
          if (!ready) {
            pendingDrivers.set(driver.driverId, newerDriver(pendingDrivers.get(driver.driverId), driver));
            return;
          }
          setDrivers((previous) => {
            const index = previous.findIndex((item) => item.driverId === driver.driverId);
            if (index < 0) return [...previous, driver];
            return previous.map((item, i) => i === index ? newerDriver(item, driver) : item);
          });
          setLastSync(Date.now());
        },
        onAlert(alert) {
          if (signal.aborted) return;
          if (ready) publishAlert(alert);
          else mergeAlert(pendingAlerts, alert);
        },
      }, signal).then(() => schedule(), schedule);
    };
    const offline = () => {
      stop();
      setConnection('reconnecting');
    };
    const online = () => {
      stop();
      attempt = 0;
      run();
    };
    window.addEventListener('offline', offline);
    window.addEventListener('online', online);
    run();
    return () => {
      closed = true;
      stop();
      window.removeEventListener('offline', offline);
      window.removeEventListener('online', online);
    };
  }, [retryKey]);

  const acknowledge = useCallback(async (id: string, note: string) => {
    const updated = await api.ackEvent(id, note.trim());
    acks.current.set(id, updated);
    setAlerts((items) => items.map((item) => item.id === id ? updated : item));
    return updated;
  }, []);
  const applySettings = useCallback((value: Settings) => setSettings(value), []);
  const retry = () => {
    setConnection('reconnecting');
    setRetryKey((key) => key + 1);
  };

  return { drivers, alerts, connection, lastSync, settings, applySettings, acknowledge, retry };
}

const FeedContext = createContext<ReturnType<typeof useLiveFeed> | null>(null);

export function LiveFeedProvider({ children, onCritical }: { children: ReactNode; onCritical: () => void }) {
  const feed = useLiveFeed(onCritical);
  return <FeedContext.Provider value={feed}>{children}</FeedContext.Provider>;
}

export function useFeed() {
  const feed = useContext(FeedContext);
  if (!feed) throw new Error('Thiếu LiveFeedProvider');
  return feed;
}

import { dayKey, dayOf, hourOf } from '../lib/format';
import { readStorage, writeStorage } from '../lib/storage';
import type { AlertEvent, DateRange, DriverState, HourlyStats, LiveDriverState, Session, User } from '../types';
import { ApiError, defaultSettings } from './contract';
import type { AdminApi } from './contract';
import { currentSessionId, demoDrivers, demoEvent, demoLive, seedDemo } from './demoData';
import { DEMO_PASSWORD } from './demoCredentials';

const DEMO_USERS = {
  manager: { id: 'demo-manager', role: 'manager', fullName: 'Nguyễn Minh Khanh', organizationId: 'demo' },
  dispatcher: { id: 'demo-dispatcher', role: 'dispatcher', fullName: 'Huỳnh Tấn Gia Huy', organizationId: 'demo' },
  driver: { id: 'demo-driver', role: 'driver', fullName: 'Nguyễn Văn Minh', organizationId: 'demo' },
} satisfies Record<string, User>;

const storePrefix = 'predrive-demo-v1:';
const start = Date.now();
const live = demoLive(start);
const seeded = seedDemo(start, live);
const saved = readStorage<AlertEvent[]>(storePrefix + 'events', [], 'sessionStorage');
const events = new Map(seeded.events.map((event) => [event.id, event]));
for (const event of saved) {
  const seed = events.get(event.id);
  if (seed) events.set(event.id, { ...seed, ackBy: event.ackBy, ackAt: event.ackAt, note: event.note });
  else if (event.id.startsWith('realtime-') && Date.parse(event.capturedAt) > start - 28 * 86_400_000) {
    events.set(event.id, event);
  }
}
let settings = { ...defaultSettings, ...readStorage(storePrefix + 'settings', {}, 'sessionStorage') };
let token: string | null = null;
let tick = 0;
const bootId = Math.random().toString(36).slice(2);

function user() {
  const found = Object.entries(DEMO_USERS).find(([name]) => token === `demo:${name}`)?.[1];
  if (!found) throw new ApiError('Phiên đăng nhập đã hết hạn.', 401);
  return found;
}

function operator() {
  const current = user();
  if (current.role === 'driver') throw new ApiError('Tài khoản không có quyền điều hành.', 403);
  return current;
}

async function pause(signal?: AbortSignal) {
  await new Promise((resolve) => setTimeout(resolve, 120));
  signal?.throwIfAborted();
}

function inRange(value: string, { from, to }: DateRange) {
  return (!from || value >= from) && (!to || value <= to);
}

function getDriver(id: string) {
  const driver = demoDrivers.find((entry) => entry.id === id);
  if (!driver) throw new ApiError('Không tìm thấy tài xế.', 404);
  return driver;
}

function storeEvents() {
  writeStorage(storePrefix + 'events', [...events.values()].filter((event) => event.ackAt || event.id.startsWith('realtime-')), 'sessionStorage');
}

function drowsyToday(driverId: string, now: number) {
  const today = dayKey(now);
  return [...events.values()].filter((event) =>
    event.driverId === driverId && event.type === 'DROWSINESS' && dayOf(event.capturedAt) === today).length;
}

function getActiveSession(driver: LiveDriverState): Session[] {
  if (!driver.sessionId) return [];
  const currentEvents = [...events.values()].filter((event) => event.sessionId === driver.sessionId);
  return [{
    id: driver.sessionId, driverId: driver.driverId,
    startedAt: new Date(Date.now() - driver.totalDrivingSec * 1000).toISOString(),
    endedAt: null, totalDrivingSec: driver.totalDrivingSec,
    warningCount: currentEvents.filter((event) => event.level === 'WARNING').length,
    criticalCount: currentEvents.filter((event) => event.level === 'CRITICAL').length,
  }];
}

function driverStats(id: string, range: DateRange) {
  const driver = live.find((entry) => entry.driverId === id)!;
  const driverEvents = [...events.values()].filter((event) => event.driverId === id && inRange(event.capturedAt, range));
  const sessions = [...seeded.sessions.filter((session) => session.driverId === id), ...getActiveSession(driver)];
  const totalDrivingSec = sessions.reduce((sum, session) => {
    const start = Math.max(Date.parse(session.startedAt), range.from ? Date.parse(range.from) : -Infinity);
    const end = Math.min(session.endedAt ? Date.parse(session.endedAt) : Date.now(), range.to ? Date.parse(range.to) : Infinity);
    return sum + Math.min(session.totalDrivingSec, Math.max(0, Math.floor((end - start) / 1000)));
  }, 0);
  const hourly = Array.from({ length: 24 }, (_, hour) => ({ hour, count: 0 }));
  for (const event of driverEvents) hourly[hourOf(event.capturedAt)].count += 1;
  return {
    totalDrivingSec, alertCount: driverEvents.length,
    alertsPerDrivingHour: totalDrivingSec ? driverEvents.length * 3600 / totalDrivingSec : 0,
    hourly,
  };
}

function simulate(handlers: Parameters<AdminApi['stream']>[0]) {
  tick += 1;
  const now = Date.now();
  const at = new Date(now).toISOString();
  const phase = tick % 10;
  const focus = phase === 3 || phase === 4 ? 2 : phase === 7 || phase === 8 ? 3 : -1;
  for (let i = 0; i < live.length; i += 1) {
    const previous = live[i];
    let state: DriverState = i === 5 ? 'OFFLINE' : i === 4 && phase < 6 ? 'DISCONNECTED' : 'NORMAL';
    if (tick < 3 && i < 2) state = previous.state;
    if (i === focus) state = phase === 4 || phase === 8 ? 'CRITICAL' : 'DROWSINESS_SIGNS';
    const active = state !== 'OFFLINE' && state !== 'DISCONNECTED';
    const next: LiveDriverState = {
      ...previous, state,
      sessionId: state === 'OFFLINE' ? null : currentSessionId(previous.driverId, dayKey(now)),
      continuousDrivingSec: previous.continuousDrivingSec + (active ? 4 : 0),
      totalDrivingSec: previous.totalDrivingSec + (active ? 4 : 0),
      lastHeartbeatAt: active ? at : previous.lastHeartbeatAt,
    };
    const wasOverLimit = previous.continuousDrivingSec >= settings.continuousWarnSec;
    const crossedLimit = !wasOverLimit && next.continuousDrivingSec >= settings.continuousWarnSec;
    const crossedCritical = previous.continuousDrivingSec < settings.continuousCriticalSec
      && next.continuousDrivingSec >= settings.continuousCriticalSec;
    let alert: AlertEvent | undefined;
    if (state !== previous.state && ['CRITICAL', 'DROWSINESS_SIGNS', 'DISCONNECTED'].includes(state)) {
      alert = demoEvent(next, at, state === 'DISCONNECTED' ? 'DISCONNECTED' : 'DROWSINESS',
        state === 'CRITICAL' ? 'CRITICAL' : 'WARNING', `realtime-${bootId}-${tick}-${i}`);
    } else if (active && (crossedLimit || crossedCritical)) {
      alert = demoEvent(next, at, 'LONG_DRIVING', crossedCritical ? 'CRITICAL' : 'WARNING', `realtime-${bootId}-${tick}-${i}`);
    }
    if (alert) {
      events.set(alert.id, alert);
      storeEvents();
    }
    next.drowsyCountToday = drowsyToday(next.driverId, now);
    live[i] = next;
    handlers.onDriver(next);
    if (alert) handlers.onAlert(alert);
  }
}

export const mockApi: AdminApi = {
  setAccessToken(value) { token = value; },
  async login(username, password) {
    await pause();
    const account = Object.entries(DEMO_USERS).find(([name]) => name === username.trim().toLowerCase());
    if (password !== DEMO_PASSWORD || !account) {
      throw new ApiError('Tên đăng nhập hoặc mật khẩu không đúng.', 401);
    }
    return { accessToken: `demo:${account[0]}`, user: account[1] };
  },
  async me(signal) { await pause(signal); return user(); },
  async getLive(signal) {
    await pause(signal);
    operator();
    const now = Date.now();
    return live.map((driver) => {
      const connected = driver.state !== 'OFFLINE' && driver.state !== 'DISCONNECTED';
      return {
        ...driver,
        lastHeartbeatAt: connected ? new Date(now).toISOString() : driver.lastHeartbeatAt,
        drowsyCountToday: drowsyToday(driver.driverId, now),
      };
    });
  },
  async stream(handlers, signal) {
    await pause(signal);
    operator();
    handlers.onOpen();
    await new Promise<void>((resolve) => {
      const timer = setInterval(() => simulate(handlers), 4000);
      signal.addEventListener('abort', () => { clearInterval(timer); resolve(); }, { once: true });
    });
  },
  async getEvents(query, signal) {
    await pause(signal);
    operator();
    const { driverId, level, type, acked, page = 1, pageSize = 10 } = query;
    const result = [...events.values()].filter((event) =>
      (!driverId || event.driverId === driverId) && inRange(event.capturedAt, query)
      && (!level || event.level === level) && (!type || event.type === type)
      && (acked === undefined || Boolean(event.ackAt) === acked))
      .sort((a, b) => b.capturedAt.localeCompare(a.capturedAt));
    return { items: result.slice((page - 1) * pageSize, page * pageSize), total: result.length };
  },
  async ackEvent(id, note) {
    await pause();
    const current = operator();
    const event = events.get(id);
    if (!event) throw new ApiError('Không tìm thấy cảnh báo.', 404);
    if (event.ackAt) return event;
    const updated = { ...event, ackBy: current.id, ackAt: new Date().toISOString(), note: note.trim() || null };
    events.set(id, updated);
    storeEvents();
    return updated;
  },
  async getDrivers(signal) { await pause(signal); operator(); return demoDrivers; },
  async createDriver(payload) {
    await pause();
    if (operator().role !== 'manager') throw new ApiError('Chỉ quản lý có thể tạo tài xế.', 403);
    const created = {
      id: `driver-mock-${Date.now()}`,
      fullName: payload.fullName.trim(),
      phone: payload.phone.trim(),
      vehicleId: payload.vehicleId || `veh-mock-${Date.now()}`,
      vehicleName: payload.vehicleName?.trim() || 'Chưa phân xe',
      avatarUrl: null,
    };
    demoDrivers.push(created);
    live.push({
      driverId: created.id,
      fullName: created.fullName,
      phone: created.phone,
      vehicleName: created.vehicleName,
      state: 'OFFLINE',
      sessionId: null,
      continuousDrivingSec: 0,
      totalDrivingSec: 0,
      drowsyCountToday: 0,
      lastHeartbeatAt: null,
      location: null,
    });
    return created;
  },
  async createPairingCode(payload = {}) {
    await pause();
    if (operator().role !== 'manager') throw new ApiError('Chỉ quản lý có thể tạo mã ghép xe.', 403);
    const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    const code = Array.from({ length: 6 }, () => alphabet[Math.floor(Math.random() * alphabet.length)]).join('');
    const minutes = payload.expiresInMinutes ?? 60;
    return { code, expiresAt: new Date(Date.now() + minutes * 60_000).toISOString() };
  },
  async getDriver(id, signal) {
    await pause(signal);
    operator();
    const driver = getDriver(id);
    const recentSessions = [...getActiveSession(live.find((entry) => entry.driverId === id)!),
      ...seeded.sessions.filter((session) => session.driverId === id)].slice(0, 7);
    return { ...driver, recentSessions };
  },
  async getDriverStats(id, range, signal) {
    await pause(signal); operator(); getDriver(id);
    return driverStats(id, range);
  },
  async getHourly(range, signal) {
    await pause(signal); operator();
    const buckets = Array.from({ length: 24 }, (_, hour): HourlyStats => ({ hour, warning: 0, critical: 0 }));
    for (const event of events.values()) {
      if (inRange(event.capturedAt, range)) buckets[hourOf(event.capturedAt)][event.level === 'CRITICAL' ? 'critical' : 'warning'] += 1;
    }
    return buckets;
  },
  async getRanking(range, signal) {
    await pause(signal); operator();
    return demoDrivers.map(({ id, fullName }) => {
      const { alertCount, alertsPerDrivingHour } = driverStats(id, range);
      return { driverId: id, fullName, alertCount, alertsPerDrivingHour };
    }).sort((a, b) => b.alertsPerDrivingHour - a.alertsPerDrivingHour);
  },
  async getSystemHealth(range, signal) {
    await pause(signal); operator();
    const scoped = [...events.values()].filter((event) => inRange(event.capturedAt, range));
    return {
      tooDarkRate: scoped.length ? 0.028 : 0,
      unavailableRate: scoped.length ? 0.047 : 0,
      disconnectedCount: scoped.filter((event) => event.type === 'DISCONNECTED').length,
    };
  },
  async getSettings(signal) { await pause(signal); operator(); return { ...settings }; },
  async updateSettings(next) {
    await pause();
    if (operator().role !== 'manager') throw new ApiError('Chỉ quản lý có thể sửa cài đặt.', 403);
    settings = { ...next };
    writeStorage(storePrefix + 'settings', settings, 'sessionStorage');
    return { ...settings };
  },
  async getLiveLocations(signal) {
    await pause(signal);
    operator();
    const basePoints: Array<[number, number, number, number]> = [
      [10.7769, 106.7009, 68, 45],
      [10.9574, 106.8426, 74, 62],
      [11.9404, 108.4583, 55, 30],
      [15.8801, 108.338, 72, 350],
      [16.4637, 107.5909, 0, 0],
      [21.0285, 105.8542, 0, 0],
    ];
    return live.map((drv, idx) => {
      const [baseLat, baseLng, baseSpeed, heading] = basePoints[idx % basePoints.length];
      const moving = drv.state !== 'OFFLINE' && drv.state !== 'DISCONNECTED';
      const offset = moving ? (tick % 12) * 0.0025 : 0;
      return {
        driverId: drv.driverId,
        driverName: drv.fullName,
        vehicleId: `veh-${idx + 1}`,
        vehicleName: drv.vehicleName,
        state: drv.state,
        sessionId: drv.sessionId,
        lat: Number((baseLat + offset).toFixed(5)),
        lng: Number((baseLng + offset * 0.8).toFixed(5)),
        speedKmh: moving ? baseSpeed : 0,
        headingDeg: heading,
        at: drv.lastHeartbeatAt ?? new Date().toISOString(),
      };
    });
  },
  async getLocationTrail(query, signal) {
    await pause(signal);
    operator();
    const targetId = query.driverId || live[0]?.driverId || 'driver-1';
    const drv = live.find((item) => item.driverId === targetId) ?? live[0];
    const drvIdx = Math.max(0, live.findIndex((item) => item.driverId === drv.driverId));
    const baseLat = 10.7769 + drvIdx * 0.45;
    const baseLng = 106.7009 + drvIdx * 0.35;
    const now = Date.now();
    const drvEvents = [...events.values()]
      .filter((ev) => ev.driverId === drv.driverId)
      .sort((a, b) => a.capturedAt.localeCompare(b.capturedAt))
      .slice(-4);

    const points = Array.from({ length: 8 }, (_, step) => {
      const linkedEvent = step === 3 ? drvEvents[0] : step === 6 ? drvEvents[1] : undefined;
      return {
        lat: Number((baseLat + step * 0.012).toFixed(5)),
        lng: Number((baseLng + step * 0.015).toFixed(5)),
        speedKmh: 62 + (step % 4) * 5,
        headingDeg: 42,
        at: new Date(now - (8 - step) * 180_000).toISOString(),
        eventId: linkedEvent?.id ?? null,
      };
    });

    const alerts = drvEvents.slice(0, 2).map((ev, idx) => {
      const pt = points[idx === 0 ? 3 : 6];
      return {
        eventId: ev.id,
        type: ev.type,
        level: ev.level,
        severityLevel: ev.level === 'CRITICAL' ? 3 : 2,
        status: ev.status,
        driverId: ev.driverId,
        driverName: ev.driverName,
        vehicleName: ev.vehicleName,
        lat: ev.lat ?? pt.lat,
        lng: ev.lng ?? pt.lng,
        occurredAt: ev.capturedAt,
        note: ev.note,
      };
    });

    return {
      driverId: drv.driverId,
      driverName: drv.fullName,
      vehicleName: drv.vehicleName,
      sessionId: drv.sessionId,
      points,
      alerts,
    };
  },
  async getAlarmFatigue(signal) {
    await pause(signal);
    operator();
    return demoDrivers.map((drv, idx) => {
      const monitoredMinutes = 420 + idx * 55;
      const monitoringOffCount = (idx % 3) + 1;
      const alertsTotal = 8 + idx * 2;
      const alertsFalse = idx % 4;
      const offPerHour = Number((monitoringOffCount / (monitoredMinutes / 60)).toFixed(2));
      const falseAlertPct = Number(((100 * alertsFalse) / alertsTotal).toFixed(1));
      return {
        driverId: drv.id,
        fullName: drv.fullName,
        monitoredMinutes,
        monitoringOffCount,
        alertsTotal,
        alertsFalse,
        offPerHour,
        falseAlertPct,
      };
    });
  },
};

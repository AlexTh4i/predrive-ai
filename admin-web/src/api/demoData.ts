import { dayKey, dayOf, localDateTime, shiftDay } from '../lib/format';
import type { AlertEvent, Driver, DriverState, EventLevel, EventType, LiveDriverState, Session } from '../types';

const names = ['Nguyễn Văn Minh', 'Trần Quốc Huy', 'Lê Hoàng Nam', 'Phạm Đức Long', 'Võ Thanh Sơn', 'Đặng Minh Tâm'];
const plates = ['51B-245.18', '50H-317.62', '51B-192.06', '50H-406.35', '51C-867.24', '51B-309.72'];
const initialStates: DriverState[] = ['CRITICAL', 'DROWSINESS_SIGNS', 'NORMAL', 'NORMAL', 'DISCONNECTED', 'OFFLINE'];
const drivingTimes = [8640, 4920, 3780, 2460, 6020, 0];

export const demoDrivers: Driver[] = names.map((fullName, i) => ({
  id: `driver-${i + 1}`,
  fullName,
  phone: `+8400000000${i + 1}`,
  vehicleId: `vehicle-${i + 1}`,
  vehicleName: plates[i],
  avatarUrl: null,
}));

export const currentSessionId = (driverId: string, day: string) => `${driverId}-live-${day}`;

export function demoLive(now: number): LiveDriverState[] {
  return demoDrivers.map(({ id, fullName, phone, vehicleName }, i) => ({
    driverId: id, fullName, phone, vehicleName, state: initialStates[i],
    sessionId: i === 5 ? null : currentSessionId(id, dayKey(now)),
    continuousDrivingSec: drivingTimes[i],
    totalDrivingSec: drivingTimes[i] + (i === 5 ? 0 : 1800),
    drowsyCountToday: 0,
    lastHeartbeatAt: i === 5 ? null : new Date(now - (i === 4 ? 91_000 : 0)).toISOString(),
    location: null,
  }));
}

export function demoEvent(
  driver: LiveDriverState, at: string, type: EventType, level: EventLevel,
  id: string, options: { delayed?: boolean; closed?: boolean; acked?: boolean; sessionId?: string } = {},
): AlertEvent {
  const { delayed = false, closed = false, acked = false, sessionId = driver.sessionId } = options;
  return {
    id, sessionId: sessionId ?? currentSessionId(driver.driverId, dayOf(at)), driverId: driver.driverId,
    driverName: driver.fullName, vehicleName: driver.vehicleName, type, level,
    status: closed ? 'CLOSED' : level === 'CRITICAL' ? 'ESCALATED' : 'OPEN',
    state: type === 'DISCONNECTED' ? 'DISCONNECTED' : type === 'DROWSINESS'
      ? (level === 'CRITICAL' ? 'CRITICAL' : 'DROWSINESS_SIGNS') : 'NORMAL',
    riskScore: type === 'DROWSINESS' ? (level === 'CRITICAL' ? 0.95 : 0.8) : null,
    startedAt: at, durationSec: closed ? 48 : 0, delayed, capturedAt: at,
    receivedAt: delayed ? new Date(Date.parse(at) + 95_000).toISOString() : at,
    ackBy: acked ? 'demo-dispatcher' : null,
    ackAt: acked ? new Date(Date.parse(at) + 120_000).toISOString() : null,
    note: acked ? 'Đã gọi và nhắc tài xế dừng nghỉ.' : null,
  };
}

export function seedDemo(now: number, live: LiveDriverState[]) {
  const today = dayKey(now);
  const sessions: Session[] = [];
  const events: AlertEvent[] = [];
  for (let daysAgo = 0; daysAgo < 28; daysAgo += 1) {
    const day = shiftDay(today, -daysAgo);
    for (let i = 0; i < live.length; i += 1) {
      if ((daysAgo + i) % 5 === 4) continue;
      const driver = live[i];
      const sessionId = `${driver.driverId}-${day}`;
      const morning = i % 4 !== 3;
      const startedAt = localDateTime(day, morning ? '00:45:00' : '11:00:00');
      const totalDrivingSec = 12600 + ((daysAgo + i) % 4) * 900;
      const endedAt = new Date(Date.parse(startedAt) + totalDrivingSec * 1000).toISOString();
      if (Date.parse(endedAt) > now) continue;
      const sessionEvents: AlertEvent[] = [];
      if ((daysAgo * 2 + i) % 3 !== 1) {
        const hour = morning ? (i % 3) + 2 : 13;
        const capturedAt = localDateTime(day, `${String(hour).padStart(2, '0')}:05:00`);
        if (capturedAt <= endedAt) {
          const level = (daysAgo + i) % 4 === 0 ? 'CRITICAL' : 'WARNING';
          sessionEvents.push(demoEvent(driver, capturedAt, 'DROWSINESS', level, `${sessionId}-drowsy`, {
            sessionId, closed: true, delayed: (daysAgo + i) % 9 === 2, acked: daysAgo > 0 && (daysAgo + i) % 3 === 0,
          }));
        }
      }
      if ((daysAgo + i) % 7 === 0) {
        sessionEvents.push(demoEvent(driver, endedAt, 'LONG_DRIVING', 'WARNING', `${sessionId}-long`, {
          sessionId, closed: true, acked: daysAgo > 0,
        }));
      }
      events.push(...sessionEvents);
      sessions.push({
        id: sessionId, driverId: driver.driverId, startedAt, endedAt, totalDrivingSec,
        warningCount: sessionEvents.filter((event) => event.level === 'WARNING').length,
        criticalCount: sessionEvents.filter((event) => event.level === 'CRITICAL').length,
      });
    }
  }
  const recent = [
    { i: 0, minutes: 2, type: 'DROWSINESS', level: 'CRITICAL' },
    { i: 1, minutes: 6, type: 'DROWSINESS', level: 'WARNING' },
    { i: 4, minutes: 11, type: 'DISCONNECTED', level: 'WARNING' },
    { i: 2, minutes: 18, type: 'LONG_DRIVING', level: 'WARNING' },
    { i: 3, minutes: 31, type: 'DROWSINESS', level: 'WARNING' },
  ] satisfies { i: number; minutes: number; type: EventType; level: EventLevel }[];
  for (const { i, minutes, type, level } of recent) {
    events.push(demoEvent(live[i], new Date(now - minutes * 60_000).toISOString(), type, level,
      `recent-${today}-${i}`, { acked: i === 2, closed: i === 2 || i === 3 }));
  }
  return { events, sessions };
}

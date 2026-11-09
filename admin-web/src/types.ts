export type DriverState =
  | 'NORMAL'
  | 'DROWSINESS_SIGNS'
  | 'CRITICAL'
  | 'DISTRACTED'
  | 'MONITORING_UNAVAILABLE'
  | 'OFFLINE'
  | 'DISCONNECTED';

export type EventType = 'DROWSINESS' | 'LONG_DRIVING' | 'DISCONNECTED' | 'REST_CLAIM_REJECTED';
export type EventLevel = 'WARNING' | 'CRITICAL';
export type EventStatus = 'OPEN' | 'ESCALATED' | 'CLOSED';
export type Role = 'manager' | 'dispatcher' | 'driver';

export interface User {
  id: string;
  role: Role;
  fullName: string;
  organizationId: string;
}

export interface LoginResult {
  accessToken: string;
  user: User;
}

export interface Driver {
  id: string;
  fullName: string;
  phone: string;
  vehicleId: string;
  vehicleName: string;
  avatarUrl: string | null;
}

export interface LiveDriverState {
  driverId: string;
  fullName: string;
  phone: string;
  vehicleName: string;
  state: DriverState;
  sessionId: string | null;
  continuousDrivingSec: number;
  totalDrivingSec: number;
  drowsyCountToday: number;
  lastHeartbeatAt: string | null;
  location: { lat: number; lng: number; at: string } | null;
}

export interface AlertEvent {
  id: string;
  sessionId: string;
  driverId: string;
  driverName: string;
  vehicleName: string;
  type: EventType;
  level: EventLevel;
  status: EventStatus;
  state: DriverState;
  riskScore: number | null;
  startedAt: string;
  durationSec: number;
  delayed: boolean;
  capturedAt: string;
  receivedAt: string;
  ackBy: string | null;
  ackAt: string | null;
  note: string | null;
}

export interface Session {
  id: string;
  driverId: string;
  startedAt: string;
  endedAt: string | null;
  totalDrivingSec: number;
  warningCount: number;
  criticalCount: number;
}

export type DriverDetail = Driver & { recentSessions: Session[] };

export interface Settings {
  continuousWarnSec: number;
  continuousCriticalSec: number;
  restResetMin: number;
  shareLocation: boolean;
  heartbeatIntervalSec: number;
}

export interface DateRange {
  from?: string;
  to?: string;
}

export interface EventQuery extends DateRange {
  driverId?: string;
  level?: EventLevel;
  type?: EventType;
  acked?: boolean;
  page?: number;
  pageSize?: number;
}

export interface EventPage {
  items: AlertEvent[];
  total: number;
}

export interface HourlyStats {
  hour: number;
  warning: number;
  critical: number;
}

export interface DriverStats {
  totalDrivingSec: number;
  alertCount: number;
  alertsPerDrivingHour: number;
  hourly: { hour: number; count: number }[];
}

export interface RankingEntry {
  driverId: string;
  fullName: string;
  alertsPerDrivingHour: number;
  alertCount: number;
}

export interface SystemHealth {
  tooDarkRate: number;
  unavailableRate: number;
  disconnectedCount: number;
}

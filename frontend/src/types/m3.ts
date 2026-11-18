import type { ImageQuality } from './monitor';

export type Role = 'manager' | 'dispatcher' | 'driver';

export type ContractState =
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

export interface AuthUser {
  id: string;
  role: Role;
  fullName: string;
  organizationId: string;
  mustChangePassword?: boolean;
  hasConsented?: boolean;
}

export interface ConsentStatusResponse {
  hasConsented: boolean;
  version: string;
  locationConsent: boolean;
  clipStorageConsent: boolean;
  acceptedAt?: string | null;
}

export interface LoginResponse {
  accessToken: string;
  refreshToken?: string;
  expiresIn?: number;
  user: AuthUser;
}

export interface PairResponse {
  vehicleName: string;
  organizationName: string;
}

export interface DriverSettings {
  continuousWarnSec: number;
  continuousCriticalSec: number;
  restResetMin: number;
  shareLocation: boolean;
  heartbeatIntervalSec: number;
  locationIntervalSec?: number;
  earThreshold?: number;
  eyeClosedSec?: number;
  headPoseSec?: number;
  tooDarkThreshold?: number;
  level1Sec?: number;
  level2Sec?: number;
  level3Sec?: number;
  maxContinuousDriveMin?: number;
  restReminderBeforeMin?: number;
}

export const DEFAULT_DRIVER_SETTINGS: DriverSettings = {
  continuousWarnSec: 7200,
  continuousCriticalSec: 10800,
  restResetMin: 15,
  shareLocation: false,
  heartbeatIntervalSec: 30,
  locationIntervalSec: 30,
  earThreshold: 0.28,
  eyeClosedSec: 1.0,
  headPoseSec: 1.8,
  tooDarkThreshold: 20.0,
  level1Sec: 1.0,
  level2Sec: 2.0,
  level3Sec: 4.0,
  maxContinuousDriveMin: 240,
  restReminderBeforeMin: 15,
};

export interface CreateSessionResponse {
  sessionId: string;
  settings: DriverSettings;
}

export interface UpsertEventRequest {
  eventId: string;
  type: EventType;
  level: EventLevel;
  severityLevel?: number;
  status: EventStatus;
  state: ContractState;
  riskScore: number | null;
  startedAt: string;
  durationSec: number;
  capturedAt: string;
  lat?: number | null;
  lng?: number | null;
  speedKmh?: number | null;
  headingDeg?: number | null;
}

export interface AlertEventResponse {
  id: string;
  sessionId: string;
  driverId: string;
  driverName: string;
  vehicleName: string;
  type: EventType;
  level: EventLevel;
  status: EventStatus;
  state: ContractState;
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

export interface BatchEventsResponse {
  items: AlertEventResponse[];
  total: number;
}

export interface HeartbeatLocation {
  lat: number;
  lng: number;
  speedKmh?: number | null;
  headingDeg?: number | null;
  at?: string;
}

export interface LocationIngestPayload {
  lat?: number;
  lng?: number;
  speedKmh?: number | null;
  headingDeg?: number | null;
  at?: string;
  eventId?: string;
  points?: Array<HeartbeatLocation & { eventId?: string }>;
}

export interface LocationIngestResponse {
  accepted: number;
  shareLocationEnabled: boolean;
}

export interface HeartbeatRequest {
  state: ContractState;
  imageQuality: ImageQuality;
  continuousDrivingSec: number;
  vehicleMoving: boolean;
  capturedAt: string;
  location?: HeartbeatLocation | null;
}

export interface HeartbeatResponse {
  status: string;
  state: ContractState;
  receivedAt: string;
}

export interface EndSessionRequest {
  endedAt: string;
  summary: {
    totalDrivingSec: number;
    warningCount: number;
    criticalCount: number;
    unavailableSec: number;
  };
}

export interface SessionSummaryResponse {
  id: string;
  driverId: string;
  startedAt: string;
  endedAt: string | null;
  totalDrivingSec: number;
  warningCount: number;
  criticalCount: number;
}

export type DriverMode = 'online' | 'offline_demo';

export interface DriverAuthSession {
  accessToken: string;
  refreshToken?: string;
  user: AuthUser;
  vehicleName?: string;
  organizationName?: string;
  consentedAt?: string;
  consentVersion?: string;
  locationConsent?: boolean;
}


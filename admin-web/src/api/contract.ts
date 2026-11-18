import type {
  AlertEvent, CreateDriverPayload, CreatePairingCodePayload, DateRange, Driver, DriverDetail, DriverStats, EventPage, EventQuery,
  HourlyStats, LiveDriverState, LiveVehicleLocation, LocationTrailResponse, LoginResult, PairingCodeResult, RankingEntry, Settings, SystemHealth, User,
} from '../types';

export const SESSION_EXPIRED = 'predrive:session-expired';
export const SESSION_REFRESHED = 'predrive:session-refreshed';

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) {
    super(message);
    this.name = 'ApiError';
  }
}

export interface LiveHandlers {
  onOpen(): void;
  onDriver(driver: LiveDriverState): void;
  onAlert(alert: AlertEvent): void;
}

export interface AdminApi {
  setAccessToken(token: string | null): void;
  setRefreshToken?(token: string | null): void;
  logout?(refreshToken?: string | null): Promise<void>;
  login(username: string, password: string): Promise<LoginResult>;
  me(signal?: AbortSignal): Promise<User>;
  getLive(signal?: AbortSignal): Promise<LiveDriverState[]>;
  stream(handlers: LiveHandlers, signal: AbortSignal): Promise<void>;
  getEvents(query: EventQuery, signal?: AbortSignal): Promise<EventPage>;
  ackEvent(id: string, note: string): Promise<AlertEvent>;
  getDrivers(signal?: AbortSignal): Promise<Driver[]>;
  createDriver(payload: CreateDriverPayload): Promise<Driver>;
  createPairingCode(payload?: CreatePairingCodePayload): Promise<PairingCodeResult>;
  getDriver(id: string, signal?: AbortSignal): Promise<DriverDetail>;
  getDriverStats(id: string, range: DateRange, signal?: AbortSignal): Promise<DriverStats>;
  getHourly(range: DateRange, signal?: AbortSignal): Promise<HourlyStats[]>;
  getRanking(range: DateRange, signal?: AbortSignal): Promise<RankingEntry[]>;
  getSystemHealth(range: DateRange, signal?: AbortSignal): Promise<SystemHealth>;
  getSettings(signal?: AbortSignal): Promise<Settings>;
  updateSettings(settings: Settings): Promise<Settings>;
  getLiveLocations(signal?: AbortSignal): Promise<LiveVehicleLocation[]>;
  getLocationTrail(query: { driverId?: string; sessionId?: string; from?: string; to?: string }, signal?: AbortSignal): Promise<LocationTrailResponse>;
}

export const defaultSettings: Settings = {
  continuousWarnSec: 7200,
  continuousCriticalSec: 10800,
  restResetMin: 15,
  shareLocation: false,
  heartbeatIntervalSec: 30,
};

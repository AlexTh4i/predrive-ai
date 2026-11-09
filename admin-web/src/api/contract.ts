import type {
  AlertEvent, DateRange, Driver, DriverDetail, DriverStats, EventPage, EventQuery,
  HourlyStats, LiveDriverState, LoginResult, RankingEntry, Settings, SystemHealth, User,
} from '../types';

export const SESSION_EXPIRED = 'predrive:session-expired';

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
  login(username: string, password: string): Promise<LoginResult>;
  me(signal?: AbortSignal): Promise<User>;
  getLive(signal?: AbortSignal): Promise<LiveDriverState[]>;
  stream(handlers: LiveHandlers, signal: AbortSignal): Promise<void>;
  getEvents(query: EventQuery, signal?: AbortSignal): Promise<EventPage>;
  ackEvent(id: string, note: string): Promise<AlertEvent>;
  getDrivers(signal?: AbortSignal): Promise<Driver[]>;
  getDriver(id: string, signal?: AbortSignal): Promise<DriverDetail>;
  getDriverStats(id: string, range: DateRange, signal?: AbortSignal): Promise<DriverStats>;
  getHourly(range: DateRange, signal?: AbortSignal): Promise<HourlyStats[]>;
  getRanking(range: DateRange, signal?: AbortSignal): Promise<RankingEntry[]>;
  getSystemHealth(range: DateRange, signal?: AbortSignal): Promise<SystemHealth>;
  getSettings(signal?: AbortSignal): Promise<Settings>;
  updateSettings(settings: Settings): Promise<Settings>;
}

export const defaultSettings: Settings = {
  continuousWarnSec: 7200,
  continuousCriticalSec: 10800,
  restResetMin: 15,
  shareLocation: false,
  heartbeatIntervalSec: 30,
};

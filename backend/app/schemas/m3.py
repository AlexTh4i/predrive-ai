from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer


def _ensure_utc(v: Any) -> Any:
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
    return v


def _serialize_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


UtcDatetime = Annotated[
    datetime,
    BeforeValidator(_ensure_utc),
    PlainSerializer(_serialize_utc, return_type=str, when_used="json"),
]

ContractState = Literal[
    "NORMAL",
    "DROWSINESS_SIGNS",
    "CRITICAL",
    "DISTRACTED",
    "MONITORING_UNAVAILABLE",
    "OFFLINE",
    "DISCONNECTED",
]

EventType = Literal[
    "DROWSY",
    "DROWSINESS",
    "DISTRACTED",
    "HEAD_DOWN",
    "TOO_DARK",
    "NO_FACE",
    "LONG_DRIVING",
    "DISCONNECTED",
    "REST_CLAIM_REJECTED",
]

EventLevel = Literal["WARNING", "CRITICAL"]

EventStatus = Literal["OPEN", "ESCALATED", "CLOSED"]

ImageQualityEnum = Literal["GOOD", "LOW_LIGHT", "BLURRY", "TOO_DARK", "UNKNOWN"]

UserRole = Literal["manager", "dispatcher", "driver"]


class CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


# --- AUTH ---
class LoginRequest(CamelModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class AuthUserSchema(CamelModel):
    id: str
    role: UserRole
    fullName: str
    organizationId: str
    mustChangePassword: bool = False
    hasConsented: bool = False


class ConsentAcceptRequest(CamelModel):
    version: str = Field(default="2026-01", min_length=1, max_length=32)
    locationConsent: bool = True
    clipStorageConsent: bool = False


class ConsentStatusResponse(CamelModel):
    hasConsented: bool
    version: str
    locationConsent: bool
    clipStorageConsent: bool = False
    acceptedAt: Optional[UtcDatetime] = None


class LoginResponse(CamelModel):
    accessToken: str
    refreshToken: Optional[str] = None
    expiresIn: int = 900
    user: AuthUserSchema


class RefreshTokenRequest(CamelModel):
    refreshToken: str = Field(min_length=1)


class LogoutRequest(CamelModel):
    refreshToken: Optional[str] = None


class ChangePasswordRequest(CamelModel):
    currentPassword: str = Field(min_length=1)
    newPassword: str = Field(min_length=8, max_length=128)


class PairRequest(CamelModel):
    code: str = Field(min_length=1)


class PairResponse(CamelModel):
    vehicleName: str
    organizationName: str


# --- SETTINGS ---
class SettingsSchema(CamelModel):
    continuousWarnSec: int = Field(default=7200, ge=60)
    continuousCriticalSec: int = Field(default=10800, ge=60)
    restResetMin: int = Field(default=15, ge=1)
    shareLocation: bool = False
    heartbeatIntervalSec: int = Field(default=30, ge=5)
    # Extended dynamic thresholds & retention policies per organization (R3 / P2-6 / Phase 3)
    earThreshold: Optional[float] = Field(default=None, ge=0.05, le=0.6)
    eyeClosedSec: Optional[float] = Field(default=None, ge=0.2, le=30.0)
    headPoseSec: Optional[float] = Field(default=None, ge=0.2, le=30.0)
    tooDarkThreshold: Optional[float] = Field(default=None, ge=1.0, le=150.0)
    level1Sec: Optional[float] = Field(default=None, ge=0.2, le=30.0)
    level2Sec: Optional[float] = Field(default=None, ge=0.5, le=60.0)
    level3Sec: Optional[float] = Field(default=None, ge=1.0, le=120.0)
    ackTimeoutSec: Optional[int] = Field(default=None, ge=5, le=3600)
    maxContinuousDriveMin: Optional[int] = Field(default=None, ge=1, le=1440)
    restReminderBeforeMin: Optional[int] = Field(default=None, ge=1, le=180)
    locationIntervalSec: Optional[int] = Field(default=None, ge=5, le=600)
    heartbeatRetentionDays: Optional[int] = Field(default=None, ge=1, le=3650)
    locationRetentionDays: Optional[int] = Field(default=None, ge=1, le=3650)
    eventRetentionDays: Optional[int] = Field(default=None, ge=1, le=3650)
    auditRetentionDays: Optional[int] = Field(default=None, ge=1, le=3650)


# --- DRIVER APP ---
class CreateSessionRequest(CamelModel):
    sessionId: str = Field(min_length=1)
    startedAt: UtcDatetime


class CreateSessionResponse(CamelModel):
    sessionId: str
    settings: SettingsSchema


class UpsertEventRequest(CamelModel):
    eventId: str = Field(min_length=1)
    type: EventType
    level: EventLevel
    status: EventStatus
    state: ContractState
    riskScore: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    startedAt: UtcDatetime
    durationSec: int = Field(ge=0)
    capturedAt: UtcDatetime


class BatchEventsRequest(CamelModel):
    events: list[UpsertEventRequest]


class HeartbeatLocationInput(CamelModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)
    at: Optional[UtcDatetime] = None


class HeartbeatRequest(CamelModel):
    state: ContractState
    imageQuality: ImageQualityEnum = "GOOD"
    continuousDrivingSec: int = Field(ge=0)
    vehicleMoving: bool = True
    capturedAt: UtcDatetime
    location: Optional[HeartbeatLocationInput] = None


class HeartbeatResponse(CamelModel):
    status: str = "ok"
    state: ContractState
    receivedAt: UtcDatetime


class EndSessionSummary(CamelModel):
    totalDrivingSec: int = Field(ge=0)
    warningCount: int = Field(ge=0)
    criticalCount: int = Field(ge=0)
    unavailableSec: int = Field(ge=0)


class EndSessionRequest(CamelModel):
    endedAt: UtcDatetime
    summary: EndSessionSummary


# --- SHARED / WEB ENTITIES ---
class DriverSchema(CamelModel):
    id: str
    fullName: str
    phone: str
    vehicleId: Optional[str] = None
    vehicleName: str
    avatarUrl: Optional[str] = None
    temporaryPassword: Optional[str] = None


class SessionSchema(CamelModel):
    id: str
    driverId: str
    startedAt: UtcDatetime
    endedAt: Optional[UtcDatetime] = None
    totalDrivingSec: int
    warningCount: int
    criticalCount: int


class DriverDetailResponse(DriverSchema):
    recentSessions: list[SessionSchema]


class LocationPoint(CamelModel):
    lat: float
    lng: float
    at: UtcDatetime


class LiveDriverState(CamelModel):
    driverId: str
    fullName: str
    phone: str
    vehicleName: str
    state: ContractState
    sessionId: Optional[str] = None
    continuousDrivingSec: int
    totalDrivingSec: int
    drowsyCountToday: int
    lastHeartbeatAt: Optional[UtcDatetime] = None
    location: Optional[LocationPoint] = None


class AlertEvent(CamelModel):
    id: str
    sessionId: str
    driverId: str
    driverName: str
    vehicleName: str
    type: EventType
    level: EventLevel
    status: EventStatus
    state: ContractState
    riskScore: Optional[float] = None
    startedAt: UtcDatetime
    durationSec: int
    delayed: bool
    capturedAt: UtcDatetime
    receivedAt: UtcDatetime
    ackBy: Optional[str] = None
    ackAt: Optional[UtcDatetime] = None
    note: Optional[str] = None


class BatchEventsResponse(CamelModel):
    items: list[AlertEvent]
    total: int


class PaginatedEventsResponse(CamelModel):
    items: list[AlertEvent]
    total: int


class AckEventRequest(CamelModel):
    note: Optional[str] = None


# --- STATS ---
class HourlyCountItem(CamelModel):
    hour: int = Field(ge=0, le=23)
    count: int = Field(ge=0)


class DriverStatsResponse(CamelModel):
    totalDrivingSec: int
    alertCount: int
    alertsPerDrivingHour: float
    hourly: list[HourlyCountItem]


class HourlyBreakdownItem(CamelModel):
    hour: int = Field(ge=0, le=23)
    warning: int = Field(ge=0)
    critical: int = Field(ge=0)


class DriverRankingItem(CamelModel):
    driverId: str
    fullName: str
    alertsPerDrivingHour: float
    alertCount: int


class SystemHealthResponse(CamelModel):
    tooDarkRate: float
    unavailableRate: float
    disconnectedCount: int


# --- PAIRING & DRIVER CREATION ---
class CreatePairingCodeRequest(CamelModel):
    vehicleId: Optional[str] = None
    expiresInMinutes: int = Field(default=60, ge=1, le=10080)


class PairingCodeResponse(CamelModel):
    code: str
    expiresAt: UtcDatetime


class CreateDriverRequest(CamelModel):
    fullName: str = Field(min_length=1)
    phone: str = Field(min_length=1)
    username: Optional[str] = None
    password: Optional[str] = None
    vehicleId: Optional[str] = None
    vehicleName: Optional[str] = None
    avatarUrl: Optional[str] = None


# --- AUDIT LOGS, API KEYS & REPORTS (P1-4 / P3-6 / P3-8) ---
class AuditLogItem(CamelModel):
    id: int
    organizationId: Optional[str] = None
    actorId: Optional[str] = None
    actorName: Optional[str] = None
    action: str
    entity: Optional[str] = None
    entityId: Optional[str] = None
    ip: Optional[str] = None
    meta: dict[str, Any] = Field(default_factory=dict)
    createdAt: UtcDatetime


class PaginatedAuditLogsResponse(CamelModel):
    items: list[AuditLogItem]
    total: int


class CreateApiKeyRequest(CamelModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["events:read", "vehicles:read"])


class ApiKeyItem(CamelModel):
    id: str
    name: str
    keyPrefix: str
    scopes: list[str]
    lastUsedAt: Optional[UtcDatetime] = None
    revokedAt: Optional[UtcDatetime] = None
    createdAt: UtcDatetime


class ApiKeyCreatedResponse(ApiKeyItem):
    rawKey: str


class ExportReportRequest(CamelModel):
    reportType: Literal["weekly", "monthly"] = "weekly"
    fileFormat: Literal["pdf", "xlsx"] = "pdf"
    periodStart: Optional[str] = None
    periodEnd: Optional[str] = None


class ReportItem(CamelModel):
    id: str
    reportType: Literal["weekly", "monthly"]
    fileFormat: Literal["pdf", "xlsx"]
    periodStart: str
    periodEnd: str
    status: Literal["pending", "ready", "failed"]
    storagePath: Optional[str] = None
    createdAt: UtcDatetime



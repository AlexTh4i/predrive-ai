from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SessionResponse(BaseModel):
    session_id: UUID
    created_at: datetime
    expires_at: datetime


class FrameMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["frame"]
    session_id: UUID
    frame_id: int = Field(ge=0)
    captured_at: datetime
    image_format: Literal["jpeg"]
    image_base64: str = Field(min_length=1)

    @field_validator("captured_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        return value.astimezone(timezone.utc)


DriverState = Literal[
    "NOT_EVALUATED",
    "NORMAL",
    "DISTRACTED",
    "DROWSINESS_SIGNS",
    "CRITICAL",
    "MONITORING_UNAVAILABLE",
]

AlertLevel = Literal["NONE", "INFO", "WARNING", "CRITICAL"]

ImageQuality = Literal["GOOD", "LOW_LIGHT", "BLURRY", "TOO_DARK", "UNKNOWN"]


class AnalysisResult(BaseModel):
    type: Literal["analysis_result"] = "analysis_result"
    session_id: UUID
    frame_id: int
    captured_at: datetime
    processed_at: datetime
    model_version: str = "baseline-mediapipe-v0.1"
    state: DriverState = "NOT_EVALUATED"
    alert_level: AlertLevel = "NONE"
    face_visible: Optional[bool] = None
    image_quality: ImageQuality = "UNKNOWN"
    risk_score: Optional[float] = None
    processing_ms: int = Field(ge=0)

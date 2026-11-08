from typing import Literal, Optional
from pydantic import BaseModel, Field

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


class AIAnalysisOutput(BaseModel):
    state: DriverState
    alert_level: AlertLevel
    face_visible: Optional[bool]
    image_quality: ImageQuality
    risk_score: Optional[float] = None
    ear: Optional[float] = None
    is_distracted: bool = False
    model_version: str = "baseline-mediapipe-v0.1"
    processing_ms: int = 0


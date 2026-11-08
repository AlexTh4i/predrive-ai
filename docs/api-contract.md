# PREDRIVE AI API Contract — MVP v0.2 (AI Integrated)

All timestamps are ISO 8601 with timezone; the backend normalizes them to UTC. Session metadata is in-memory only. No raw frames are stored.

## 1. Health and Session Endpoints

- `GET /health` → `{"status":"ok","service":"predrive-backend","version":"0.1.0"}`
- `POST /api/v1/sessions` → HTTP 201 with `session_id` (UUID), `created_at`, and `expires_at`.
- `WS /ws/monitor?session_id=<UUID>` accepts one active connection per session. Unknown/expired sessions close with policy code 1008.

## 2. Client → Server (`frame`)

Send one JSON object per WebSocket message:

```json
{
  "type": "frame",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "frame_id": 12,
  "captured_at": "2026-11-08T04:00:00.000Z",
  "image_format": "jpeg",
  "image_base64": "<base64-jpeg>"
}
```

Validation rules:
- Strictly increasing `frame_id` per session.
- Timestamp within `MAX_FRAME_AGE` (default 60s) and `MAX_FUTURE_SKEW` (default 60s).
- Valid base64-encoded JPEG, dimensions up to `1920x1080`, max `2 MiB` decoded.
- Rate limit up to `10` frames per rolling second.
- Invalid frames return `{"type":"error","code":"INVALID_FRAME","detail":"..."}` without dropping the WebSocket connection.

## 3. Server → Client (`analysis_result`)

### 3.1. Real AI Inference (`baseline-mediapipe-v0.1`)
```json
{
  "type": "analysis_result",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "frame_id": 12,
  "captured_at": "2026-11-08T04:00:00.000Z",
  "processed_at": "2026-11-08T04:00:00.038Z",
  "model_version": "baseline-mediapipe-v0.1",
  "state": "NORMAL",
  "alert_level": "NONE",
  "face_visible": true,
  "image_quality": "GOOD",
  "risk_score": 0.1,
  "processing_ms": 38
}
```

### 3.2. Enums
- `state`: `"NOT_EVALUATED" | "NORMAL" | "DISTRACTED" | "DROWSINESS_SIGNS" | "CRITICAL" | "MONITORING_UNAVAILABLE"`
- `alert_level`: `"NONE" | "INFO" | "WARNING" | "CRITICAL"`
- `image_quality`: `"GOOD" | "LOW_LIGHT" | "BLURRY" | "TOO_DARK" | "UNKNOWN"`
- `risk_score`: `null` or float in `[0.0, 1.0]`

## 4. Development & Mobile LAN Boundary

- In local development, Vite runs with `@vitejs/plugin-basic-ssl` (`https://<LAN-IP>:5173`) and proxies `/api`, `/health`, and `/ws` to `127.0.0.1:8000` so mobile browsers (iOS Safari / Android Chrome) operate in a valid Secure Context (`HTTPS` + `WSS`).
- Public deployment requires authenticated sessions, authorization checks, edge rate limits, restricted CORS origins, secret management, and privacy/retention controls.

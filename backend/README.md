# PREDRIVE AI backend (B1)

FastAPI gateway prototype. It creates short-lived in-memory test sessions and accepts JPEG frames over WebSocket. Until an evaluated AI model is integrated, every accepted frame returns `NOT_EVALUATED` with `model_version=mock-v0`. No images or frame metadata are persisted.

## Run locally

```powershell
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health: `http://<server-lan-ip>:8000/health`. Allow port 8000 only on a trusted private network. A phone browser can use `ws://<server-lan-ip>:8000/ws/monitor?session_id=...` only in a controlled development setup; camera access requires a secure context and public deployments require HTTPS/WSS, authentication, authorization, TLS termination, and appropriately restricted origins. The current MVP has no user authentication and must not be exposed to the public Internet.

Create a session with `POST /api/v1/sessions`, then connect to the WebSocket URL with the returned UUID. Send one JSON frame per message as documented in `../docs/api-contract.md`. Frames are decoded and validated in memory, then discarded.

Configuration is through environment variables shown in `.env.example`. Do not commit `.env`, secrets, or private images. The mock response is not an AI assessment or a safety feature. Test only with recorded/simulated content or consenting participants while the vehicle is stationary.

## Limits and known gaps

This B1 prototype uses process-local sessions, has no auth/database/AI, and does not persist events. Restarting the process removes sessions. Use a reverse proxy with TLS and request limits before phone testing beyond a trusted LAN; add authentication, authorization, abuse protection, monitoring and deployment review before any public exposure. It is a research prototype, not a certified driver-safety device.

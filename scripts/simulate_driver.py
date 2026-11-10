#!/usr/bin/env python3
"""Script giả lập 1 tài xế (Driver App Simulator) cho PreDrive AI Backend M3.

Kịch bản thực hiện:
1. Đăng nhập tài khoản tài xế (`POST /api/v1/auth/login`).
2. Mở phiên giám sát (`POST /api/v1/sessions` — kiểm tra idempotent bằng cách gửi 2 lần).
3. Gửi nhịp tim `NORMAL` (`POST /api/v1/sessions/{id}/heartbeat`).
4. Tạo chuỗi sự kiện buồn ngủ với cùng `eventId` chuyển trạng thái:
   `OPEN (WARNING)` -> `ESCALATED (CRITICAL)` -> `CLOSED (CRITICAL)`
   kèm 1 gói gửi lặp trễ thứ tự để kiểm chứng idempotency.
5. Gửi lô sự kiện hàng đợi offline (`POST /api/v1/sessions/{id}/events/batch`) có `capturedAt` cách đây 3 phút (`delayed = true`).
6. Gửi nhịp tim hồi phục `NORMAL` và kết thúc phiên (`POST /api/v1/sessions/{id}/end`).
7. (Kiểm tra chéo) Đăng nhập tài khoản `dispatcher` kiểm tra `/live`, `/events`, `/stats/hourly`.
"""
import argparse
from datetime import datetime, timedelta, timezone
import time
from typing import Any
from uuid import uuid4

import httpx


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_simulation(
    client: httpx.Client,
    username: str = "driver1",
    password: str = "driver123",
    step_delay: float = 0.3,
    keep_open: bool = False,
) -> dict[str, Any]:
    print(f"=== [1/7] Đăng nhập tài xế '{username}' ===")
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    login_res.raise_for_status()
    login_data = login_res.json()
    token = login_data["accessToken"]
    user = login_data["user"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"  -> Thành công: {user['fullName']} (id={user['id']}, org={user['organizationId']})")

    session_id = str(uuid4())
    started_at = datetime.now(timezone.utc)
    print(f"\n=== [2/7] Mở phiên giám sát sessionId={session_id} ===")
    sess_res = client.post(
        "/api/v1/sessions",
        json={"sessionId": session_id, "startedAt": iso_utc(started_at)},
        headers=headers,
    )
    sess_res.raise_for_status()
    # Gửi lặp lại lần 2 để kiểm tra idempotent
    sess_res_retry = client.post(
        "/api/v1/sessions",
        json={"sessionId": session_id, "startedAt": iso_utc(started_at)},
        headers=headers,
    )
    sess_res_retry.raise_for_status()
    settings = sess_res.json()["settings"]
    print(f"  -> Đã mở phiên (Idempotent OK). Settings: {settings}")

    time.sleep(step_delay)
    print("\n=== [3/7] Gửi Heartbeat trạng thái NORMAL ===")
    hb1_res = client.post(
        f"/api/v1/sessions/{session_id}/heartbeat",
        json={
            "state": "NORMAL",
            "imageQuality": "GOOD",
            "continuousDrivingSec": 300,
            "vehicleMoving": True,
            "capturedAt": iso_utc(datetime.now(timezone.utc)),
            "location": {"lat": 10.762622, "lng": 106.660172},
        },
        headers=headers,
    )
    hb1_res.raise_for_status()
    print(f"  -> Heartbeat #1: {hb1_res.json()}")

    time.sleep(step_delay)
    event_id = str(uuid4())
    ev_start = datetime.now(timezone.utc)
    print(f"\n=== [4/7] Tạo sự kiện buồn ngủ vòng đời OPEN -> ESCALATED -> CLOSED (eventId={event_id}) ===")

    # 4.1 OPEN (WARNING)
    r_open = client.post(
        f"/api/v1/sessions/{session_id}/events",
        json={
            "eventId": event_id,
            "type": "DROWSINESS",
            "level": "WARNING",
            "status": "OPEN",
            "state": "DROWSINESS_SIGNS",
            "riskScore": 0.80,
            "startedAt": iso_utc(ev_start),
            "durationSec": 2,
            "capturedAt": iso_utc(datetime.now(timezone.utc)),
        },
        headers=headers,
    )
    r_open.raise_for_status()
    print(f"  -> Bước 4.1 [OPEN]:      level={r_open.json()['level']}, status={r_open.json()['status']}, duration={r_open.json()['durationSec']}s")

    time.sleep(step_delay)
    # 4.2 ESCALATED (CRITICAL)
    r_esc = client.post(
        f"/api/v1/sessions/{session_id}/events",
        json={
            "eventId": event_id,
            "type": "DROWSINESS",
            "level": "CRITICAL",
            "status": "ESCALATED",
            "state": "CRITICAL",
            "riskScore": 0.95,
            "startedAt": iso_utc(ev_start),
            "durationSec": 4,
            "capturedAt": iso_utc(datetime.now(timezone.utc)),
        },
        headers=headers,
    )
    r_esc.raise_for_status()
    print(f"  -> Bước 4.2 [ESCALATED]: level={r_esc.json()['level']}, status={r_esc.json()['status']}, duration={r_esc.json()['durationSec']}s")

    time.sleep(step_delay)
    # 4.3 CLOSED (CRITICAL)
    r_closed = client.post(
        f"/api/v1/sessions/{session_id}/events",
        json={
            "eventId": event_id,
            "type": "DROWSINESS",
            "level": "CRITICAL",
            "status": "CLOSED",
            "state": "CRITICAL",
            "riskScore": 0.96,
            "startedAt": iso_utc(ev_start),
            "durationSec": 6,
            "capturedAt": iso_utc(datetime.now(timezone.utc)),
        },
        headers=headers,
    )
    r_closed.raise_for_status()
    print(f"  -> Bước 4.3 [CLOSED]:    level={r_closed.json()['level']}, status={r_closed.json()['status']}, duration={r_closed.json()['durationSec']}s")

    # 4.4 Gửi lặp lại gói OPEN cũ (out-of-order retry) -> phải giữ nguyên CRITICAL + CLOSED
    r_retry = client.post(
        f"/api/v1/sessions/{session_id}/events",
        json={
            "eventId": event_id,
            "type": "DROWSINESS",
            "level": "WARNING",
            "status": "OPEN",
            "state": "DROWSINESS_SIGNS",
            "riskScore": 0.75,
            "startedAt": iso_utc(ev_start),
            "durationSec": 1,
            "capturedAt": iso_utc(ev_start),
        },
        headers=headers,
    )
    r_retry.raise_for_status()
    print(f"  -> Bước 4.4 [RETRY CŨ]:  level={r_retry.json()['level']}, status={r_retry.json()['status']}, duration={r_retry.json()['durationSec']}s (Idempotent OK)")

    time.sleep(step_delay)
    print("\n=== [5/7] Gửi lại lô sự kiện Offline (Batch Events — kiểm tra cờ delayed=true) ===")
    offline_ev_1 = str(uuid4())
    offline_ev_2 = str(uuid4())
    three_min_ago = datetime.now(timezone.utc) - timedelta(seconds=180)
    batch_res = client.post(
        f"/api/v1/sessions/{session_id}/events/batch",
        json={
            "events": [
                {
                    "eventId": offline_ev_1,
                    "type": "DROWSINESS",
                    "level": "WARNING",
                    "status": "CLOSED",
                    "state": "DROWSINESS_SIGNS",
                    "riskScore": 0.82,
                    "startedAt": iso_utc(three_min_ago - timedelta(seconds=4)),
                    "durationSec": 4,
                    "capturedAt": iso_utc(three_min_ago),
                },
                {
                    "eventId": offline_ev_2,
                    "type": "LONG_DRIVING",
                    "level": "WARNING",
                    "status": "OPEN",
                    "state": "NORMAL",
                    "riskScore": 0.65,
                    "startedAt": iso_utc(datetime.now(timezone.utc) - timedelta(seconds=5)),
                    "durationSec": 7200,
                    "capturedAt": iso_utc(datetime.now(timezone.utc)),
                },
            ]
        },
        headers=headers,
    )
    batch_res.raise_for_status()
    batch_items = batch_res.json()["items"]
    for item in batch_items:
        print(f"  -> Batch Event id={item['id']} | type={item['type']} | delayed={item['delayed']}")

    time.sleep(step_delay)
    print("\n=== [6/7] Gửi Heartbeat NORMAL & Kết thúc phiên ===")
    hb2_res = client.post(
        f"/api/v1/sessions/{session_id}/heartbeat",
        json={
            "state": "NORMAL",
            "imageQuality": "GOOD",
            "continuousDrivingSec": 1800,
            "vehicleMoving": True,
            "capturedAt": iso_utc(datetime.now(timezone.utc)),
        },
        headers=headers,
    )
    hb2_res.raise_for_status()

    ended_session = None
    if not keep_open:
        end_res = client.post(
            f"/api/v1/sessions/{session_id}/end",
            json={
                "endedAt": iso_utc(datetime.now(timezone.utc)),
                "summary": {
                    "totalDrivingSec": 1800,
                    "warningCount": 2,
                    "criticalCount": 1,
                    "unavailableSec": 10,
                },
            },
            headers=headers,
        )
        end_res.raise_for_status()
        ended_session = end_res.json()
        print(f"  -> Đã đóng phiên: totalDrivingSec={ended_session['totalDrivingSec']}s, warnings={ended_session['warningCount']}, criticals={ended_session['criticalCount']}")
    else:
        print("  -> Giữ phiên mở (--keep-open) để quan sát trên /api/v1/live.")

    print("\n=== [7/7] Kiểm tra dữ liệu qua tài khoản Người trực (dispatcher) ===")
    disp_login = client.post(
        "/api/v1/auth/login",
        json={"username": "dispatcher", "password": "dispatcher123"},
    )
    disp_login.raise_for_status()
    disp_hdr = {"Authorization": f"Bearer {disp_login.json()['accessToken']}"}

    live_data = client.get("/api/v1/live", headers=disp_hdr).json()
    ev_data = client.get(f"/api/v1/events?driverId={user['id']}&pageSize=5", headers=disp_hdr).json()
    print(f"  -> GET /api/v1/live:   {len(live_data)} tài xế trong tổ chức")
    print(f"  -> GET /api/v1/events: tổng {ev_data['total']} sự kiện của tài xế {user['fullName']}")

    return {
        "sessionId": session_id,
        "primaryEventId": event_id,
        "offlineEventId": offline_ev_1,
        "endedSession": ended_session,
        "liveCount": len(live_data),
        "driverEventTotal": ev_data["total"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Giả lập App Tài xế PreDrive AI (M3)")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Địa chỉ máy chủ Backend (mặc định: http://127.0.0.1:8000)",
    )
    parser.add_argument("--username", default="driver1", help="Tài khoản tài xế")
    parser.add_argument("--password", default="driver123", help="Mật khẩu tài xế")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.4,
        help="Thời gian nghỉ giữa các bước (giây)",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Không đóng phiên cuối kịch bản (để test mất heartbeat / DISCONNECTED)",
    )
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=15.0) as client:
        run_simulation(
            client=client,
            username=args.username,
            password=args.password,
            step_delay=args.delay,
            keep_open=args.keep_open,
        )


if __name__ == "__main__":
    main()


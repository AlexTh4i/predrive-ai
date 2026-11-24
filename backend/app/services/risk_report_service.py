from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
from typing import Literal, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models.models import (
    EventModel,
    Organization,
    ReportModel,
    RiskScore,
    SessionModel,
    User,
)
from .mappers import VN_TZ, get_vehicle_name_map, to_vn_time


@dataclass
class RiskWeights:
    w_critical: float = 25.0
    w_drowsy: float = 12.0
    w_distraction: float = 6.0
    w_overtime: float = 10.0
    shift_hours_norm: float = 8.0

    @classmethod
    def from_env(cls) -> "RiskWeights":
        return cls(
            w_critical=float(os.getenv("RISK_WEIGHT_CRITICAL", "25.0")),
            w_drowsy=float(os.getenv("RISK_WEIGHT_DROWSY", "12.0")),
            w_distraction=float(os.getenv("RISK_WEIGHT_DISTRACTION", "6.0")),
            w_overtime=float(os.getenv("RISK_WEIGHT_OVERTIME", "10.0")),
            shift_hours_norm=max(1.0, float(os.getenv("RISK_SHIFT_HOURS_NORM", "8.0"))),
        )


def resolve_reports_base_dir() -> Path:
    env_dir = os.getenv("PREDRIVE_REPORTS_DIR", "").strip()
    if env_dir:
        base = Path(env_dir)
    else:
        base = Path(__file__).resolve().parents[2] / "data" / "reports"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _vn_date_bounds_utc(p_start: date, p_end: date) -> tuple[datetime, datetime]:
    start_vn = datetime.combine(p_start, time.min, tzinfo=VN_TZ)
    end_vn = datetime.combine(p_end, time.max, tzinfo=VN_TZ)
    return start_vn.astimezone(timezone.utc), end_vn.astimezone(timezone.utc)


def period_dates_for(
    period_type: Literal["shift", "weekly", "monthly"],
    ref_date: Optional[date] = None,
) -> tuple[date, date]:
    d_end = ref_date or to_vn_time(datetime.now(timezone.utc)).date()
    if period_type == "shift":
        return d_end, d_end
    if period_type == "weekly":
        return d_end - timedelta(days=6), d_end
    return d_end - timedelta(days=29), d_end


def classify_risk_level(score: int) -> Literal["low", "medium", "high"]:
    if score >= 70:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def compute_organization_risk_scores(
    db: Session,
    org_id: str,
    period_type: Literal["shift", "weekly", "monthly"] = "weekly",
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    weights: Optional[RiskWeights] = None,
) -> list[RiskScore]:
    """Compute and upsert `risk_scores` for every driver in `org_id` over `[period_start, period_end]`."""
    w = weights or RiskWeights.from_env()
    def_start, def_end = period_dates_for(period_type)
    p_start = period_start or def_start
    p_end = period_end or def_end
    start_utc, end_utc = _vn_date_bounds_utc(p_start, p_end)

    drivers = db.scalars(
        select(User)
        .where(User.organization_id == org_id, User.role == "driver")
        .order_by(User.full_name.asc())
    ).all()

    results: list[RiskScore] = []
    for drv in drivers:
        sessions = db.scalars(
            select(SessionModel).where(
                SessionModel.organization_id == org_id,
                SessionModel.driver_id == drv.id,
                SessionModel.started_at >= start_utc,
                SessionModel.started_at <= end_utc,
            )
        ).all()
        total_sec = sum(max(int(s.total_driving_sec or 0), int(s.continuous_driving_sec or 0)) for s in sessions)
        driving_hours_float = round(total_sec / 3600.0, 1)

        events = db.scalars(
            select(EventModel).where(
                EventModel.organization_id == org_id,
                EventModel.driver_id == drv.id,
                EventModel.occurred_at >= start_utc,
                EventModel.occurred_at <= end_utc,
                or_(
                    EventModel.driver_feedback.is_(None),
                    EventModel.driver_feedback != "false_alarm",
                ),
            )
        ).all()

        events_count = len(events)
        critical_cnt = sum(1 for e in events if int(e.level) >= 3)
        drowsy_cnt = sum(
            1 for e in events if e.type in ("DROWSINESS", "DROWSY", "HEAD_DOWN")
        )
        drowsy_non_crit = sum(
            1
            for e in events
            if e.type in ("DROWSINESS", "DROWSY", "HEAD_DOWN") and int(e.level) < 3
        )
        distract_cnt = sum(1 for e in events if e.type == "DISTRACTED")
        overtime_cnt = sum(
            1 for e in events if e.type in ("LONG_DRIVING", "REST_CLAIM_REJECTED")
        )

        weighted_pts = (
            w.w_critical * critical_cnt
            + w.w_drowsy * drowsy_non_crit
            + w.w_distraction * distract_cnt
            + w.w_overtime * overtime_cnt
        )
        exposure = max(1.0, driving_hours_float / max(1.0, w.shift_hours_norm))
        score_val = min(100, max(0, int(round(weighted_pts / exposure))))
        lvl = classify_risk_level(score_val)

        existing = db.scalar(
            select(RiskScore).where(
                RiskScore.organization_id == org_id,
                RiskScore.driver_id == drv.id,
                RiskScore.period_type == period_type,
                RiskScore.period_start == p_start,
            )
        )
        if existing is not None:
            existing.period_end = p_end
            existing.score = score_val
            existing.risk_level = lvl
            existing.events_count = events_count
            existing.drowsy_events = drowsy_cnt
            existing.distraction_events = distract_cnt
            existing.driving_hours = Decimal(f"{driving_hours_float:.1f}")
            row = existing
        else:
            row = RiskScore(
                organization_id=org_id,
                driver_id=drv.id,
                period_type=period_type,
                period_start=p_start,
                period_end=p_end,
                score=score_val,
                risk_level=lvl,
                events_count=events_count,
                drowsy_events=drowsy_cnt,
                distraction_events=distract_cnt,
                driving_hours=Decimal(f"{driving_hours_float:.1f}"),
            )
            db.add(row)
        results.append(row)

    db.commit()
    for r in results:
        db.refresh(r)
    return results


@dataclass
class DriverReportRow:
    driver_id: str
    full_name: str
    vehicle_name: str
    sessions_count: int
    driving_hours: float
    events_total: int
    critical_count: int
    drowsy_count: int
    distracted_count: int
    risk_score: int
    risk_level: str


def build_report_dataset(
    db: Session,
    org_id: str,
    report_type: Literal["weekly", "monthly"],
    p_start: date,
    p_end: date,
) -> tuple[str, list[DriverReportRow]]:
    org = db.get(Organization, org_id)
    org_name = org.name if org else org_id
    vehicle_map = get_vehicle_name_map(db, org_id)
    start_utc, end_utc = _vn_date_bounds_utc(p_start, p_end)

    score_rows = compute_organization_risk_scores(
        db=db,
        org_id=org_id,
        period_type=report_type,
        period_start=p_start,
        period_end=p_end,
    )
    score_by_drv = {r.driver_id: r for r in score_rows}

    drivers = db.scalars(
        select(User)
        .where(User.organization_id == org_id, User.role == "driver")
        .order_by(User.full_name.asc())
    ).all()

    rows: list[DriverReportRow] = []
    for drv in drivers:
        sessions = db.scalars(
            select(SessionModel).where(
                SessionModel.organization_id == org_id,
                SessionModel.driver_id == drv.id,
                SessionModel.started_at >= start_utc,
                SessionModel.started_at <= end_utc,
            )
        ).all()
        events = db.scalars(
            select(EventModel).where(
                EventModel.organization_id == org_id,
                EventModel.driver_id == drv.id,
                EventModel.occurred_at >= start_utc,
                EventModel.occurred_at <= end_utc,
            )
        ).all()
        total_sec = sum(max(int(s.total_driving_sec or 0), int(s.continuous_driving_sec or 0)) for s in sessions)
        drv_hours = round(total_sec / 3600.0, 1)
        crit_cnt = sum(1 for e in events if int(e.level) >= 3)
        drowsy_cnt = sum(
            1 for e in events if e.type in ("DROWSINESS", "DROWSY", "HEAD_DOWN")
        )
        dist_cnt = sum(1 for e in events if e.type == "DISTRACTED")
        rs = score_by_drv.get(drv.id)
        v_name = vehicle_map.get(drv.vehicle_id, "Chua phan xe") if drv.vehicle_id else "Chua phan xe"

        rows.append(
            DriverReportRow(
                driver_id=drv.id,
                full_name=drv.full_name,
                vehicle_name=v_name,
                sessions_count=len(sessions),
                driving_hours=drv_hours,
                events_total=len(events),
                critical_count=crit_cnt,
                drowsy_count=drowsy_cnt,
                distracted_count=dist_cnt,
                risk_score=int(rs.score) if rs else 0,
                risk_level=str(rs.risk_level) if rs else "low",
            )
        )

    return org_name, rows


def generate_report_file(
    db: Session,
    report: ReportModel,
) -> Path:
    """Render `.xlsx` or `.pdf` safety report file on disk and return its absolute Path."""
    org_name, rows = build_report_dataset(
        db=db,
        org_id=report.organization_id,
        report_type=report.report_type,  # type: ignore[arg-type]
        p_start=report.period_start,
        p_end=report.period_end,
    )

    out_dir = resolve_reports_base_dir() / report.organization_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{report.id}.{report.file_format}"

    total_sessions = sum(r.sessions_count for r in rows)
    total_hours = round(sum(r.driving_hours for r in rows), 1)
    total_events = sum(r.events_total for r in rows)
    total_critical = sum(r.critical_count for r in rows)

    if report.file_format == "xlsx":
        wb = Workbook()
        ws_sum = wb.active
        assert ws_sum is not None
        ws_sum.title = "TongHop"

        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="00804A", end_color="00804A", fill_type="solid")

        ws_sum.append(["PreDrive AI - Bao cao an toan doi xe"])
        ws_sum["A1"].font = Font(bold=True, size=14)
        ws_sum.append(["To chuc", org_name])
        ws_sum.append(["Ky bao cao", report.report_type])
        ws_sum.append(["Tu ngay", report.period_start.isoformat()])
        ws_sum.append(["Den ngay", report.period_end.isoformat()])
        ws_sum.append(["Tong tai xe", len(rows)])
        ws_sum.append(["Tong phien lai", total_sessions])
        ws_sum.append(["Tong gio lai", total_hours])
        ws_sum.append(["Tong su kien", total_events])
        ws_sum.append(["Tong nguy hiem (Muc 3)", total_critical])

        ws_drv = wb.create_sheet(title="ChiTietTaiXe")
        cols = [
            "Driver ID",
            "Ho va ten",
            "Phuong tien",
            "So phien",
            "Gio lai",
            "Tong su kien",
            "Nguy hiem",
            "Buon ngu",
            "Mat tap trung",
            "Diem rui ro",
            "Muc rui ro",
        ]
        ws_drv.append(cols)
        for cell in ws_drv[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        for r in rows:
            ws_drv.append(
                [
                    r.driver_id,
                    r.full_name,
                    r.vehicle_name,
                    r.sessions_count,
                    r.driving_hours,
                    r.events_total,
                    r.critical_count,
                    r.drowsy_count,
                    r.distracted_count,
                    r.risk_score,
                    r.risk_level,
                ]
            )
        wb.save(out_path)
        return out_path

    # PDF generation via ReportLab
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(out_path), pagesize=A4)
    story = [
        Paragraph("<b>PreDrive AI - Fleet Safety &amp; Risk Report</b>", styles["Title"]),
        Spacer(1, 8),
        Paragraph(
            f"Organization ID: {report.organization_id} | Period: {report.period_start.isoformat()} to {report.period_end.isoformat()} ({report.report_type})",
            styles["Normal"],
        ),
        Paragraph(
            f"Drivers: {len(rows)} | Sessions: {total_sessions} | Driving Hours: {total_hours} | Total Events: {total_events} | Critical: {total_critical}",
            styles["Normal"],
        ),
        Spacer(1, 14),
    ]

    table_data = [
        ["Driver ID (short)", "Hours", "Sessions", "Events", "Critical", "Score", "Risk Level"]
    ]
    for r in rows:
        table_data.append(
            [
                r.driver_id[:8],
                f"{r.driving_hours:.1f}",
                str(r.sessions_count),
                str(r.events_total),
                str(r.critical_count),
                str(r.risk_score),
                r.risk_level.upper(),
            ]
        )

    tbl = Table(table_data, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#00804A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
            ]
        )
    )
    story.append(tbl)
    doc.build(story)
    return out_path

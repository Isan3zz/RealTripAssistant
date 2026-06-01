"""
api/export.py — 导出 API

支持 Markdown / PDF / ICS 格式导出。
Phase 3 基础版：Markdown + ICS，PDF 用 weasyprint 可选。
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from travel_planning_agent.config import settings
from travel_planning_agent.db.session import get_db
from travel_planning_agent.db.models import Trip, PlanVersion

router = APIRouter(prefix="/api", tags=["导出"])


class ExportRequest(BaseModel):
    format: str = "markdown"  # markdown / pdf / ics
    plan_id: Optional[str] = None


@router.post("/trips/{trip_id}/export")
def export_trip(trip_id: str, req: ExportRequest, db: DBSession = Depends(get_db)):
    """导出行程。"""
    t = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not t:
        raise HTTPException(404, "行程不存在")

    # 获取方案
    if req.plan_id:
        plan = db.query(PlanVersion).filter(
            PlanVersion.plan_id == req.plan_id,
            PlanVersion.trip_id == trip_id,
        ).first()
    else:
        plan = db.query(PlanVersion).filter(
            PlanVersion.trip_id == trip_id,
            PlanVersion.is_active == True,
        ).first()

    if not plan:
        raise HTTPException(404, "方案不存在，请先生成方案")

    # 创建导出目录
    export_dir = Path(settings.data_dir) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    export_id = f"export_{trip_id[:8]}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    if req.format == "markdown":
        content = _generate_markdown(t, plan)
        filename = f"{export_id}.md"
    elif req.format == "ics":
        content = _generate_ics(t, plan)
        filename = f"{export_id}.ics"
    else:
        raise HTTPException(400, f"不支持的导出格式: {req.format}")

    filepath = export_dir / filename
    filepath.write_text(content, encoding="utf-8")

    return {
        "export_id": export_id,
        "download_url": f"/api/exports/{export_id}/download",
        "format": req.format,
        "filename": filename,
    }


@router.get("/exports/{export_id}/download")
def download_export(export_id: str):
    """下载导出文件。"""
    export_dir = Path(settings.data_dir) / "exports"
    for f in export_dir.iterdir():
        if f.name.startswith(export_id):
            return FileResponse(str(f), filename=f.name)
    raise HTTPException(404, "导出文件不存在或已过期")


def _generate_markdown(trip: Trip, plan: PlanVersion) -> str:
    """生成 Markdown 导出。"""
    data = plan.plan_data
    lines = [
        "---",
        f"destination: {trip.destination}",
        f"dates: {trip.start_date} ~ {trip.start_date}",
        f"budget: {trip.budget} CNY",
        f"pace: {trip.pace}",
        f"status: completed",
        "---",
        "",
    ]

    _cat_map = {
        "transport": "路程",
        "activity": "游玩",
        "meal": "用餐",
        "accommodation": "住宿",
    }
    for day in data.get("days", []):
        lines.append(f"## Day {day['day_number']} — {day.get('theme', '')}")
        lines.append("")
        prev_type = None
        for seg in day.get("segments", []):
            # 添加分类小标题
            seg_type = seg.get("type", "")
            if seg_type != prev_type:
                cat_name = _cat_map.get(seg_type)
                if cat_name:
                    lines.append(f"### {cat_name}")
                prev_type = seg_type

            time_str = ""
            if seg.get("start_time") and seg.get("end_time"):
                time_str = f"{seg['start_time']}-{seg['end_time']}  "
            cost = ""
            if seg.get("estimated_cost") and seg["estimated_cost"].get("amount", 0) > 0:
                cost = f" (¥{seg['estimated_cost']['amount']:,.0f})"
            tags = f" [{', '.join(seg.get('tags', []))}]" if seg.get("tags") else ""
            lines.append(f"- {time_str}{seg['title']}{cost}{tags}")
        lines.append("")

    return "\n".join(lines)


def _generate_ics(trip: Trip, plan: PlanVersion) -> str:
    """生成 ICS 日历导出（简化版）。"""
    from datetime import timedelta

    data = plan.plan_data
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//RealTrip Assistant//CN",
    ]

    day_offset = 0
    for day in data.get("days", []):
        date_obj = trip.start_date + timedelta(days=day_offset)
        for seg in day.get("segments", []):
            if not seg.get("start_time") or not seg.get("end_time"):
                continue
            dt_start = f"{date_obj.isoformat()}T{seg['start_time'].replace(':', '')}00"
            dt_end = f"{date_obj.isoformat()}T{seg['end_time'].replace(':', '')}00"
            lines.extend([
                "BEGIN:VEVENT",
                f"DTSTART:{dt_start}",
                f"DTEND:{dt_end}",
                f"SUMMARY:{seg['title']}",
                f"DESCRIPTION:{' - '.join(seg.get('tags', []))}",
                "END:VEVENT",
            ])
        day_offset += 1

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)

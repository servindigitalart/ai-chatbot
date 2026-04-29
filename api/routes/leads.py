from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from core.database import get_supabase

router = APIRouter(prefix="/leads", tags=["leads"])
logger = structlog.get_logger()


class LeadStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None


@router.get("")
async def list_leads(
    clinic_id: Optional[str] = None,
    status: Optional[str] = None,
    is_hot: Optional[bool] = None,
    days: int = 30,
    limit: int = 50,
    offset: int = 0,
):
    db = get_supabase()

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    q = (
        db.from_("chatbot_leads")
        .select("*, chatbot_sessions(message_count, source_url, source_surface)")
        .gte("created_at", since)
        .order("qualification_score", desc=True)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if clinic_id:
        q = q.eq("clinic_id", clinic_id)
    if status:
        q = q.eq("status", status)
    if is_hot is not None:
        q = q.eq("is_hot", is_hot)

    res = q.execute()
    leads = res.data or []

    # Counts for summary
    count_q = (
        db.from_("chatbot_leads")
        .select("id, is_hot, status", count="exact")
        .gte("created_at", since)
    )
    if clinic_id:
        count_q = count_q.eq("clinic_id", clinic_id)
    count_res = count_q.execute()
    all_leads = count_res.data or []

    hot_count = sum(1 for l in all_leads if l.get("is_hot"))
    new_count = sum(1 for l in all_leads if l.get("status") == "new")

    return {
        "leads": leads,
        "total": count_res.count or len(all_leads),
        "hot_count": hot_count,
        "new_count": new_count,
    }


@router.get("/export")
async def export_leads(
    clinic_id: Optional[str] = None,
    status: Optional[str] = None,
    days: int = 30,
):
    db = get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    q = (
        db.from_("chatbot_leads")
        .select("name, email, phone, service_interest, qualification_score, status, created_at")
        .gte("created_at", since)
        .order("created_at", desc=True)
    )
    if clinic_id:
        q = q.eq("clinic_id", clinic_id)
    if status:
        q = q.eq("status", status)

    res = q.execute()
    leads = res.data or []

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"leads-{clinic_id or 'all'}-{date_str}.csv"

    lines = ["name,email,phone,service_interest,score,status,date"]
    for lead in leads:
        row = ",".join([
            _csv_field(lead.get("name")),
            _csv_field(lead.get("email")),
            _csv_field(lead.get("phone")),
            _csv_field(lead.get("service_interest")),
            str(lead.get("qualification_score", 0)),
            _csv_field(lead.get("status")),
            _csv_field((lead.get("created_at") or "")[:10]),
        ])
        lines.append(row)

    csv_body = "\n".join(lines)
    return Response(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{lead_id}")
async def get_lead(lead_id: str):
    db = get_supabase()

    lead_res = db.from_("chatbot_leads").select("*").eq("id", lead_id).execute()
    if not lead_res.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead = lead_res.data[0]

    session_res = (
        db.from_("chatbot_sessions")
        .select("*")
        .eq("id", lead.get("session_id"))
        .execute()
    )
    session = session_res.data[0] if session_res.data else None

    messages: list = []
    if session:
        msgs_res = (
            db.from_("chatbot_messages")
            .select("*")
            .eq("session_id", session["id"])
            .order("created_at")
            .execute()
        )
        messages = msgs_res.data or []

    return {"lead": lead, "session": session, "messages": messages}


@router.put("/{lead_id}")
async def update_lead(lead_id: str, body: LeadStatusUpdate):
    db = get_supabase()

    valid_statuses = ("new", "contacted", "converted", "lost")
    if body.status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {valid_statuses}",
        )

    updates = {"status": body.status}
    if body.notes is not None:
        updates["notes"] = body.notes

    res = db.from_("chatbot_leads").update(updates).eq("id", lead_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    return res.data[0]


def _csv_field(value) -> str:
    if value is None:
        return ""
    val = str(value).replace('"', '""')
    if "," in val or '"' in val:
        return f'"{val}"'
    return val

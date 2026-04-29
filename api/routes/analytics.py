from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter

from core.database import get_supabase

router = APIRouter(prefix="/analytics", tags=["analytics"])
logger = structlog.get_logger()


@router.get("/overview")
async def overview(clinic_id: Optional[str] = None, days: int = 30):
    db = get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Sessions
    sessions_q = (
        db.from_("chatbot_sessions")
        .select("id, status, message_count, lead_captured, qualification_score, enrolled_in_sequence, started_at")
        .gte("started_at", since)
    )
    if clinic_id:
        sessions_q = sessions_q.eq("clinic_id", clinic_id)
    sessions_res = sessions_q.execute()
    sessions = sessions_res.data or []

    total_sessions = len(sessions)
    completed = sum(1 for s in sessions if s.get("status") == "completed")
    abandoned = sum(1 for s in sessions if s.get("status") == "abandoned")
    completion_rate = round(completed / total_sessions, 3) if total_sessions else 0.0
    msg_counts = [s.get("message_count", 0) for s in sessions]
    avg_messages = round(sum(msg_counts) / len(msg_counts), 1) if msg_counts else 0.0

    # Leads
    leads_q = (
        db.from_("chatbot_leads")
        .select("id, qualification_score, is_hot, enrolled_in_sequence")
        .gte("created_at", since)
    )
    if clinic_id:
        leads_q = leads_q.eq("clinic_id", clinic_id)
    leads_res = leads_q.execute()
    leads = leads_res.data or []

    total_leads = len(leads)
    hot = sum(1 for l in leads if l.get("qualification_score", 0) >= 70)
    warm = sum(1 for l in leads if 40 <= l.get("qualification_score", 0) < 70)
    cold = sum(1 for l in leads if l.get("qualification_score", 0) < 40)
    capture_rate = round(total_leads / total_sessions, 3) if total_sessions else 0.0
    enrolled = sum(1 for l in leads if l.get("enrolled_in_sequence"))

    scores = [l.get("qualification_score", 0) for l in leads]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0

    # Top service interests
    si_q = (
        db.from_("chatbot_sessions")
        .select("service_interest")
        .gte("started_at", since)
        .not_.is_("service_interest", "null")
    )
    if clinic_id:
        si_q = si_q.eq("clinic_id", clinic_id)
    si_res = si_q.execute()
    si_counter = Counter(
        s["service_interest"] for s in (si_res.data or []) if s.get("service_interest")
    )
    top_service_interests = [
        {"service": svc, "count": cnt}
        for svc, cnt in si_counter.most_common(5)
    ]

    # Top intents from messages
    if clinic_id:
        session_ids = [s["id"] for s in sessions]
        if session_ids:
            intents_res = (
                db.from_("chatbot_messages")
                .select("intent")
                .in_("session_id", session_ids[:100])  # cap to avoid huge IN clause
                .not_.is_("intent", "null")
                .execute()
            )
            intent_counter = Counter(
                m["intent"] for m in (intents_res.data or []) if m.get("intent")
            )
        else:
            intent_counter: Counter = Counter()
    else:
        intent_counter = Counter()

    top_intents = [
        {"intent": intent, "count": cnt}
        for intent, cnt in intent_counter.most_common(5)
    ]

    # Daily sessions — last 14 days
    daily_sessions = _build_daily_buckets(sessions, days=min(days, 14))

    return {
        "period": f"last_{days}_days",
        # Top-level aliases for backward compatibility
        "total_sessions": total_sessions,
        "leads_captured": total_leads,
        "avg_messages_per_session": avg_messages,
        "sessions": {
            "total": total_sessions,
            "completed": completed,
            "abandoned": abandoned,
            "completion_rate": completion_rate,
            "avg_messages_per_session": avg_messages,
        },
        "leads": {
            "total": total_leads,
            "hot": hot,
            "warm": warm,
            "cold": cold,
            "capture_rate": capture_rate,
            "enrolled_in_email": enrolled,
        },
        "top_service_interests": top_service_interests,
        "top_intents": top_intents,
        "daily_sessions": daily_sessions,
        "avg_qualification_score": avg_score,
    }


@router.get("/sessions")
async def list_sessions(clinic_id: Optional[str] = None, days: int = 7):
    db = get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    q = (
        db.from_("chatbot_sessions")
        .select(
            "id, started_at, message_count, lead_captured, "
            "qualification_score, service_interest, source_url, status"
        )
        .gte("started_at", since)
        .order("started_at", desc=True)
        .limit(50)
    )
    if clinic_id:
        q = q.eq("clinic_id", clinic_id)

    res = q.execute()
    return res.data or []


def _build_daily_buckets(sessions: list, days: int = 14) -> list:
    """Build per-day session counts for the last N days."""
    now = datetime.now(timezone.utc).date()
    buckets: dict[str, dict] = {}
    for i in range(days - 1, -1, -1):
        d = (now - timedelta(days=i)).isoformat()
        buckets[d] = {"date": d, "sessions": 0, "leads": 0}

    for s in sessions:
        started = s.get("started_at", "")
        if started:
            day = started[:10]
            if day in buckets:
                buckets[day]["sessions"] += 1
                if s.get("lead_captured"):
                    buckets[day]["leads"] += 1

    return list(buckets.values())

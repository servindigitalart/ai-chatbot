from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.chat_agent import ChatAgent
from connectors.email_marketing import EmailMarketingConnector
from core.database import get_supabase

router = APIRouter(prefix="/chat", tags=["chat"])
logger = structlog.get_logger()


class SessionCreate(BaseModel):
    clinic_id: str
    source_url: Optional[str] = None
    source_surface: str = "widget"
    visitor_id: Optional[str] = None


class MessageRequest(BaseModel):
    content: str
    visitor_id: Optional[str] = None


class LeadUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    service_interest: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _capture_lead_row(
    clinic_id: str,
    session_id: str,
    lead_info: dict,
    score: int,
) -> dict:
    return {
        "clinic_id": clinic_id,
        "session_id": session_id,
        "name": lead_info.get("name"),
        "email": lead_info.get("email"),
        "phone": lead_info.get("phone"),
        "service_interest": lead_info.get("service_interest"),
        "notes": lead_info.get("notes"),
        "qualification_score": score,
        "is_hot": score >= 70,
        "status": "new",
    }


@router.post("/session")
async def create_session(body: SessionCreate):
    db = get_supabase()

    config_res = (
        db.from_("chatbot_configs")
        .select("*")
        .eq("clinic_id", body.clinic_id)
        .eq("is_active", True)
        .execute()
    )
    if not config_res.data:
        raise HTTPException(
            status_code=404,
            detail="Chatbot not configured for this clinic",
        )
    config = config_res.data[0]

    session_res = (
        db.from_("chatbot_sessions")
        .insert({
            "clinic_id": body.clinic_id,
            "config_id": config["id"],
            "visitor_id": body.visitor_id,
            "source_url": body.source_url,
            "source_surface": body.source_surface,
            "status": "active",
            "message_count": 0,
            "started_at": _now(),
            "last_message_at": _now(),
        })
        .execute()
    )
    session = session_res.data[0]
    session_id = session["id"]

    db.from_("chatbot_messages").insert({
        "session_id": session_id,
        "role": "assistant",
        "content": config["welcome_message"],
        "intent": "greeting",
    }).execute()

    return {
        "session_id": session_id,
        "bot_name": config.get("bot_name", "Assistant"),
        "welcome_message": config["welcome_message"],
        "primary_color": config.get("primary_color", "#007AE6"),
        "config": {
            "capture_name": config.get("capture_name", True),
            "capture_email": config.get("capture_email", True),
            "capture_phone": config.get("capture_phone", True),
            "scheduling_enabled": config.get("scheduling_enabled", False),
            "scheduling_url": config.get("scheduling_url"),
            "scheduling_button_text": config.get(
                "scheduling_button_text", "Book Appointment"
            ),
        },
    }


@router.post("/session/{session_id}/message")
async def send_message(session_id: str, body: MessageRequest):
    db = get_supabase()

    # Fetch session + config together
    session_res = (
        db.from_("chatbot_sessions")
        .select("*")
        .eq("id", session_id)
        .execute()
    )
    if not session_res.data:
        raise HTTPException(status_code=404, detail="Session not found")
    session = session_res.data[0]
    if session.get("status") != "active":
        raise HTTPException(status_code=400, detail="Session is not active")

    config_res = (
        db.from_("chatbot_configs")
        .select("*")
        .eq("id", session["config_id"])
        .execute()
    )
    if not config_res.data:
        raise HTTPException(status_code=404, detail="Config not found")
    config = config_res.data[0]

    # Fetch last 10 messages for context
    history_res = (
        db.from_("chatbot_messages")
        .select("role, content")
        .eq("session_id", session_id)
        .order("created_at")
        .limit(10)
        .execute()
    )
    history = history_res.data or []

    # Insert user message
    db.from_("chatbot_messages").insert({
        "session_id": session_id,
        "role": "user",
        "content": body.content,
    }).execute()

    # Get AI reply
    agent = ChatAgent(config=config)
    result = await agent.get_reply(
        message=body.content,
        history=history,
        session=session,
    )

    # Insert assistant message
    db.from_("chatbot_messages").insert({
        "session_id": session_id,
        "role": "assistant",
        "content": result["reply"],
        "intent": result["intent"],
        "confidence": result["confidence"],
    }).execute()

    # Increment message count
    new_count = session.get("message_count", 0) + 1
    db.from_("chatbot_sessions").update({
        "message_count": new_count,
        "last_message_at": _now(),
    }).eq("id", session_id).execute()

    # Extract lead info from full conversation so far
    all_msgs_res = (
        db.from_("chatbot_messages")
        .select("role, content")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )
    all_messages = all_msgs_res.data or []

    lead_info = await agent.extract_lead_info(all_messages)
    score = agent.calculate_qualification_score(
        {**session, "message_count": new_count}, lead_info
    )

    # Update session with any newly discovered lead fields
    session_updates: dict = {
        "qualification_score": score,
        "is_qualified": score >= 40,
    }
    if lead_info.get("name") and not session.get("contact_name"):
        session_updates["contact_name"] = lead_info["name"]
    if lead_info.get("email") and not session.get("contact_email"):
        session_updates["contact_email"] = lead_info["email"]
    if lead_info.get("phone") and not session.get("contact_phone"):
        session_updates["contact_phone"] = lead_info["phone"]
    if lead_info.get("service_interest") and not session.get("service_interest"):
        session_updates["service_interest"] = lead_info["service_interest"]
    db.from_("chatbot_sessions").update(session_updates).eq("id", session_id).execute()

    # Lead capture: email newly found for the first time
    lead_just_captured = False
    email_newly_captured = (
        lead_info.get("email")
        and not session.get("contact_email")
        and not session.get("lead_captured")
    )
    if email_newly_captured:
        lead_row = _capture_lead_row(
            session["clinic_id"], session_id, lead_info, score
        )
        lead_res = db.from_("chatbot_leads").insert(lead_row).execute()
        lead_id = lead_res.data[0]["id"] if lead_res.data else None

        connector = EmailMarketingConnector()
        enroll_result = await connector.enroll_lead(
            session["clinic_id"],
            {**lead_info, "session_id": session_id},
        )
        enrolled = enroll_result.get("status") in ("created", "updated")

        db.from_("chatbot_sessions").update({
            "lead_captured": True,
            "enrolled_in_sequence": enrolled,
        }).eq("id", session_id).execute()

        if enroll_result.get("id") and lead_id:
            db.from_("chatbot_leads").update({
                "email_contact_id": enroll_result["id"],
                "enrolled_in_sequence": enrolled,
            }).eq("id", lead_id).execute()

        lead_just_captured = True
        logger.info(
            "lead_captured",
            session_id=session_id,
            email=lead_info["email"],
            score=score,
            enrolled=enrolled,
        )

    return {
        "reply": result["reply"],
        "intent": result["intent"],
        "session_id": session_id,
        "lead_captured": lead_just_captured,
        "suggested_actions": result["suggested_actions"],
        "qualification_score": score,
    }


@router.get("/session/{session_id}")
async def get_session(session_id: str):
    db = get_supabase()

    session_res = (
        db.from_("chatbot_sessions").select("*").eq("id", session_id).execute()
    )
    if not session_res.data:
        raise HTTPException(status_code=404, detail="Session not found")
    session = session_res.data[0]

    messages_res = (
        db.from_("chatbot_messages")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )

    lead_res = (
        db.from_("chatbot_leads").select("*").eq("session_id", session_id).execute()
    )

    return {
        "session": session,
        "messages": messages_res.data or [],
        "lead": lead_res.data[0] if lead_res.data else None,
    }


@router.patch("/session/{session_id}")
async def update_session(session_id: str, body: LeadUpdate):
    db = get_supabase()

    session_res = (
        db.from_("chatbot_sessions").select("*").eq("id", session_id).execute()
    )
    if not session_res.data:
        raise HTTPException(status_code=404, detail="Session not found")
    session = session_res.data[0]

    updates: dict = {}
    if body.name and not session.get("contact_name"):
        updates["contact_name"] = body.name
    if body.email and not session.get("contact_email"):
        updates["contact_email"] = body.email
    if body.phone and not session.get("contact_phone"):
        updates["contact_phone"] = body.phone
    if body.service_interest and not session.get("service_interest"):
        updates["service_interest"] = body.service_interest

    if updates:
        db.from_("chatbot_sessions").update(updates).eq("id", session_id).execute()

    # Trigger lead capture if email provided for first time
    email_newly_captured = (
        body.email
        and not session.get("contact_email")
        and not session.get("lead_captured")
    )
    if email_newly_captured:
        lead_info = {
            "name": body.name or session.get("contact_name"),
            "email": body.email,
            "phone": body.phone or session.get("contact_phone"),
            "service_interest": body.service_interest or session.get("service_interest"),
            "urgency": None,
            "notes": None,
        }
        score = 0
        if lead_info.get("service_interest"):
            score += 30
        if lead_info.get("email"):
            score += 20
        if lead_info.get("phone"):
            score += 15
        if lead_info.get("name"):
            score += 10

        lead_row = _capture_lead_row(
            session["clinic_id"], session_id, lead_info, score
        )
        lead_res = db.from_("chatbot_leads").insert(lead_row).execute()
        lead_id = lead_res.data[0]["id"] if lead_res.data else None

        connector = EmailMarketingConnector()
        enroll_result = await connector.enroll_lead(
            session["clinic_id"],
            {**lead_info, "session_id": session_id},
        )
        enrolled = enroll_result.get("status") in ("created", "updated")

        db.from_("chatbot_sessions").update({
            "lead_captured": True,
            "enrolled_in_sequence": enrolled,
        }).eq("id", session_id).execute()

        if enroll_result.get("id") and lead_id:
            db.from_("chatbot_leads").update({
                "email_contact_id": enroll_result["id"],
                "enrolled_in_sequence": enrolled,
            }).eq("id", lead_id).execute()

    updated = db.from_("chatbot_sessions").select("*").eq("id", session_id).execute()
    return updated.data[0] if updated.data else {}


@router.post("/session/{session_id}/end")
async def end_session(session_id: str):
    db = get_supabase()

    session_res = (
        db.from_("chatbot_sessions").select("lead_captured").eq("id", session_id).execute()
    )
    if not session_res.data:
        raise HTTPException(status_code=404, detail="Session not found")

    db.from_("chatbot_sessions").update({
        "status": "completed",
        "completed_at": _now(),
    }).eq("id", session_id).execute()

    return {
        "completed": True,
        "lead_captured": session_res.data[0].get("lead_captured", False),
    }

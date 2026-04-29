from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.config_agent import ConfigAgent
from core.config import settings
from core.database import get_supabase

router = APIRouter(prefix="/config", tags=["config"])
logger = structlog.get_logger()


class ConfigGenerateRequest(BaseModel):
    clinic_id: str
    force_regenerate: bool = False


class ConfigUpdateRequest(BaseModel):
    bot_name: Optional[str] = None
    welcome_message: Optional[str] = None
    fallback_message: Optional[str] = None
    tone: Optional[str] = None
    system_prompt: Optional[str] = None
    capture_name: Optional[bool] = None
    capture_email: Optional[bool] = None
    capture_phone: Optional[bool] = None
    require_email_before_chat: Optional[bool] = None
    services: Optional[list[str]] = None
    primary_color: Optional[str] = None
    widget_position: Optional[str] = None
    scheduling_enabled: Optional[bool] = None
    scheduling_url: Optional[str] = None
    scheduling_button_text: Optional[str] = None
    auto_enroll_leads: Optional[bool] = None
    is_active: Optional[bool] = None


class FAQCreate(BaseModel):
    question: str
    answer: str
    category: Optional[str] = None
    display_order: int = 0


class FAQUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class FAQReorderRequest(BaseModel):
    faq_ids: list[str]


def _generate_embed_code(clinic_id: str) -> str:
    return (
        f'<script src="{settings.widget_base_url}/static/widget.js" '
        f'data-clinic-id="{clinic_id}" async></script>'
    )


def _sync_faqs_to_config(clinic_id: str) -> None:
    """Keep chatbot_configs.faqs JSONB in sync with chatbot_faqs table."""
    db = get_supabase()
    faqs_res = (
        db.from_("chatbot_faqs")
        .select("question, answer, category")
        .eq("clinic_id", clinic_id)
        .eq("is_active", True)
        .order("display_order")
        .execute()
    )
    db.from_("chatbot_configs").update({"faqs": faqs_res.data}).eq(
        "clinic_id", clinic_id
    ).execute()


@router.get("/{clinic_id}")
async def get_config(clinic_id: str):
    db = get_supabase()
    res = (
        db.from_("chatbot_configs").select("*").eq("clinic_id", clinic_id).execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=404,
            detail="No config found. Call POST /api/config/generate to create one.",
        )
    return res.data[0]


@router.post("/generate")
async def generate_config(body: ConfigGenerateRequest):
    db = get_supabase()

    # Idempotent — return existing if not force_regenerate
    if not body.force_regenerate:
        existing = (
            db.from_("chatbot_configs")
            .select("*")
            .eq("clinic_id", body.clinic_id)
            .execute()
        )
        if existing.data:
            faqs = (
                db.from_("chatbot_faqs")
                .select("*")
                .eq("clinic_id", body.clinic_id)
                .order("display_order")
                .execute()
            )
            return {**existing.data[0], "faqs": faqs.data}

    # Fetch clinic
    clinic_res = (
        db.from_("clinics")
        .select("id, name, specialty, city, state, website, phone, address")
        .eq("id", body.clinic_id)
        .execute()
    )
    if not clinic_res.data:
        raise HTTPException(status_code=404, detail="Clinic not found.")
    clinic = clinic_res.data[0]

    # Generate config via AI
    agent = ConfigAgent()
    generated = await agent.generate_chatbot_config(clinic)

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()

    config_row = {
        "clinic_id": body.clinic_id,
        "bot_name": generated.get("bot_name", "Assistant"),
        "welcome_message": generated.get("welcome_message", "Hi! How can I help?"),
        "fallback_message": generated.get(
            "fallback_message", "I'll connect you with our team shortly."
        ),
        "tone": generated.get("tone", "friendly"),
        "system_prompt": generated.get("system_prompt", ""),
        "qualification_questions": generated.get("qualification_questions", []),
        "services": generated.get("services", []),
        "faqs": generated.get("faqs", []),
        "primary_color": generated.get("primary_color", "#007AE6"),
        "scheduling_button_text": generated.get(
            "scheduling_button_text", "Book Appointment"
        ),
        "is_active": False,
        "is_ai_generated": True,
        "ai_generation_context": {
            "clinic_id": body.clinic_id,
            "specialty": clinic.get("specialty"),
            "generated_at": now,
        },
    }

    # Delete existing config if force_regenerate
    if body.force_regenerate:
        db.from_("chatbot_configs").delete().eq("clinic_id", body.clinic_id).execute()
        db.from_("chatbot_faqs").delete().eq("clinic_id", body.clinic_id).execute()

    config_res = db.from_("chatbot_configs").insert(config_row).execute()
    config = config_res.data[0]
    config_id = config["id"]

    # Insert FAQs
    faq_rows = [
        {
            "clinic_id": body.clinic_id,
            "config_id": config_id,
            "question": f["question"],
            "answer": f["answer"],
            "category": f.get("category"),
            "display_order": i,
        }
        for i, f in enumerate(generated.get("faqs", []))
    ]
    faqs_data = []
    if faq_rows:
        faqs_res = db.from_("chatbot_faqs").insert(faq_rows).execute()
        faqs_data = faqs_res.data

    logger.info("config_created", clinic_id=body.clinic_id, config_id=config_id)
    return {**config, "faqs": faqs_data}


@router.put("/{clinic_id}")
async def update_config(clinic_id: str, body: ConfigUpdateRequest):
    db = get_supabase()

    existing = (
        db.from_("chatbot_configs").select("*").eq("clinic_id", clinic_id).execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Config not found.")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return existing.data[0]

    from datetime import datetime, timezone

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Regenerate system prompt if tone or services changed
    needs_prompt_regen = "tone" in updates or "services" in updates
    if needs_prompt_regen:
        clinic_res = (
            db.from_("clinics")
            .select("id, name, specialty, city, state")
            .eq("id", clinic_id)
            .execute()
        )
        if clinic_res.data:
            merged_config = {**existing.data[0], **updates}
            agent = ConfigAgent()
            new_prompt = await agent.generate_system_prompt(
                clinic_res.data[0], merged_config
            )
            updates["system_prompt"] = new_prompt

    res = (
        db.from_("chatbot_configs").update(updates).eq("clinic_id", clinic_id).execute()
    )
    return res.data[0]


@router.post("/{clinic_id}/activate")
async def activate_config(clinic_id: str):
    db = get_supabase()
    res = (
        db.from_("chatbot_configs")
        .update({"is_active": True})
        .eq("clinic_id", clinic_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Config not found.")
    return {
        "activated": True,
        "widget_embed_code": _generate_embed_code(clinic_id),
    }


@router.post("/{clinic_id}/deactivate")
async def deactivate_config(clinic_id: str):
    db = get_supabase()
    res = (
        db.from_("chatbot_configs")
        .update({"is_active": False})
        .eq("clinic_id", clinic_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Config not found.")
    return {"deactivated": True}


@router.post("/{clinic_id}/regenerate-prompt")
async def regenerate_prompt(clinic_id: str):
    db = get_supabase()

    config_res = (
        db.from_("chatbot_configs").select("*").eq("clinic_id", clinic_id).execute()
    )
    if not config_res.data:
        raise HTTPException(status_code=404, detail="Config not found.")
    config = config_res.data[0]

    clinic_res = (
        db.from_("clinics")
        .select("id, name, specialty, city, state")
        .eq("id", clinic_id)
        .execute()
    )
    if not clinic_res.data:
        raise HTTPException(status_code=404, detail="Clinic not found.")

    agent = ConfigAgent()
    new_prompt = await agent.generate_system_prompt(clinic_res.data[0], config)

    from datetime import datetime, timezone

    db.from_("chatbot_configs").update(
        {
            "system_prompt": new_prompt,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("clinic_id", clinic_id).execute()

    return {"system_prompt": new_prompt}


@router.get("/{clinic_id}/embed-code")
async def get_embed_code(clinic_id: str):
    return {
        "embed_code": _generate_embed_code(clinic_id),
        "preview_url": f"{settings.widget_base_url}/api/widget/preview/{clinic_id}",
    }


# ── FAQ management ─────────────────────────────────────────────────────────────

@router.get("/{clinic_id}/faqs")
async def list_faqs(
    clinic_id: str,
    category: Optional[str] = None,
    is_active: bool = True,
):
    db = get_supabase()
    q = (
        db.from_("chatbot_faqs")
        .select("*")
        .eq("clinic_id", clinic_id)
        .eq("is_active", is_active)
        .order("display_order")
    )
    if category:
        q = q.eq("category", category)
    return q.execute().data


@router.post("/{clinic_id}/faqs")
async def create_faq(clinic_id: str, body: FAQCreate):
    db = get_supabase()

    config_res = (
        db.from_("chatbot_configs").select("id").eq("clinic_id", clinic_id).execute()
    )
    config_id = config_res.data[0]["id"] if config_res.data else None

    row = {
        "clinic_id": clinic_id,
        "config_id": config_id,
        "question": body.question,
        "answer": body.answer,
        "category": body.category,
        "display_order": body.display_order,
    }
    res = db.from_("chatbot_faqs").insert(row).execute()
    _sync_faqs_to_config(clinic_id)
    return res.data[0]


@router.put("/{clinic_id}/faqs/{faq_id}")
async def update_faq(clinic_id: str, faq_id: str, body: FAQUpdate):
    db = get_supabase()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        res = db.from_("chatbot_faqs").select("*").eq("id", faq_id).execute()
        return res.data[0] if res.data else {}
    res = db.from_("chatbot_faqs").update(updates).eq("id", faq_id).execute()
    _sync_faqs_to_config(clinic_id)
    return res.data[0] if res.data else {}


@router.delete("/{clinic_id}/faqs/{faq_id}")
async def delete_faq(clinic_id: str, faq_id: str):
    db = get_supabase()
    db.from_("chatbot_faqs").delete().eq("id", faq_id).execute()
    _sync_faqs_to_config(clinic_id)
    return {"deleted": True}


@router.post("/{clinic_id}/faqs/reorder")
async def reorder_faqs(clinic_id: str, body: FAQReorderRequest):
    db = get_supabase()
    for i, faq_id in enumerate(body.faq_ids):
        db.from_("chatbot_faqs").update({"display_order": i}).eq("id", faq_id).execute()
    _sync_faqs_to_config(clinic_id)
    return {"reordered": True}


@router.post("/{clinic_id}/suggest-faqs")
async def suggest_faqs(clinic_id: str):
    db = get_supabase()

    # Fetch existing FAQs
    existing_res = (
        db.from_("chatbot_faqs").select("question, answer, category").eq(
            "clinic_id", clinic_id
        ).execute()
    )

    # Fetch recent unanswered messages (low confidence or unknown intent)
    config_res = (
        db.from_("chatbot_configs").select("id").eq("clinic_id", clinic_id).execute()
    )
    recent_questions: list[str] = []
    if config_res.data:
        sessions_res = (
            db.from_("chatbot_sessions")
            .select("id")
            .eq("clinic_id", clinic_id)
            .limit(50)
            .execute()
        )
        if sessions_res.data:
            session_ids = [s["id"] for s in sessions_res.data]
            msgs_res = (
                db.from_("chatbot_messages")
                .select("content")
                .in_("session_id", session_ids)
                .eq("role", "user")
                .or_("intent.eq.unknown,confidence.lt.0.5")
                .limit(20)
                .execute()
            )
            recent_questions = [m["content"] for m in msgs_res.data]

    clinic_res = (
        db.from_("clinics")
        .select("id, name, specialty")
        .eq("id", clinic_id)
        .execute()
    )
    clinic = clinic_res.data[0] if clinic_res.data else {"name": "clinic", "specialty": "general"}

    agent = ConfigAgent()
    suggestions = await agent.suggest_faq_improvements(
        existing_res.data, clinic, recent_questions
    )
    return {"suggestions": suggestions}

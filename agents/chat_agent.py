import json
import re

import google.generativeai as genai
import structlog

from core.config import settings

logger = structlog.get_logger()

INTENT_PATTERNS = {
    "greeting": r"\b(hi|hello|hey|good morning|good afternoon|howdy)\b",
    "pricing": r"\b(cost|price|how much|fee|charge|expensive|afford|insurance)\b",
    "scheduling": r"\b(book|schedule|appointment|available|when|calendar|visit)\b",
    "location": r"\b(where|address|located|directions|parking|near)\b",
    "hours": r"\b(hours|open|close|time|weekend|saturday|sunday)\b",
    "services": r"\b(offer|provide|treat|specialize|procedure|treatment|service)\b",
    "lead_capture": r"\b(contact|reach|call me|email me|follow up|more info)\b",
    "farewell": r"\b(bye|goodbye|thanks|thank you|that's all|done)\b",
}


class ChatAgent:
    def __init__(self, config: dict):
        """
        config: chatbot_configs row from DB
        {system_prompt, bot_name, tone, services, faqs,
         capture_name, capture_email, capture_phone,
         scheduling_enabled, scheduling_url, ...}
        """
        self.config = config
        genai.configure(api_key=settings.gemini_api_key)

    def detect_intent(self, message: str) -> tuple[str, float]:
        """
        Fast regex-based intent detection before Gemini call.
        Returns (intent_name, confidence).
        """
        message_lower = message.lower()
        for intent, pattern in INTENT_PATTERNS.items():
            matches = re.findall(pattern, message_lower, re.IGNORECASE)
            if matches:
                confidence = 1.0 if len(matches) > 1 else 0.7
                return intent, confidence
        return "general", 0.3

    async def get_reply(
        self,
        message: str,
        history: list[dict],
        session: dict,
    ) -> dict:
        """
        Main method: get AI reply for a user message.
        """
        intent, confidence = self.detect_intent(message)

        # Build system prompt, optionally appending lead capture nudge
        system_prompt = self.config.get("system_prompt", "")
        message_count = session.get("message_count", 0)
        lead_captured = session.get("lead_captured", False)
        contact_email = session.get("contact_email")

        if (
            not lead_captured
            and not contact_email
            and message_count >= 2
            and intent not in ("greeting", "farewell")
        ):
            system_prompt += (
                "\n\nThe user has been chatting for a while. "
                "Naturally ask for their name and email to follow up. "
                "Do it conversationally, not as a form. "
                "Example: 'By the way, what’s the best email to reach you?'"
            )

        gemini_history = self.build_gemini_history(history)

        model = genai.GenerativeModel(
            "gemini-2.0-flash",
            system_instruction=system_prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=512,
                temperature=0.7,
            ),
        )
        response = await model.generate_content_async(
            gemini_history + [{"role": "user", "parts": [{"text": message}]}]
        )

        reply_text = response.text

        suggested_actions = self._build_suggested_actions(intent, message_count)

        logger.info(
            "chat_reply_generated",
            intent=intent,
            confidence=confidence,
            message_count=message_count,
        )

        return {
            "reply": reply_text,
            "intent": intent,
            "confidence": confidence,
            "suggested_actions": suggested_actions,
        }

    async def extract_lead_info(self, conversation: list[dict]) -> dict:
        """
        Analyze conversation history to extract any lead info shared.
        """
        conversation_text = "\n".join(
            f"{msg['role'].upper()}: {msg['content']}" for msg in conversation
        )

        prompt = f"""Analyze this chat conversation and extract any contact information shared.

Conversation:
{conversation_text}

Return ONLY valid JSON (no markdown) with exactly these fields:
{{
    "name": "string or null",
    "email": "string or null (must be valid email format)",
    "phone": "string or null (any phone format)",
    "service_interest": "string or null (what service/treatment they want)",
    "urgency": "high or medium or low or null",
    "notes": "string or null (1 sentence summary of what they discussed)"
}}

Rules:
- Only extract what was explicitly stated in the conversation
- email must match pattern user@domain.tld
- urgency=high if they said soon/this week/ASAP/urgent
- urgency=medium if they asked about scheduling or pricing
- urgency=low if just browsing/general questions
- notes should be concise, 1 sentence max
"""
        model = genai.GenerativeModel(
            "gemini-2.0-flash",
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=256,
                temperature=0.1,
            ),
        )
        response = await model.generate_content_async(prompt)

        raw = response.text
        try:
            result = self._parse_json(raw)
        except (ValueError, json.JSONDecodeError):
            result = {
                "name": None,
                "email": None,
                "phone": None,
                "service_interest": None,
                "urgency": None,
                "notes": None,
            }

        # Validate email format
        if result.get("email") and not re.match(
            r"^[^@]+@[^@]+\.[^@]+$", result["email"]
        ):
            result["email"] = None

        return result

    def calculate_qualification_score(self, session: dict, lead_info: dict) -> int:
        """Calculate 0-100 qualification score."""
        score = 0
        if lead_info.get("service_interest"):
            score += 30
        if lead_info.get("email"):
            score += 20
        if lead_info.get("phone"):
            score += 15
        if lead_info.get("name"):
            score += 10
        urgency = lead_info.get("urgency")
        if urgency == "high":
            score += 15
        elif urgency == "medium":
            score += 10
        if session.get("message_count", 0) >= 4:
            score += 10
        if session.get("source_surface") == "preview":
            score -= 10
        return max(0, min(100, score))

    def build_gemini_history(self, history: list[dict]) -> list[dict]:
        """Convert chat history to Gemini format, capped at last 10 messages."""
        gemini_history = []
        for msg in history[-10:]:
            role = "user" if msg["role"] == "user" else "model"
            gemini_history.append({"role": role, "parts": [{"text": msg["content"]}]})
        return gemini_history

    def _build_suggested_actions(self, intent: str, message_count: int) -> list:
        actions = []
        if intent == "scheduling" and self.config.get("scheduling_enabled"):
            actions.append({
                "type": "book_appointment",
                "label": self.config.get("scheduling_button_text", "Book Appointment"),
                "url": self.config.get("scheduling_url"),
            })
        elif intent == "lead_capture" or message_count >= 4:
            actions.append({"type": "capture_lead", "label": "Get a callback"})
        if intent == "farewell":
            actions.append({"type": "end_chat", "label": "End conversation"})
        return actions

    def _parse_json(self, text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        return json.loads(text.strip())

import json
import structlog
from pathlib import Path

import google.generativeai as genai

from core.config import settings

logger = structlog.get_logger()

_patterns_path = Path(__file__).parent.parent / "skills" / "chatbot_patterns.md"
CHATBOT_PATTERNS = _patterns_path.read_text() if _patterns_path.exists() else ""


class ConfigAgent:
    def __init__(self):
        genai.configure(api_key=settings.gemini_api_key)
        self._model = genai.GenerativeModel("gemini-2.0-flash")

    async def generate_chatbot_config(self, clinic: dict) -> dict:
        """
        Auto-generate complete chatbot configuration for a clinic.
        """
        prompt = f"""You are a medical chatbot configuration expert for MEDPLATFORM.

Generate a complete chatbot configuration for this medical clinic:
- Name: {clinic.get('name', 'Unknown Clinic')}
- Specialty: {clinic.get('specialty', 'general')}
- City: {clinic.get('city', '')}
- State: {clinic.get('state', '')}
- Website: {clinic.get('website', 'N/A')}

Reference these medical chatbot best practices:
{CHATBOT_PATTERNS}

Return ONLY valid JSON with this exact structure (no markdown fences):
{{
    "bot_name": "string (max 30 chars, friendly name like Maya or Alex or BrandedAssistant)",
    "welcome_message": "string (max 120 chars, warm clinic-specific greeting)",
    "fallback_message": "string (max 100 chars, graceful handoff message)",
    "tone": "friendly",
    "system_prompt": "string (~500 words, full system prompt per the patterns guide)",
    "qualification_questions": [
        {{"question": "string", "type": "open|yes_no|service_select|multiple_choice", "options": null}}
    ],
    "services": ["string", "..."],
    "faqs": [
        {{"question": "string", "answer": "string", "category": "pricing|services|location|booking|credentials|preparation"}}
    ],
    "primary_color": "#007AE6",
    "scheduling_button_text": "Book Appointment"
}}

Requirements:
- Generate exactly 3 qualification questions relevant to the specialty
- Generate exactly 10 FAQs specific to the specialty and clinic location
- bot_name must be ≤30 chars
- welcome_message must be ≤120 chars
- services: 5-10 services typical for this specialty
- tone must be one of: professional, friendly, warm, concise
- primary_color: choose a color appropriate for the specialty
"""
        for attempt in range(2):
            try:
                response = self._model.generate_content(prompt)
                result = self._parse_json_response(response.text)

                # Enforce constraints
                if len(result.get("bot_name", "")) > 30:
                    result["bot_name"] = result["bot_name"][:30]
                if len(result.get("welcome_message", "")) > 120:
                    result["welcome_message"] = result["welcome_message"][:120]

                logger.info(
                    "config_generated",
                    clinic_id=clinic.get("id"),
                    specialty=clinic.get("specialty"),
                )
                return result
            except (ValueError, json.JSONDecodeError) as e:
                if attempt == 0:
                    logger.warning("config_parse_retry", error=str(e))
                    continue
                logger.error("config_parse_failed", error=str(e))
                raise

    async def generate_system_prompt(self, clinic: dict, config: dict) -> str:
        """
        Generate or regenerate just the system prompt.
        Used when admin changes services, FAQs, or tone.
        """
        faqs_text = ""
        if config.get("faqs"):
            faqs_text = "\n".join(
                f"Q: {f['question']}\nA: {f['answer']}"
                for f in config["faqs"][:10]
            )

        services_text = ", ".join(config.get("services", [])) or "various services"
        scheduling_text = ""
        if config.get("scheduling_enabled") and config.get("scheduling_url"):
            scheduling_text = (
                f"\nScheduling: Direct patients to book at {config['scheduling_url']} "
                f"using the '{config.get('scheduling_button_text', 'Book Appointment')}' button."
            )

        prompt = f"""Write a system prompt for a medical chatbot with these specifications:

Bot name: {config.get('bot_name', 'Assistant')}
Clinic: {clinic.get('name', 'the clinic')}
Specialty: {clinic.get('specialty', 'general medicine')}
Location: {clinic.get('city', '')}, {clinic.get('state', '')}
Tone: {config.get('tone', 'friendly')}
Services offered: {services_text}
{scheduling_text}

Top FAQs to know:
{faqs_text}

HIPAA compliance rules (MUST follow):
{CHATBOT_PATTERNS[:500]}

Write a complete system prompt (400-600 words) that includes:
1. Bot identity paragraph
2. Clinic context (specialty, location, services)
3. HIPAA behavior rules
4. Lead capture instructions (service interest → name → email → phone order)
5. FAQ knowledge inline
6. Escalation rules (when to say "let me connect you with our team")
7. Closing/handoff instructions

Return ONLY the system prompt text, no JSON wrapper.
"""
        response = self._model.generate_content(prompt)
        return response.text.strip()

    async def suggest_faq_improvements(
        self,
        existing_faqs: list[dict],
        clinic: dict,
        recent_questions: list[str],
    ) -> list[dict]:
        """
        Given existing FAQs and recent unanswered questions,
        suggest new FAQs or improvements to existing ones.
        """
        existing_text = "\n".join(
            f"- {f['question']}" for f in existing_faqs
        )
        recent_text = "\n".join(f"- {q}" for q in recent_questions[:20])

        prompt = f"""A medical chatbot for {clinic.get('name')} ({clinic.get('specialty')}) \
has these existing FAQs:
{existing_text}

Visitors recently asked questions the bot couldn't answer well:
{recent_text}

Suggest 5 new FAQs or improvements. Return ONLY valid JSON array:
[
  {{
    "question": "string",
    "answer": "string",
    "category": "pricing|services|location|booking|credentials|preparation",
    "reason": "why this FAQ would help"
  }}
]
"""
        response = self._model.generate_content(prompt)
        return self._parse_json_response(response.text)

    async def generate_bot_name(self, clinic: dict) -> str:
        """
        Generate a friendly bot name for the clinic.
        Returns a single name string ≤20 chars.
        """
        prompt = f"""Generate a single friendly chatbot name for a {clinic.get('specialty', 'medical')} \
clinic called "{clinic.get('name', 'the clinic')}".

Options: a neutral human name (Maya, Alex, Jordan) OR a branded name \
("{clinic.get('name', '').split()[0]} Assistant").
Return ONLY the name, nothing else. Max 20 characters.
"""
        response = self._model.generate_content(prompt)
        name = response.text.strip().strip('"').strip("'")
        return name[:20]

    def _parse_json_response(self, text: str) -> dict:
        """
        Safely parse Gemini JSON response.
        Strips ```json fences, leading/trailing whitespace.
        """
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        return json.loads(text.strip())

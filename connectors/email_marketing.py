import httpx
import structlog

from core.config import settings

logger = structlog.get_logger()


class EmailMarketingConnector:
    def __init__(self):
        self.base_url = settings.email_marketing_url

    async def enroll_lead(self, clinic_id: str, lead: dict) -> dict:
        """
        Send captured lead to email-marketing service.
        Called after lead info is captured in chat.

        lead: {name, email, phone, service_interest, session_id, tags}

        Never raises — chatbot must continue even if email service is down.
        """
        try:
            first_name = None
            if lead.get("name"):
                first_name = lead["name"].split()[0]

            tags = ["chatbot_lead"]
            if lead.get("service_interest"):
                service_tag = lead["service_interest"].lower().replace(" ", "_")
                tags.append(f"interest_{service_tag}")

            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"{self.base_url}/api/contacts",
                    json={
                        "clinic_id": clinic_id,
                        "email": lead["email"],
                        "first_name": first_name,
                        "phone": lead.get("phone"),
                        "source": "chatbot",
                        "source_metadata": {
                            "service_interest": lead.get("service_interest"),
                            "session_id": lead.get("session_id"),
                        },
                        "tags": tags,
                    },
                )
                if res.status_code in (200, 201):
                    result = res.json()
                    logger.info(
                        "lead_enrolled_in_email",
                        clinic_id=clinic_id,
                        email=lead["email"],
                    )
                    return {"id": result.get("id"), "status": "created"}
                else:
                    logger.warning(
                        "email_enroll_failed",
                        status=res.status_code,
                        email=lead.get("email"),
                    )
                    return {"id": None, "status": "failed"}
        except Exception as e:
            logger.error("email_connector_error", error=str(e))
            return {"id": None, "status": "failed"}

    async def health_check(self) -> bool:
        """Ping email-marketing service. Returns True if reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(f"{self.base_url}/")
                return res.status_code == 200
        except Exception:
            return False

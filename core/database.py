from supabase import create_client, Client
from .config import settings
import structlog

logger = structlog.get_logger()
_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _client


async def check_connection() -> bool:
    try:
        get_supabase().from_("clinics").select("id").limit(1).execute()
        return True
    except Exception as e:
        logger.error("db_connection_failed", error=str(e))
        return False

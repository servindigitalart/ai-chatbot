import structlog
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from core.config import settings
from core.database import get_supabase

router = APIRouter(prefix="/widget", tags=["widget"])
logger = structlog.get_logger()


@router.get("/preview/{clinic_id}", response_class=HTMLResponse)
async def preview_widget(clinic_id: str):
    """Preview page for the widget — used by admin before deploying."""
    db = get_supabase()

    clinic_name = clinic_id
    try:
        res = db.from_("clinics").select("name").eq("id", clinic_id).execute()
        if res.data:
            clinic_name = res.data[0].get("name", clinic_id)
    except Exception:
        pass

    widget_base = settings.widget_base_url
    api_base = settings.ai_chatbot_url

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Widget Preview \u2014 {clinic_name}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
      max-width: 800px; margin: 80px auto; padding: 20px; color: #374151;
    }}
    .preview-badge {{
      background: #fef3c7; border: 1px solid #fcd34d;
      padding: 8px 16px; border-radius: 8px; font-size: 13px;
      display: inline-block; margin-bottom: 24px;
    }}
    h1 {{ font-size: 28px; color: #111827; margin: 0 0 12px; }}
    p {{ color: #6b7280; line-height: 1.6; }}
    h3 {{ font-size: 15px; color: #374151; margin: 24px 0 8px; }}
    .embed-code {{
      background: #1e293b; color: #e2e8f0; padding: 16px;
      border-radius: 8px; font-family: monospace; font-size: 13px;
      word-break: break-all; line-height: 1.6;
    }}
  </style>
</head>
<body>
  <span class="preview-badge">Preview Mode</span>
  <h1>Chatbot Preview</h1>
  <p>The chat widget appears in the bottom-right corner after 2 seconds.<br>
     Click it to start a conversation.</p>
  <h3>Embed code for your website:</h3>
  <div class="embed-code">
    &lt;script src="{widget_base}/static/widget.js"<br>
    &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;data-clinic-id="{clinic_id}" async&gt;&lt;/script&gt;
  </div>
  <script src="{widget_base}/static/widget.js"
          data-clinic-id="{clinic_id}"
          data-api-url="{api_base}"
          async></script>
</body>
</html>"""
    return html


@router.get("/embed-code/{clinic_id}")
async def get_embed_code(clinic_id: str):
    db = get_supabase()

    is_active = False
    try:
        res = (
            db.from_("chatbot_configs")
            .select("is_active")
            .eq("clinic_id", clinic_id)
            .execute()
        )
        if res.data:
            is_active = res.data[0].get("is_active", False)
    except Exception:
        pass

    widget_base = settings.widget_base_url
    embed_code = (
        f'<script src="{widget_base}/static/widget.js" '
        f'data-clinic-id="{clinic_id}" async></script>'
    )

    return {
        "embed_code": embed_code,
        "preview_url": f"{widget_base}/api/widget/preview/{clinic_id}",
        "is_active": is_active,
    }

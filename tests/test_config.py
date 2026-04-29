import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health_returns_ok():
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["service"] == "ai-chatbot"


def test_health_detail_structure():
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert "checks" in data
    assert "database" in data["checks"]
    assert "gemini" in data["checks"]


def test_config_not_found():
    res = client.get("/api/config/nonexistent-clinic-id")
    assert res.status_code in (404, 500)


def test_leads_list_empty():
    res = client.get("/api/leads?clinic_id=test-id")
    assert res.status_code == 200


def test_analytics_overview_structure():
    res = client.get("/api/analytics/overview?clinic_id=test-id")
    assert res.status_code == 200
    data = res.json()
    assert "total_sessions" in data
    assert "leads_captured" in data


def test_chat_session_stub():
    res = client.post(
        "/api/chat/session",
        json={"clinic_id": "test-id", "source_url": "https://example.com"},
    )
    # 200 if active config exists; 404 if not (expected in mock env)
    assert res.status_code in (200, 404)


def test_widget_preview_returns_html():
    res = client.get("/api/widget/preview/test-clinic-id")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "widget.js" in res.text


def test_widget_js_served():
    """widget.js is served as static file with correct content."""
    res = client.get("/static/widget.js")
    assert res.status_code == 200
    assert "MEDPLATFORM" in res.text
    assert "data-clinic-id" in res.text


def test_embed_code_endpoint():
    """Embed code endpoint returns script tag."""
    res = client.get("/api/widget/embed-code/test-clinic-id")
    assert res.status_code == 200
    data = res.json()
    assert "embed_code" in data
    assert "script" in data["embed_code"]
    assert "preview_url" in data
    assert "is_active" in data


async def test_config_agent_generate():
    """ConfigAgent generates valid config with real Gemini."""
    import os

    if not os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") == "mock-key":
        pytest.skip("Real GEMINI_API_KEY not set")

    from agents.config_agent import ConfigAgent

    agent = ConfigAgent()
    result = await agent.generate_chatbot_config(
        {
            "id": "test-id",
            "name": "Austin Dermatology Center",
            "specialty": "dermatology",
            "city": "Austin",
            "state": "TX",
            "website": "https://austinderm.com",
        }
    )
    assert "bot_name" in result
    assert "welcome_message" in result
    assert "system_prompt" in result
    assert "faqs" in result
    assert len(result["faqs"]) >= 5
    assert len(result["welcome_message"]) <= 120

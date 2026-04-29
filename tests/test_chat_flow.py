import os

import pytest


MOCK_CONFIG = {
    "system_prompt": "You are a helpful assistant.",
    "bot_name": "Maya",
    "tone": "friendly",
    "services": ["Botox", "Acne Treatment"],
    "scheduling_enabled": False,
    "scheduling_url": None,
    "scheduling_button_text": "Book Now",
}

SCHEDULING_CONFIG = {
    **MOCK_CONFIG,
    "scheduling_enabled": True,
    "scheduling_url": "https://book.me",
    "scheduling_button_text": "Book Consultation",
}


def test_detect_intent_pricing():
    from agents.chat_agent import ChatAgent

    agent = ChatAgent(config=MOCK_CONFIG)
    intent, confidence = agent.detect_intent("How much does Botox cost?")
    assert intent == "pricing"
    assert confidence >= 0.7


def test_detect_intent_scheduling():
    from agents.chat_agent import ChatAgent

    agent = ChatAgent(config=SCHEDULING_CONFIG)
    intent, confidence = agent.detect_intent("Can I book an appointment?")
    assert intent == "scheduling"
    assert confidence >= 0.7


def test_detect_intent_fallback():
    from agents.chat_agent import ChatAgent

    agent = ChatAgent(config=MOCK_CONFIG)
    intent, confidence = agent.detect_intent("Tell me something interesting")
    assert intent == "general"
    assert confidence < 0.5


def test_qualification_score_full_lead():
    """Full lead with email + phone + service + urgency gets hot score."""
    from agents.chat_agent import ChatAgent

    agent = ChatAgent(config=MOCK_CONFIG)
    lead_info = {
        "name": "John Smith",
        "email": "john@example.com",
        "phone": "512-555-0100",
        "service_interest": "Botox",
        "urgency": "high",
    }
    session = {"message_count": 5, "source_surface": "widget"}
    score = agent.calculate_qualification_score(session, lead_info)
    assert score >= 70
    assert score <= 100


def test_qualification_score_cold_lead():
    """Lead with no contact info gets low score."""
    from agents.chat_agent import ChatAgent

    agent = ChatAgent(config=MOCK_CONFIG)
    lead_info = {
        "name": None,
        "email": None,
        "phone": None,
        "service_interest": None,
        "urgency": None,
    }
    session = {"message_count": 1, "source_surface": "widget"}
    score = agent.calculate_qualification_score(session, lead_info)
    assert score < 40


def test_qualification_score_preview_penalty():
    """Preview surface loses 10 points."""
    from agents.chat_agent import ChatAgent

    agent = ChatAgent(config=MOCK_CONFIG)
    lead_info = {
        "name": "Jane",
        "email": "jane@example.com",
        "phone": None,
        "service_interest": "Acne",
        "urgency": None,
    }
    session_widget = {"message_count": 2, "source_surface": "widget"}
    session_preview = {"message_count": 2, "source_surface": "preview"}
    score_widget = agent.calculate_qualification_score(session_widget, lead_info)
    score_preview = agent.calculate_qualification_score(session_preview, lead_info)
    assert score_preview == score_widget - 10


def test_build_gemini_history_converts_roles():
    """assistant role is converted to model for Gemini API."""
    from agents.chat_agent import ChatAgent

    agent = ChatAgent(config=MOCK_CONFIG)
    history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "What services do you offer?"},
    ]
    gemini = agent.build_gemini_history(history)
    assert gemini[0]["role"] == "user"
    assert gemini[1]["role"] == "model"
    assert gemini[2]["role"] == "user"
    assert gemini[0]["parts"][0]["text"] == "Hello"


def test_build_gemini_history_limits_to_10():
    """History is capped at the last 10 messages."""
    from agents.chat_agent import ChatAgent

    agent = ChatAgent(config=MOCK_CONFIG)
    history = [{"role": "user", "content": f"msg {i}"} for i in range(15)]
    gemini = agent.build_gemini_history(history)
    assert len(gemini) == 10
    # Should be the last 10
    assert gemini[0]["parts"][0]["text"] == "msg 5"
    assert gemini[-1]["parts"][0]["text"] == "msg 14"


async def test_chat_agent_get_reply_real_gemini():
    """Full reply with real Gemini API."""
    if not os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") == "mock-key":
        pytest.skip("Real GEMINI_API_KEY not set")

    from agents.chat_agent import ChatAgent

    config = {
        "system_prompt": (
            "You are Maya, the AI assistant for Austin Dermatology Center. "
            "You help patients learn about services and book consultations. "
            "Services: Botox, Acne Treatment, Chemical Peels. "
            "Location: Austin, TX. Always be warm and professional."
        ),
        "bot_name": "Maya",
        "tone": "friendly",
        "services": ["Botox", "Acne Treatment"],
        "scheduling_enabled": True,
        "scheduling_url": "https://austinderm.com/book",
        "scheduling_button_text": "Book Consultation",
    }
    agent = ChatAgent(config=config)
    result = await agent.get_reply(
        message="How much does Botox cost?",
        history=[],
        session={
            "message_count": 1,
            "source_surface": "widget",
            "lead_captured": False,
            "contact_email": None,
        },
    )
    assert "reply" in result
    assert len(result["reply"]) > 10
    assert "intent" in result
    assert result["intent"] == "pricing"
    assert "suggested_actions" in result
    assert isinstance(result["suggested_actions"], list)


async def test_extract_lead_info_finds_email():
    """extract_lead_info correctly identifies email in conversation."""
    if not os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") == "mock-key":
        pytest.skip("Real GEMINI_API_KEY not set")

    from agents.chat_agent import ChatAgent

    agent = ChatAgent(config=MOCK_CONFIG)
    conversation = [
        {"role": "assistant", "content": "Hi! How can I help?"},
        {"role": "user", "content": "I'm John and I'm interested in Botox"},
        {"role": "assistant", "content": "Great! What's your email?"},
        {
            "role": "user",
            "content": "Sure, it's john.smith@gmail.com, call me at 512-555-0100",
        },
    ]
    result = await agent.extract_lead_info(conversation)
    assert result.get("email") == "john.smith@gmail.com"
    assert result.get("name") is not None
    assert result.get("service_interest") is not None

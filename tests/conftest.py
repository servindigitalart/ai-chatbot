import os
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("SUPABASE_URL", "https://mock.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "mock-key")
os.environ.setdefault("DATABASE_URL", "postgresql://mock")
os.environ.setdefault("GEMINI_API_KEY", "mock-key")

import core.database as _db_module  # noqa: E402 — after env vars are set


def _make_mock_client():
    """Supabase-like mock that chains .from_/.select/... returning empty data."""
    execute = MagicMock(return_value=MagicMock(data=[], count=0))
    chain = MagicMock()
    chain.execute = execute
    for method in (
        "eq", "in_", "order", "limit", "range", "single",
        "select", "insert", "update", "delete", "upsert",
        "neq", "gte", "lte", "gt", "lt", "contains", "match", "or_",
    ):
        setattr(chain, method, MagicMock(return_value=chain))
    chain.execute = execute

    sb = MagicMock()
    sb.from_ = MagicMock(return_value=chain)
    sb.table = MagicMock(return_value=chain)
    return sb


@pytest.fixture(autouse=True)
def mock_supabase_client():
    """Replace cached Supabase client for every test, then restore."""
    original = _db_module._client
    _db_module._client = _make_mock_client()
    yield
    _db_module._client = original

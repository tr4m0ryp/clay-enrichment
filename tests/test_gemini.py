"""
Tests for GeminiClient.

All tests mock the google-genai SDK so no real API calls are made.
"""

import json
import os
import sys
import types as builtin_types
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so "from src..." imports work.
# ---------------------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ---------------------------------------------------------------------------
# Stub out google.genai BEFORE importing GeminiClient.
# The stub must look like a proper package (google) with a genai sub-module.
# ---------------------------------------------------------------------------

# Preserve the real google package if it exists, so we only override genai.
if "google" not in sys.modules:
    _google_pkg = builtin_types.ModuleType("google")
    _google_pkg.__path__ = []
    sys.modules["google"] = _google_pkg

_genai_stub = builtin_types.ModuleType("google.genai")
_genai_types_stub = builtin_types.ModuleType("google.genai.types")

_google_pkg = sys.modules["google"]
_genai_stub.Client = MagicMock()
_genai_types_stub.GenerateContentConfig = MagicMock()
_google_pkg.genai = _genai_stub
sys.modules["google.genai"] = _genai_stub
sys.modules["google.genai.types"] = _genai_types_stub

# Now it is safe to import GeminiClient. src.utils.logger exists in the
# real package and has no heavy imports, so it does not need stubbing.
from src.gemini.client import GeminiClient  # noqa: E402

# Keep a reference so tests can swap out Client/GenerateContentConfig
_genai = sys.modules["google.genai"]
_genai_types = sys.modules["google.genai.types"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(model_enrichment="gemini-2.5-flash-lite"):
    cfg = MagicMock()
    cfg.gemini_api_key = "test-api-key"
    cfg.model_enrichment = model_enrichment
    return cfg


def _make_rate_limiter():
    rl = MagicMock()
    rl.acquire = AsyncMock()
    return rl


def _make_response(text: str, input_tokens: int = 10, output_tokens: int = 20):
    usage = MagicMock()
    usage.prompt_token_count = input_tokens
    usage.candidates_token_count = output_tokens

    resp = MagicMock()
    resp.text = text
    resp.usage_metadata = usage
    return resp


def _setup_mock_client(response):
    """Return a (mock_client, mock_aio) pair wired to return response."""
    mock_aio = MagicMock()
    mock_aio.models.generate_content = AsyncMock(return_value=response)
    mock_client = MagicMock()
    mock_client.aio = mock_aio
    _genai.Client.return_value = mock_client
    return mock_client, mock_aio


# ---------------------------------------------------------------------------
# Tests: generate()
# ---------------------------------------------------------------------------

class TestGeminiClientGenerate:

    @pytest.mark.anyio
    async def test_rate_limiter_called_before_api(self):
        """Rate limiter acquire() must be called before the API call."""
        call_order = []

        config = _make_config()
        rate_limiter = _make_rate_limiter()

        async def track_acquire(api_name):
            call_order.append("acquire")

        rate_limiter.acquire = AsyncMock(side_effect=track_acquire)

        mock_aio = MagicMock()

        async def api_call(**kwargs):
            call_order.append("api")
            return _make_response("hello")

        mock_aio.models.generate_content = AsyncMock(side_effect=api_call)
        mock_client = MagicMock()
        mock_client.aio = mock_aio
        _genai.Client.return_value = mock_client

        client = GeminiClient(config, rate_limiter)
        await client.generate(prompt="sys", user_message="hi")

        assert call_order[0] == "acquire", "rate limiter must be called first"
        assert call_order[1] == "api", "api call must come after rate limiter"

    @pytest.mark.anyio
    async def test_generate_returns_text_and_token_counts(self):
        config = _make_config()
        rate_limiter = _make_rate_limiter()
        _, mock_aio = _setup_mock_client(
            _make_response("result text", input_tokens=5, output_tokens=15)
        )

        client = GeminiClient(config, rate_limiter)
        result = await client.generate(prompt="sys", user_message="hello")

        assert result["text"] == "result text"
        assert result["input_tokens"] == 5
        assert result["output_tokens"] == 15

    @pytest.mark.anyio
    async def test_generate_uses_config_model_when_none_provided(self):
        config = _make_config(model_enrichment="gemini-2.5-flash-lite")
        rate_limiter = _make_rate_limiter()
        _, mock_aio = _setup_mock_client(_make_response("ok"))

        client = GeminiClient(config, rate_limiter)
        await client.generate(prompt="sys", user_message="msg", model=None)

        call_kwargs = mock_aio.models.generate_content.call_args.kwargs
        assert call_kwargs["model"] == "gemini-2.5-flash-lite"

    @pytest.mark.anyio
    async def test_generate_uses_explicit_model(self):
        config = _make_config()
        rate_limiter = _make_rate_limiter()
        _, mock_aio = _setup_mock_client(_make_response("ok"))

        client = GeminiClient(config, rate_limiter)
        await client.generate(prompt="sys", user_message="msg", model="gemini-2.5-flash")

        call_kwargs = mock_aio.models.generate_content.call_args.kwargs
        assert call_kwargs["model"] == "gemini-2.5-flash"

    @pytest.mark.anyio
    async def test_rate_limiter_called_with_model_name(self):
        config = _make_config()
        rate_limiter = _make_rate_limiter()
        _setup_mock_client(_make_response("ok"))

        client = GeminiClient(config, rate_limiter)
        await client.generate(prompt="sys", user_message="msg", model="gemini-2.5-flash")

        rate_limiter.acquire.assert_called_once_with("gemini-2.5-flash")

    @pytest.mark.anyio
    async def test_json_mode_sets_response_mime_type(self):
        config = _make_config()
        rate_limiter = _make_rate_limiter()
        _setup_mock_client(_make_response('{"key": "value"}'))

        captured = {}
        original = _genai_types.GenerateContentConfig

        def capture(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        _genai_types.GenerateContentConfig = capture
        try:
            client = GeminiClient(config, rate_limiter)
            await client.generate(prompt="sys", user_message="msg", json_mode=True)
        finally:
            _genai_types.GenerateContentConfig = original

        assert captured.get("response_mime_type") == "application/json"

    @pytest.mark.anyio
    async def test_json_mode_false_does_not_set_mime_type(self):
        config = _make_config()
        rate_limiter = _make_rate_limiter()
        _setup_mock_client(_make_response("plain text"))

        captured = {}
        original = _genai_types.GenerateContentConfig

        def capture(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        _genai_types.GenerateContentConfig = capture
        try:
            client = GeminiClient(config, rate_limiter)
            await client.generate(prompt="sys", user_message="msg", json_mode=False)
        finally:
            _genai_types.GenerateContentConfig = original

        assert "response_mime_type" not in captured

    @pytest.mark.anyio
    async def test_api_error_is_logged_and_raised(self):
        config = _make_config()
        rate_limiter = _make_rate_limiter()

        mock_aio = MagicMock()
        mock_aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("API failure")
        )
        mock_client = MagicMock()
        mock_client.aio = mock_aio
        _genai.Client.return_value = mock_client

        client = GeminiClient(config, rate_limiter)

        with pytest.raises(RuntimeError, match="API failure"):
            await client.generate(prompt="sys", user_message="msg")


# ---------------------------------------------------------------------------
# Tests: generate_batch()
# ---------------------------------------------------------------------------

class TestGeminiClientGenerateBatch:

    @pytest.mark.anyio
    async def test_batch_combines_items_into_single_call(self):
        config = _make_config()
        rate_limiter = _make_rate_limiter()

        items = ["item one", "item two", "item three"]
        batch_json = json.dumps([{"id": 1}, {"id": 2}, {"id": 3}])
        _, mock_aio = _setup_mock_client(_make_response(batch_json))

        client = GeminiClient(config, rate_limiter)
        await client.generate_batch(prompt="classify each", items=items)

        assert mock_aio.models.generate_content.call_count == 1

        contents = mock_aio.models.generate_content.call_args.kwargs["contents"]
        assert "item one" in contents
        assert "item two" in contents
        assert "item three" in contents

    @pytest.mark.anyio
    async def test_batch_parses_json_array(self):
        config = _make_config()
        rate_limiter = _make_rate_limiter()

        payload = [{"name": "Alice"}, {"name": "Bob"}]
        _setup_mock_client(_make_response(json.dumps(payload)))

        client = GeminiClient(config, rate_limiter)
        result = await client.generate_batch(prompt="enrich", items=["a", "b"])

        assert result["results"] == payload

    @pytest.mark.anyio
    async def test_batch_empty_items_returns_empty(self):
        config = _make_config()
        rate_limiter = _make_rate_limiter()

        client = GeminiClient(config, rate_limiter)
        result = await client.generate_batch(prompt="sys", items=[])

        assert result == {"results": [], "input_tokens": 0, "output_tokens": 0}
        rate_limiter.acquire.assert_not_called()

    @pytest.mark.anyio
    async def test_batch_invalid_json_raises(self):
        config = _make_config()
        rate_limiter = _make_rate_limiter()
        _setup_mock_client(_make_response("not valid json {{{{"))

        client = GeminiClient(config, rate_limiter)

        with pytest.raises(json.JSONDecodeError):
            await client.generate_batch(prompt="sys", items=["x"])

    @pytest.mark.anyio
    async def test_batch_uses_json_mode_by_default(self):
        config = _make_config()
        rate_limiter = _make_rate_limiter()
        _setup_mock_client(_make_response("[]"))

        captured = {}
        original = _genai_types.GenerateContentConfig

        def capture(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        _genai_types.GenerateContentConfig = capture
        try:
            client = GeminiClient(config, rate_limiter)
            await client.generate_batch(prompt="sys", items=["a"])
        finally:
            _genai_types.GenerateContentConfig = original

        assert captured.get("response_mime_type") == "application/json"

    @pytest.mark.anyio
    async def test_batch_returns_token_counts(self):
        config = _make_config()
        rate_limiter = _make_rate_limiter()
        _setup_mock_client(_make_response("[1, 2]", input_tokens=100, output_tokens=50))

        client = GeminiClient(config, rate_limiter)
        result = await client.generate_batch(prompt="sys", items=["a", "b"])

        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50

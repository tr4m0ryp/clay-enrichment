"""
Test configuration: mock unavailable third-party imports.

The google-genai SDK and notion-client require specific versions that
may not be available in all environments. This conftest patches the
import machinery so tests can run with mocked external dependencies.
"""

import sys
from unittest.mock import MagicMock

# Mock the google.genai namespace so `from google import genai` works
_mock_genai = MagicMock()
_mock_genai_types = MagicMock()
_mock_genai.types = _mock_genai_types

# Build the google namespace mock
_mock_google = MagicMock()
_mock_google.genai = _mock_genai

# Only patch if the real import fails
try:
    from google import genai  # noqa: F401
except (ImportError, ModuleNotFoundError):
    sys.modules.setdefault("google.genai", _mock_genai)
    sys.modules.setdefault("google.genai.types", _mock_genai_types)
    # Ensure google namespace has genai attribute
    if "google" in sys.modules:
        sys.modules["google"].genai = _mock_genai
    else:
        sys.modules["google"] = _mock_google

# Mock notion_client if not available
try:
    from notion_client import Client  # noqa: F401
except (ImportError, ModuleNotFoundError):
    _mock_notion = MagicMock()
    sys.modules.setdefault("notion_client", _mock_notion)

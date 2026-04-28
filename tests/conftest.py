"""
Test configuration: mock unavailable third-party imports.

The google-genai SDK requires specific versions that may not be
available in all environments. This conftest patches the import
machinery so tests can run with mocked external dependencies.
"""

import sys
from unittest.mock import MagicMock

_mock_genai = MagicMock()
_mock_genai_types = MagicMock()
_mock_genai.types = _mock_genai_types

_mock_google = MagicMock()
_mock_google.genai = _mock_genai

try:
    from google import genai  # noqa: F401
except (ImportError, ModuleNotFoundError):
    sys.modules.setdefault("google.genai", _mock_genai)
    sys.modules.setdefault("google.genai.types", _mock_genai_types)
    if "google" in sys.modules:
        sys.modules["google"].genai = _mock_genai
    else:
        sys.modules["google"] = _mock_google

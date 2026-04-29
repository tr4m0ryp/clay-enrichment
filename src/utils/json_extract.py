"""Tolerant JSON extractor for LLM output.

Handles:
- raw JSON (``{...}`` or ``[...]``)
- markdown-fenced JSON (```json ... ``` or ``` ... ```)
- leading/trailing prose ("Here is the JSON: {...}\\n\\nHope this helps!")
- partial truncation (try to find the longest balanced subspan)

This is the single chokepoint that every Gemini text response must flow
through before being treated as structured data. Per F16, the api_keys
pool can downshift the served model, and lower tiers (Gemini 2.5 Flash)
emit prose / markdown fences more often. ``json.loads`` directly on
LLM output is brittle; use ``extract_json`` instead.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Markdown-fenced JSON: ```json {...} ``` or ``` [...] ``` (lazy, so the
# *first* fenced block wins -- subsequent fences are ignored).
_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```",
    re.DOTALL,
)

# Greedy fallback: match from the first opening brace/bracket through the
# last closing brace/bracket. Greediness is intentional -- it lets us
# capture nested structures that a lazy match would truncate. If the span
# does not parse, ``_shrink_to_balanced`` walks character-by-character to
# find the longest balanced prefix.
_OBJECT_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def extract_json(text: str) -> Any | None:
    """Extract a JSON value from possibly-noisy LLM output.

    Returns the parsed value (``dict`` or ``list``) or ``None`` if no
    valid JSON could be recovered. The order of attempts is:

    1. ``json.loads`` on the stripped text (the happy path -- the model
       obeyed the "JSON only" instruction).
    2. Markdown-fenced extraction -- the first ```json ... ``` block.
    3. Greedy first-brace-to-last-brace span; if that fails, balance the
       span by trimming trailing characters until braces match.

    Args:
        text: raw model output.

    Returns:
        Parsed JSON value, or ``None`` when nothing usable was found.
    """
    if not text:
        return None
    stripped = text.strip()

    # Path 1: direct parse.
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        pass

    # Path 2: markdown fence.
    fence_match = _FENCE_RE.search(stripped)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # Path 3: greedy span + balance-shrinking fallback.
    span_match = _OBJECT_RE.search(stripped)
    if span_match:
        candidate = span_match.group(1)
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            shrunk = _shrink_to_balanced(candidate)
            if shrunk is not None:
                try:
                    return json.loads(shrunk)
                except (json.JSONDecodeError, ValueError):
                    pass

    logger.warning(
        "extract_json: no JSON value found in %d chars", len(text),
    )
    return None


def _shrink_to_balanced(s: str) -> str | None:
    """Walk ``s`` and return the slice ending at the first balanced close.

    The input must begin with ``{`` or ``[``; the function returns the
    smallest prefix whose brace/bracket depth returns to zero. Strings
    inside the JSON are skipped so braces/brackets inside string literals
    do not perturb the depth counter. Backslash escapes inside strings
    are honoured.

    Returns ``None`` when ``s`` does not start with an opener or never
    balances.
    """
    if not s:
        return None
    open_ch = s[0]
    if open_ch == "{":
        close_ch = "}"
    elif open_ch == "[":
        close_ch = "]"
    else:
        return None

    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(s):
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return s[: i + 1]
    return None

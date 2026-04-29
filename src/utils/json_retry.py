"""Single-retry helper for malformed JSON output from Gemini.

When the api_keys pool downshifts the served model (Gemini 3 Pro ->
2.5 Pro -> 2.5 Flash per F16), the lower tiers occasionally wrap their
JSON in prose or markdown fences despite the prompt's "JSON only"
instruction. ``extract_json`` recovers most of those; this module
covers the residual cases by re-prompting once with the malformed
output appended as negative context.

Public surface:
    ``retry_on_malformed_json(call, base_user_message)``
        Run ``call(user_message)``, parse with ``extract_json``, and
        retry once on parse failure. Returns
        ``(parsed_json, raw_result_dict)`` on success or ``None`` after
        the second failure.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from src.utils.json_extract import extract_json

logger = logging.getLogger(__name__)

# Appended to the retry prompt verbatim. Worded to remind the model
# that the *previous* output failed -- not the schema itself -- so it
# does not invent new fields trying to "fix" the earlier reply.
RETRY_INSTRUCTION = (
    "\n\nYour previous output was not valid JSON or did not match the "
    "required schema. Return ONLY the JSON object specified in the "
    "Output Format section. No prose. No markdown fences. No commentary."
)

# Cap how much of the malformed output we echo back. Gemini's input
# window is large but the malformed reply itself is often the cause of
# downstream truncation, so we trim it.
_PREVIOUS_OUTPUT_BUDGET = 2000


async def retry_on_malformed_json(
    call: Callable[[str], Awaitable[dict]],
    base_user_message: str,
) -> tuple[Any, dict] | None:
    """Run ``call`` with one retry on malformed JSON output.

    The ``call`` callable must accept a single user-message string and
    return a dict shaped like ``GeminiClient.generate``'s result -- at
    minimum a ``text`` key. Workers typically wrap their existing
    ``client.generate(...)`` call in a closure that captures the system
    prompt and other kwargs, leaving only ``user_message`` variable.

    On the first parse failure, the helper appends the malformed output
    (truncated) and an explicit "Return ONLY the JSON object" reminder,
    then issues exactly one more call. On success the parsed value plus
    the raw call result (for token bookkeeping etc.) are returned. On
    second failure the helper logs and returns ``None`` -- callers
    decide whether to skip the work item, persist a partial record, or
    raise.

    Args:
        call: Async callable accepting one ``str`` and returning a dict
            with at least a ``text`` field.
        base_user_message: The user message to send on the first
            attempt.

    Returns:
        ``(parsed_value, raw_result_dict)`` on success, ``None`` on
        second failure.
    """
    first = await call(base_user_message)
    parsed = extract_json(first.get("text", ""))
    if parsed is not None:
        return parsed, first

    logger.warning(
        "retry_on_malformed_json: first attempt malformed, retrying",
    )
    retry_msg = _build_retry_message(
        base_user_message, first.get("text", ""),
    )
    second = await call(retry_msg)
    parsed = extract_json(second.get("text", ""))
    if parsed is not None:
        return parsed, second

    logger.error(
        "retry_on_malformed_json: second attempt also malformed; "
        "giving up",
    )
    return None


def _build_retry_message(base: str, previous_output: str) -> str:
    """Construct the second-attempt user message.

    Echoes the truncated previous output back to the model as negative
    context, then re-states the JSON-only requirement.
    """
    truncated = (previous_output or "")[:_PREVIOUS_OUTPUT_BUDGET]
    return (
        f"{base}\n\n"
        f"--- Your previous output (do not repeat) ---\n"
        f"{truncated}\n"
        f"--- End previous output ---{RETRY_INSTRUCTION}"
    )

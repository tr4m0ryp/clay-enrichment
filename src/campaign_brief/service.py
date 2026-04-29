"""Campaign brief generator + regenerate handler.

Two synchronous (in-request) Gemini grounded structured calls. The web
layer (task 015) calls ``generate_campaign_brief`` when the user clicks
Next on the campaign creation form, and ``regenerate_sample_email`` on
each Regenerate-with-feedback click.

Output schema is invariant across served-model tiers (per F16): both
functions return ``{icp_brief, voice_profile, banned_phrases,
sample_email_subject, sample_email_body}`` or ``None``. Prompts are
strict (Strict Prompt Template), JSON parsing is tolerant
(``extract_json``), and one retry is performed on malformed output
(``retry_on_malformed_json``). On the regenerate path the locked fields
are force-preserved from ``prior_brief`` even if the model drifted, so
the user's prior voice and banned phrases survive any regeneration.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from src.campaign_brief.prompts import GENERATE_BRIEF, REGENERATE_SAMPLE
from src.gemini.client import GeminiClient
from src.utils.json_retry import retry_on_malformed_json

logger = logging.getLogger(__name__)

# Match the prompt's required keys. Used by ``_validate`` to gate the
# return value -- a brief with missing keys is treated as a model
# failure and surfaces ``None`` so the caller can show an error rather
# than persist a partial row.
REQUIRED_KEYS: frozenset[str] = frozenset({
    "icp_brief",
    "voice_profile",
    "banned_phrases",
    "sample_email_subject",
    "sample_email_body",
})

# Cap how much user-supplied free text we forward in the user_message
# (the prompt itself already has the full text). The user_message is a
# concise summary line; long target descriptions or feedback strings
# are truncated to keep tokens predictable.
_TARGET_PREVIEW = 500
_FEEDBACK_PREVIEW = 1000


async def generate_campaign_brief(
    gemini_client: GeminiClient,
    name: str,
    target_description: str,
    sample_emails: Optional[list[str]] = None,
) -> Optional[dict[str, Any]]:
    """Run one Gemini grounded structured call to draft the brief.

    Returns the parsed brief dict containing the five required keys, or
    ``None`` when the input is empty, the JSON could not be recovered
    after one retry, or the parsed value failed schema validation.

    Args:
        gemini_client: pool-backed Gemini client (per src/gemini/client.py).
        name: short campaign name. Empty string allowed; the prompt
            still works without it.
        target_description: free-text description of the campaign's
            target audience. Required -- empty input returns ``None``.
        sample_emails: optional list of 1-3 example cold emails the
            user pasted in for tone calibration. ``None`` and ``[]``
            are both treated as "no samples".

    Returns:
        ``{icp_brief, voice_profile, banned_phrases, sample_email_subject,
        sample_email_body}`` on success, ``None`` on validation or parse
        failure.
    """
    if not target_description:
        return None

    samples_str = "\n---\n".join(sample_emails) if sample_emails else ""

    rendered_prompt = (
        GENERATE_BRIEF
        .replace("{campaign_name}", name or "")
        .replace("{target_description}", target_description)
        .replace("{sample_emails}", samples_str)
    )

    call = _build_call(gemini_client, rendered_prompt)

    base_msg = (
        f"Generate the campaign brief for: {name or '(unnamed campaign)'}\n"
        f"Target: {target_description[:_TARGET_PREVIEW]}"
    )

    result = await retry_on_malformed_json(call, base_msg)
    if result is None:
        logger.warning(
            "generate_campaign_brief: JSON unrecoverable after retry "
            "for campaign=%r",
            name,
        )
        return None

    parsed, _raw = result
    if not _validate(parsed):
        logger.warning(
            "generate_campaign_brief: schema validation failed for "
            "campaign=%r; keys=%r",
            name,
            list(parsed.keys()) if isinstance(parsed, dict) else type(parsed),
        )
        return None

    return parsed


async def regenerate_sample_email(
    gemini_client: GeminiClient,
    name: str,
    target_description: str,
    prior_brief: dict[str, Any],
    user_feedback: str,
) -> Optional[dict[str, Any]]:
    """Run one Gemini grounded structured call to update the sample email.

    The user only edited the sample, not the voice. This function
    force-preserves ``icp_brief``, ``voice_profile``, and
    ``banned_phrases`` from ``prior_brief`` after parsing -- if the
    model drifted on those fields the drifted values are discarded.

    Returns the parsed brief dict containing the five required keys
    (with the three locked fields overwritten from ``prior_brief``), or
    ``None`` when the input is empty, the JSON could not be recovered
    after one retry, or the parsed value failed schema validation.

    Args:
        gemini_client: pool-backed Gemini client.
        name: short campaign name. Empty string allowed.
        target_description: free-text campaign target description.
            Empty string allowed; the locked voice profile is the
            primary tone reference for this call.
        prior_brief: the prior brief dict whose icp_brief,
            voice_profile, and banned_phrases must be preserved
            verbatim. ``sample_email_subject`` and ``sample_email_body``
            are echoed into the prompt as the previous draft.
        user_feedback: free-text user feedback that drives the new
            sample. Empty/non-string input returns ``None``.

    Returns:
        ``{icp_brief, voice_profile, banned_phrases, sample_email_subject,
        sample_email_body}`` on success, ``None`` on validation or parse
        failure.
    """
    if not user_feedback or not isinstance(prior_brief, dict):
        return None

    rendered_prompt = (
        REGENERATE_SAMPLE
        .replace("{campaign_name}", name or "")
        .replace("{target_description}", target_description or "")
        .replace(
            "{prior_voice_profile}",
            str(prior_brief.get("voice_profile", "")),
        )
        .replace(
            "{prior_banned_phrases}",
            str(prior_brief.get("banned_phrases", [])),
        )
        .replace(
            "{prior_sample_subject}",
            str(prior_brief.get("sample_email_subject", "")),
        )
        .replace(
            "{prior_sample_body}",
            str(prior_brief.get("sample_email_body", "")),
        )
        .replace("{user_feedback}", user_feedback[:_FEEDBACK_PREVIEW])
    )

    call = _build_call(gemini_client, rendered_prompt)

    base_msg = (
        f"Regenerate the sample email for: {name or '(unnamed campaign)'}\n"
        f"User feedback: {user_feedback[:_TARGET_PREVIEW]}"
    )

    result = await retry_on_malformed_json(call, base_msg)
    if result is None:
        logger.warning(
            "regenerate_sample_email: JSON unrecoverable after retry "
            "for campaign=%r",
            name,
        )
        return None

    parsed, _raw = result
    if not _validate(parsed):
        logger.warning(
            "regenerate_sample_email: schema validation failed for "
            "campaign=%r; keys=%r",
            name,
            list(parsed.keys()) if isinstance(parsed, dict) else type(parsed),
        )
        return None

    # Force-preserve the locked fields from prior_brief in case the
    # model drifted. The user only edited the sample; voice and bans
    # are immutable for this call.
    parsed["icp_brief"] = prior_brief.get(
        "icp_brief", parsed.get("icp_brief", "")
    )
    parsed["voice_profile"] = prior_brief.get(
        "voice_profile", parsed.get("voice_profile", "")
    )
    parsed["banned_phrases"] = prior_brief.get(
        "banned_phrases", parsed.get("banned_phrases", [])
    )

    return parsed


def _build_call(
    gemini_client: GeminiClient,
    rendered_prompt: str,
) -> Callable[[str], Awaitable[dict[str, Any]]]:
    """Return a closure suitable for ``retry_on_malformed_json``.

    The closure captures the system prompt and the grounded + json_mode
    flags so the only variable on retry is the user_message, per the
    contract of ``retry_on_malformed_json``.
    """

    async def _call(user_message: str) -> dict[str, Any]:
        return await gemini_client.generate(
            prompt=rendered_prompt,
            user_message=user_message,
            # No grounding here: the brief synthesises voice from the
            # user's own target description + sample emails, not fresh
            # web facts. Gemini 2.5 also rejects grounding + json_mode
            # combined (per F16), and grounded search has separate
            # quota that's frequently exhausted on free-tier keys.
            grounding=False,
            json_mode=True,
            # Synchronous user-facing path; let the pool exhaust the top
            # tier and descend rather than failing fast at default 5.
            max_retries=30,
        )

    return _call


def _validate(parsed: Any) -> bool:
    """Return ``True`` when ``parsed`` is a dict with all required keys.

    The parsed value must be a ``dict`` and contain every key in
    ``REQUIRED_KEYS``. Extra keys are tolerated (the caller drops them
    on persistence) but missing keys are a hard failure -- workers
    downstream rely on every key being present.
    """
    return isinstance(parsed, dict) and REQUIRED_KEYS.issubset(parsed.keys())

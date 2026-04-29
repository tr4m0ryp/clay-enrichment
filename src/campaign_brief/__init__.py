"""Campaign brief feature package.

Re-exports the two public service entrypoints so callers can write
``from src.campaign_brief import generate_campaign_brief,
regenerate_sample_email`` without reaching into the submodule layout.

Per task 008 of the campaign-creation-redesign launch: the web layer
(task 015) drives both functions when the user clicks Next on the
campaign creation form (``generate_campaign_brief``) and again when they
hit Regenerate-with-feedback on the sample email
(``regenerate_sample_email``). Both calls return the same five-key
brief dict so the caller's persistence path is uniform.
"""

from __future__ import annotations

from src.campaign_brief.service import (
    generate_campaign_brief,
    regenerate_sample_email,
)

__all__ = ["generate_campaign_brief", "regenerate_sample_email"]

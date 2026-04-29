"""Shared dataclasses for the discovery strategy rotation.

`StrategyContext` is the single input the worker assembles per cycle and
hands to the picked strategy. `Strategy` is the dataclass that pairs an
id / human name / tier with the build callable.

Living in their own module so the per-tier strategy files (tier1.py,
tier2.py, tier3.py) can import them without depending on the top-level
package `__init__` (which itself imports from those tier files).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class StrategyContext:
    """Inputs the discovery worker assembles per cycle.

    Fields:
        icp_brief: campaigns.icp_brief, the AI-distilled ICP description.
        target_description: campaigns.target_description -- legacy
            free-text target. Used as fallback when icp_brief is empty.
        excluded_names: already-known company names to exclude. Worker
            caps this list at ~150 names before passing it in.
        top_seeds: top-DPP-score companies for the campaign, used by S10
            adjacency. Worker passes top 3.
        geo_index: rotates inside S07 (Geographic) -- worker increments
            independently of the outer rotation index.
        sub_niche_index: rotates inside S08 (Sub-niche).
        cert_index: rotates inside S09 (Certification).
    """

    icp_brief: str
    target_description: str
    excluded_names: list[str]
    top_seeds: list[str]
    geo_index: int
    sub_niche_index: int
    cert_index: int


@dataclass(frozen=True)
class Strategy:
    """One discovery strategy in the 13-strategy rotation.

    Attributes:
        id: stable id "S01".."S13".
        name: human-readable name (e.g. "Hiring signal").
        tier: 1, 2, or 3 per the F15 tier definitions.
        build: callable that takes a StrategyContext and returns
            (system_prompt, user_message) for one Gemini grounded
            structured call.
    """

    id: str
    name: str
    tier: int
    build: Callable[[StrategyContext], tuple[str, str]]

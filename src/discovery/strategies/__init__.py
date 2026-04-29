"""13 discovery strategies for continuous-loop multi-strategy rotation.

Per research F15:
  Tier 1 (intent signals, highest freshness):
    S01 Hiring, S02 Funding, S03 Leadership change, S04 Product launch,
    S05 Market expansion, S06 Regulatory.
  Tier 2 (breadth coverage):
    S07 Geography, S08 Sub-niche, S09 Certification, S10 Adjacency.
  Tier 3 (long tail):
    S11 Trade shows, S12 Awards, S13 Media lists.

Each strategy returns (system_prompt, user_message) for a single Gemini
grounded structured call. The discovery worker (task 011) picks one
strategy per cycle by `campaigns.discovery_strategy_index % 13`.

Public API:
- STRATEGIES: list[Strategy] -- the 13 strategies in S01..S13 order.
- pick_strategy(index): return STRATEGIES[index % 13].
- StrategyContext: dataclass of inputs the worker assembles per cycle.
- Strategy: dataclass pairing id / name / tier / build callable.
"""

from __future__ import annotations

from .context import Strategy, StrategyContext
from .tier1 import (
    _build_S01,
    _build_S02,
    _build_S03,
    _build_S04,
    _build_S05,
    _build_S06,
)
from .tier2 import _build_S07, _build_S08, _build_S09, _build_S10
from .tier3 import _build_S11, _build_S12, _build_S13

STRATEGIES: list[Strategy] = [
    Strategy("S01", "Hiring signal", 1, _build_S01),
    Strategy("S02", "Funding signal", 1, _build_S02),
    Strategy("S03", "Leadership change", 1, _build_S03),
    Strategy("S04", "Product launch", 1, _build_S04),
    Strategy("S05", "Market expansion", 1, _build_S05),
    Strategy("S06", "Regulatory", 1, _build_S06),
    Strategy("S07", "Geographic", 2, _build_S07),
    Strategy("S08", "Sub-niche", 2, _build_S08),
    Strategy("S09", "Certification", 2, _build_S09),
    Strategy("S10", "Adjacency", 2, _build_S10),
    Strategy("S11", "Trade shows", 3, _build_S11),
    Strategy("S12", "Awards", 3, _build_S12),
    Strategy("S13", "Media lists", 3, _build_S13),
]


def pick_strategy(index: int) -> Strategy:
    """Return STRATEGIES[index % 13].

    The discovery worker stores `campaigns.discovery_strategy_index` and
    increments it each cycle. This helper handles the modulo so callers
    don't have to.
    """
    return STRATEGIES[index % len(STRATEGIES)]


__all__ = [
    "STRATEGIES",
    "Strategy",
    "StrategyContext",
    "pick_strategy",
]

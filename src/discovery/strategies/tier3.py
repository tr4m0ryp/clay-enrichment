"""Tier 3 discovery strategies (S11-S13) -- long-tail signals.

Trade shows, awards, and curated media lists surface the long tail of
emerging brands that headline search rarely returns. Per F15 these run
in the rotation alongside Tier 1 / Tier 2 -- not less often -- because
event-driven and editorial-driven discovery have their own freshness
cadence (fashion-week schedule, award-cycle, monthly editorial drops).

All three strategies emit the SAME JSON array schema defined in
`output_format.COMPANY_LIST_OUTPUT_FORMAT`. The "signal" field is empty
string for Tier 3 per the schema.
"""

from __future__ import annotations

from src.prompts.base_context import build_system_prompt

from .context import StrategyContext
from .output_format import COMPANY_LIST_OUTPUT_FORMAT, format_excluded_names


def _user_message(ctx: StrategyContext) -> str:
    """Tier 3 strategies share the same user-message body."""
    icp = ctx.icp_brief or ctx.target_description or "EU mid-market fashion brands"
    return (
        f"ICP_BRIEF: {icp}\n"
        f"EXCLUDED_NAMES: {format_excluded_names(ctx.excluded_names)}\n"
        "\n"
        "Run the strategy now. Return up to 10 companies as a JSON array per the schema."
    )


def _build_S11(ctx: StrategyContext) -> tuple[str, str]:
    """S11 -- Trade show exhibitor lists."""
    icp = ctx.icp_brief or ctx.target_description or "EU mid-market fashion brands"
    task = f"""\
## Task
Find ICP-matching brands listed as exhibitors at recent EU fashion trade shows.

## Inputs
- ICP_BRIEF: {icp}
- EXCLUDED_NAMES: {format_excluded_names(ctx.excluded_names)}

## Process
1. Use Google Search grounding to find official exhibitor / showroom lists from recent EU trade shows: Premium Berlin 2026, Pitti Uomo, Copenhagen Fashion Week emerging brands programs (e.g. Zalando ZN, Ciff Newtalent), Splash Berlin, MICAM Milano, Who's Next Paris, Tranoi Paris, Neonyt Frankfurt. Prefer the most recent edition (this season or last season).
2. For each exhibitor, verify it is a brand (not a service / supplier / retailer) and matches the ICP (mid-market EU, 20-500 employees, fashion / streetwear / lifestyle / footwear / accessories).
3. Filter out any company in EXCLUDED_NAMES (case-insensitive). Filter out competitors and large enterprises per Hard Rules.
4. Return up to 10 unique companies. Leave the "signal" field as an empty string -- this is a Tier 3 breadth strategy.

{COMPANY_LIST_OUTPUT_FORMAT}
"""
    return build_system_prompt(task), _user_message(ctx)


def _build_S12(ctx: StrategyContext) -> tuple[str, str]:
    """S12 -- Awards / recognition lists."""
    icp = ctx.icp_brief or ctx.target_description or "EU mid-market fashion brands"
    task = f"""\
## Task
Find ICP-matching brands recognized in recent fashion awards and industry recognition lists.

## Inputs
- ICP_BRIEF: {icp}
- EXCLUDED_NAMES: {format_excluded_names(ctx.excluded_names)}

## Process
1. Use Google Search grounding to find recent finalist / winner lists for: Drapers Sustainable Fashion Awards, BoF 500, Forbes 30 Under 30 Europe Fashion, LVMH Prize finalists, ANDAM finalists, Hyeres Festival, Woolmark Prize, Common Objective Awards. Prefer the most recent edition (last 12 months).
2. For each recognized brand, verify it matches the ICP (mid-market EU, 20-500 employees, fashion / streetwear / lifestyle).
3. Filter out any company in EXCLUDED_NAMES (case-insensitive). Filter out competitors and large enterprises per Hard Rules.
4. Return up to 10 unique companies. Leave the "signal" field as an empty string -- this is a Tier 3 breadth strategy.

{COMPANY_LIST_OUTPUT_FORMAT}
"""
    return build_system_prompt(task), _user_message(ctx)


def _build_S13(ctx: StrategyContext) -> tuple[str, str]:
    """S13 -- Media-list discovery."""
    icp = ctx.icp_brief or ctx.target_description or "EU mid-market fashion brands"
    task = f"""\
## Task
Find ICP-matching brands featured in curated media lists from the last 6 months.

## Inputs
- ICP_BRIEF: {icp}
- EXCLUDED_NAMES: {format_excluded_names(ctx.excluded_names)}

## Process
1. Use Google Search grounding to find recent (last 6 months) curated editorial roundups: Business of Fashion EU emerging brands lists, Vogue Business sustainable EU brands features, Highsnobiety / Hypebeast emerging brand columns, BoF 'brand to know' columns, Drapers ones-to-watch, Wallpaper* fashion features, Dazed up-and-coming, FashionUnited new-brands columns.
2. For each featured brand, verify it matches the ICP (mid-market EU, 20-500 employees, fashion / streetwear / lifestyle).
3. Filter out any company in EXCLUDED_NAMES (case-insensitive). Filter out competitors and large enterprises per Hard Rules.
4. Return up to 10 unique companies. Leave the "signal" field as an empty string -- this is a Tier 3 breadth strategy.

{COMPANY_LIST_OUTPUT_FORMAT}
"""
    return build_system_prompt(task), _user_message(ctx)

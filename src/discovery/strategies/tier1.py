"""Tier 1 discovery strategies (S01-S06) -- intent signals.

Each strategy targets a different "in motion" event class -- hiring,
funding, leadership change, product launch, market expansion, regulatory
preparation. These are the highest-freshness slices of the universe per
research F15. Re-running the same strategy a week later returns NEW
companies because new events have occurred.

All six strategies emit the SAME JSON array schema defined in
`output_format.COMPANY_LIST_OUTPUT_FORMAT`.
"""

from __future__ import annotations

from src.prompts.base_context import build_system_prompt

from .context import StrategyContext
from .output_format import COMPANY_LIST_OUTPUT_FORMAT, format_excluded_names


def _user_message(ctx: StrategyContext) -> str:
    """Tier 1 strategies share the same user-message body.

    The user message restates ICP and excluded names so the model has
    them in both system + user context (defends against tier downshift
    losing system context fidelity).
    """
    icp = ctx.icp_brief or ctx.target_description or "EU mid-market fashion brands"
    return (
        f"ICP_BRIEF: {icp}\n"
        f"EXCLUDED_NAMES: {format_excluded_names(ctx.excluded_names)}\n"
        "\n"
        "Run the strategy now. Return up to 10 companies as a JSON array per the schema."
    )


def _build_S01(ctx: StrategyContext) -> tuple[str, str]:
    """S01 -- Hiring signal."""
    icp = ctx.icp_brief or ctx.target_description or "EU mid-market fashion brands"
    task = f"""\
## Task
Find ICP-matching brands that posted a sustainability, compliance, or DPP-adjacent role in the last 60 days.

## Inputs
- ICP_BRIEF: {icp}
- EXCLUDED_NAMES: {format_excluded_names(ctx.excluded_names)}

## Process
1. Use Google Search grounding to find recent (last 60 days) job postings on LinkedIn, careers pages, BoF Careers, FashionUnited, and brand newsrooms for roles like "Head of Sustainability", "ESG Manager", "Compliance Lead", "Digital Product Passport Lead", "Traceability Manager", "Supply Chain Sustainability".
2. For each job posting, identify the hiring company. Verify the company matches the ICP (mid-market EU fashion / streetwear / lifestyle).
3. Filter out any company in EXCLUDED_NAMES (case-insensitive). Filter out competitors and large enterprises per Hard Rules.
4. Return up to 10 unique companies. Populate the "signal" field with the specific role + when it was posted.

{COMPANY_LIST_OUTPUT_FORMAT}
"""
    return build_system_prompt(task), _user_message(ctx)


def _build_S02(ctx: StrategyContext) -> tuple[str, str]:
    """S02 -- Funding signal."""
    icp = ctx.icp_brief or ctx.target_description or "EU mid-market fashion brands"
    task = f"""\
## Task
Find ICP-matching brands that closed a seed, Series A, or strategic funding round in the last 6 months.

## Inputs
- ICP_BRIEF: {icp}
- EXCLUDED_NAMES: {format_excluded_names(ctx.excluded_names)}

## Process
1. Use Google Search grounding to find recent (last 6 months) funding announcements on Crunchbase, BoF, EU-Startups, Sifted, TechCrunch Europe, FashionUnited, and brand press releases for fashion / streetwear / lifestyle / footwear / accessories / sustainable apparel companies.
2. For each round, identify the funded company. Verify it matches the ICP (mid-market EU fashion).
3. Filter out any company in EXCLUDED_NAMES (case-insensitive). Filter out competitors and large enterprises per Hard Rules.
4. Return up to 10 unique companies. Populate the "signal" field with the round size, type (seed / Series A / strategic), and announcement date.

{COMPANY_LIST_OUTPUT_FORMAT}
"""
    return build_system_prompt(task), _user_message(ctx)


def _build_S03(ctx: StrategyContext) -> tuple[str, str]:
    """S03 -- Leadership change."""
    icp = ctx.icp_brief or ctx.target_description or "EU mid-market fashion brands"
    task = f"""\
## Task
Find ICP-matching brands that announced a new CEO, CMO, Head of Sustainability, or Chief Brand Officer in the last 90 days.

## Inputs
- ICP_BRIEF: {icp}
- EXCLUDED_NAMES: {format_excluded_names(ctx.excluded_names)}

## Process
1. Use Google Search grounding to find recent (last 90 days) executive appointments via BoF, Drapers, FashionUnited, WWD, LinkedIn announcements, and company press releases. Focus on CEO, CMO, COO, Head of Sustainability, Chief Brand Officer, Chief Marketing Officer.
2. For each appointment, identify the appointing company. Verify it matches the ICP (mid-market EU fashion).
3. Filter out any company in EXCLUDED_NAMES (case-insensitive). Filter out competitors and large enterprises per Hard Rules.
4. Return up to 10 unique companies. Populate the "signal" field with the role + the new executive's name + the announcement date.

{COMPANY_LIST_OUTPUT_FORMAT}
"""
    return build_system_prompt(task), _user_message(ctx)


def _build_S04(ctx: StrategyContext) -> tuple[str, str]:
    """S04 -- Product launch."""
    icp = ctx.icp_brief or ctx.target_description or "EU mid-market fashion brands"
    task = f"""\
## Task
Find ICP-matching brands that launched a new collection or product line this quarter.

## Inputs
- ICP_BRIEF: {icp}
- EXCLUDED_NAMES: {format_excluded_names(ctx.excluded_names)}

## Process
1. Use Google Search grounding to find product / collection launch announcements from the current quarter on BoF, Hypebeast, Highsnobiety, Vogue Business, Drapers, brand newsrooms, and Instagram press posts. Focus on capsule collections, seasonal drops, brand-new product lines, and category extensions.
2. For each launch, identify the launching company. Verify it matches the ICP (mid-market EU fashion / streetwear / lifestyle).
3. Filter out any company in EXCLUDED_NAMES (case-insensitive). Filter out competitors and large enterprises per Hard Rules.
4. Return up to 10 unique companies. Populate the "signal" field with the launch name and approximate launch date.

{COMPANY_LIST_OUTPUT_FORMAT}
"""
    return build_system_prompt(task), _user_message(ctx)


def _build_S05(ctx: StrategyContext) -> tuple[str, str]:
    """S05 -- Market expansion."""
    icp = ctx.icp_brief or ctx.target_description or "EU mid-market fashion brands"
    task = f"""\
## Task
Find ICP-matching brands that just announced expansion into new EU markets, new flagship stores, or new EU distribution.

## Inputs
- ICP_BRIEF: {icp}
- EXCLUDED_NAMES: {format_excluded_names(ctx.excluded_names)}

## Process
1. Use Google Search grounding to find recent expansion announcements on BoF, FashionUnited, Drapers, Retail Dive Europe, brand press releases, and trade press for new flagship store openings, new country distribution, new wholesale partnerships in EU markets, or new pop-up programs in EU capitals.
2. For each expansion, identify the expanding company. Verify it matches the ICP (mid-market EU fashion).
3. Filter out any company in EXCLUDED_NAMES (case-insensitive). Filter out competitors and large enterprises per Hard Rules.
4. Return up to 10 unique companies. Populate the "signal" field with the expansion type (flagship / wholesale / new market) + the target city or country.

{COMPANY_LIST_OUTPUT_FORMAT}
"""
    return build_system_prompt(task), _user_message(ctx)


def _build_S06(ctx: StrategyContext) -> tuple[str, str]:
    """S06 -- Regulatory."""
    icp = ctx.icp_brief or ctx.target_description or "EU mid-market fashion brands"
    task = f"""\
## Task
Find ICP-matching brands publicly preparing for ESPR, EU Digital Product Passport, or EU Ecodesign for Sustainable Products Regulation.

## Inputs
- ICP_BRIEF: {icp}
- EXCLUDED_NAMES: {format_excluded_names(ctx.excluded_names)}

## Process
1. Use Google Search grounding to find brand statements, sustainability reports, ESG announcements, conference talks, podcast interviews, and LinkedIn posts referencing "ESPR", "Digital Product Passport", "DPP", "Ecodesign for Sustainable Products Regulation", "EU textile regulation", "traceability compliance", or "EU 2028 textile mandate".
2. For each public preparation signal, identify the speaking / publishing company. Verify it matches the ICP (mid-market EU fashion).
3. Filter out any company in EXCLUDED_NAMES (case-insensitive). Filter out competitors and large enterprises per Hard Rules.
4. Return up to 10 unique companies. Populate the "signal" field with a short quote or paraphrase of the regulatory signal + source date.

{COMPANY_LIST_OUTPUT_FORMAT}
"""
    return build_system_prompt(task), _user_message(ctx)

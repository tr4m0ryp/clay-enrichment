"""Tier 2 discovery strategies (S07-S10) -- breadth coverage.

S07 (Geography), S08 (Sub-niche), S09 (Certification) each have an
internal sub-rotation: the strategy picks one value from a fixed list
using `ctx.geo_index`, `ctx.sub_niche_index`, `ctx.cert_index` modulo
list length. This forces breadth across ICP axes -- per F15, without it
the model defaults to the same dominant slice every cycle.

S10 (Adjacency) takes the top 3 highest-DPP-score companies in the
campaign as positive seeds. If `ctx.top_seeds` is empty (early in the
campaign before scoring has produced winners), the prompt falls back to
a generic adjacency phrasing without specific seeds.

All four strategies emit the SAME JSON array schema defined in
`output_format.COMPANY_LIST_OUTPUT_FORMAT`. The "signal" field is
empty string for Tier 2 per the schema.
"""

from __future__ import annotations

from src.prompts.base_context import build_system_prompt

from .context import StrategyContext
from .output_format import (
    CERTIFICATIONS,
    COMPANY_LIST_OUTPUT_FORMAT,
    GEOGRAPHIES,
    SUB_NICHES,
    format_excluded_names,
)


def _user_message(ctx: StrategyContext) -> str:
    """Tier 2 strategies share the same user-message body."""
    icp = ctx.icp_brief or ctx.target_description or "EU mid-market fashion brands"
    return (
        f"ICP_BRIEF: {icp}\n"
        f"EXCLUDED_NAMES: {format_excluded_names(ctx.excluded_names)}\n"
        "\n"
        "Run the strategy now. Return up to 10 companies as a JSON array per the schema."
    )


def _build_S07(ctx: StrategyContext) -> tuple[str, str]:
    """S07 -- Geographic micro-segment."""
    icp = ctx.icp_brief or ctx.target_description or "EU mid-market fashion brands"
    geography = GEOGRAPHIES[ctx.geo_index % len(GEOGRAPHIES)]
    task = f"""\
## Task
Find ICP-matching brands headquartered in {geography}.

## Inputs
- ICP_BRIEF: {icp}
- GEOGRAPHY: {geography}
- EXCLUDED_NAMES: {format_excluded_names(ctx.excluded_names)}

## Process
1. Use Google Search grounding to find fashion / streetwear / lifestyle / apparel / footwear / accessories brands headquartered in {geography}. Search city-specific brand directories, local fashion week exhibitor lists, "best independent brands in {geography}" roundups, regional press, and city-specific business registries.
2. For each candidate, verify the headquarters city is {geography} and the company matches the ICP (mid-market: 20-500 employees, EU market presence, sustainability-aware).
3. Filter out any company in EXCLUDED_NAMES (case-insensitive). Filter out competitors and large enterprises per Hard Rules.
4. Return up to 10 unique companies. Leave the "signal" field as an empty string -- this is a Tier 2 breadth strategy, not an intent signal.

{COMPANY_LIST_OUTPUT_FORMAT}
"""
    return build_system_prompt(task), _user_message(ctx)


def _build_S08(ctx: StrategyContext) -> tuple[str, str]:
    """S08 -- Sub-niche cycling."""
    icp = ctx.icp_brief or ctx.target_description or "EU mid-market fashion brands"
    sub_niche = SUB_NICHES[ctx.sub_niche_index % len(SUB_NICHES)]
    task = f"""\
## Task
Find ICP-matching brands in the {sub_niche} category.

## Inputs
- ICP_BRIEF: {icp}
- SUB_NICHE: {sub_niche}
- EXCLUDED_NAMES: {format_excluded_names(ctx.excluded_names)}

## Process
1. Use Google Search grounding to find EU-based mid-market brands operating primarily in the {sub_niche} category. Search niche-specific buyer guides, BoF / Drapers / Vogue Business {sub_niche} roundups, retailer category pages, and trade publication brand-of-the-year lists.
2. For each candidate, verify {sub_niche} is a primary product line (not a one-off capsule) and the company matches the ICP (mid-market EU, 20-500 employees, sustainability-aware).
3. Filter out any company in EXCLUDED_NAMES (case-insensitive). Filter out competitors and large enterprises per Hard Rules.
4. Return up to 10 unique companies. Leave the "signal" field as an empty string -- this is a Tier 2 breadth strategy.

{COMPANY_LIST_OUTPUT_FORMAT}
"""
    return build_system_prompt(task), _user_message(ctx)


def _build_S09(ctx: StrategyContext) -> tuple[str, str]:
    """S09 -- Certification cycling."""
    icp = ctx.icp_brief or ctx.target_description or "EU mid-market fashion brands"
    certification = CERTIFICATIONS[ctx.cert_index % len(CERTIFICATIONS)]
    task = f"""\
## Task
Find ICP-matching brands that hold {certification} certification.

## Inputs
- ICP_BRIEF: {icp}
- CERTIFICATION: {certification}
- EXCLUDED_NAMES: {format_excluded_names(ctx.excluded_names)}

## Process
1. Use Google Search grounding to find EU-based mid-market fashion brands listed with {certification} certification. Search the official {certification} directory / member list, sustainability press coverage referencing {certification}, brand About / Sustainability pages naming {certification}, and B2B retailer filters tagging {certification}.
2. For each candidate, verify the certification is current and the company matches the ICP (mid-market EU, 20-500 employees).
3. Filter out any company in EXCLUDED_NAMES (case-insensitive). Filter out competitors and large enterprises per Hard Rules.
4. Return up to 10 unique companies. Leave the "signal" field as an empty string -- this is a Tier 2 breadth strategy.

{COMPANY_LIST_OUTPUT_FORMAT}
"""
    return build_system_prompt(task), _user_message(ctx)


def _build_S10(ctx: StrategyContext) -> tuple[str, str]:
    """S10 -- Adjacency walking from top-DPP-score seeds."""
    icp = ctx.icp_brief or ctx.target_description or "EU mid-market fashion brands"
    if ctx.top_seeds:
        seeds = ", ".join(ctx.top_seeds)
        seed_line = f"TOP_SEEDS: {seeds}"
        process_step = (
            f"1. Use Google Search grounding to find brands that are direct competitors or close adjacencies of: {seeds}. Search 'brands like {ctx.top_seeds[0]}', shared retailer category pages, comparable-brand editorial roundups (BoF, Vogue Business, Highsnobiety), and 'if you like X you'll like Y' content. Look for brands sharing the seed brands' price tier, audience, design ethos, or geographic market."
        )
    else:
        seed_line = "TOP_SEEDS: (none -- campaign has no scored winners yet, fall back to generic adjacency)"
        process_step = (
            "1. Use Google Search grounding to find ICP-matching brands that are close adjacencies to the canonical mid-market EU sustainable-fashion cluster (similar in price tier, audience, sustainability messaging, and DTC presence to brands like Filling Pieces, Ganni, Axel Arigato, Daily Paper, Nudie Jeans, Armedangels). Use comparable-brand editorial roundups (BoF, Vogue Business), retailer category pages, and 'similar brands' content."
        )
    task = f"""\
## Task
Find ICP-matching brands that are direct competitors or close adjacencies of the top-performing companies already in this campaign.

## Inputs
- ICP_BRIEF: {icp}
- {seed_line}
- EXCLUDED_NAMES: {format_excluded_names(ctx.excluded_names)}

## Process
{process_step}
2. For each candidate, verify it matches the ICP (mid-market EU, 20-500 employees, sustainability-aware) AND shares meaningful brand DNA with the seeds (or, if no seeds, with the canonical cluster).
3. Filter out any company in EXCLUDED_NAMES (case-insensitive). Filter out competitors and large enterprises per Hard Rules. Filter out the seed brands themselves.
4. Return up to 10 unique companies. Leave the "signal" field as an empty string -- this is a Tier 2 breadth strategy.

{COMPANY_LIST_OUTPUT_FORMAT}
"""
    return build_system_prompt(task), _user_message(ctx)

"""Discovery worker -- continuous loop, 13-strategy rotation.

Per research F4/F9/F15: each cycle, for each active campaign, pick the
strategy at ``campaigns.discovery_strategy_index % 13`` and run one
Gemini grounded structured call. Increment the index after the cycle.
After a full rotation the loop restarts from S01 -- but timeline-driven
strategies surface different companies because the world has moved.

The legacy 3-step pipeline (Gemini query-gen -> SearXNG/Brave search ->
Gemini parse) is gone; this worker no longer takes a search client.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID

from src.db.campaigns import CampaignsDB
from src.db.companies import CompaniesDB
from src.discovery.strategies import (
    STRATEGIES,
    Strategy,
    StrategyContext,
    pick_strategy,
)
from src.gemini.client import GeminiClient
from src.utils.json_retry import retry_on_malformed_json

logger = logging.getLogger(__name__)

_CYCLE_INTERVAL_SECONDS = 600  # 10 min between cycles -- halved
# discovery influx so high-priority leads don't pile up faster than
# Prospeo can resolve them (15-key pool sustains ~50/day at 1
# credit per call).
_EXCLUDE_CAP = 150  # most-recent N already-known names per campaign
_TOP_SEEDS_N = 3  # top-DPP-score companies for the adjacency strategy


@dataclass
class DBClients:
    """Container for the Postgres database helpers used by discovery."""

    campaigns: CampaignsDB
    companies: CompaniesDB


async def discovery_worker(
    config,
    gemini_client: GeminiClient,
    db_clients: DBClients,
) -> None:
    """Continuous discovery loop. Runs forever, polling for active campaigns.

    One strategy per active campaign per cycle. The strategy index is
    advanced regardless of whether new companies were discovered, so the
    rotation always progresses.
    """
    del config  # accepted for interface symmetry; no longer read here.
    logger.info("Discovery worker started (13-strategy rotation)")
    while True:
        try:
            campaigns = await db_clients.campaigns.get_active_campaigns()
            logger.info(
                "Discovery cycle: found %d active campaigns", len(campaigns),
            )
            for campaign in campaigns:
                try:
                    await _discover_one_strategy(
                        campaign, gemini_client, db_clients,
                    )
                except Exception:
                    logger.exception(
                        "Discovery: error on campaign '%s'",
                        campaign.get("name", "?"),
                    )
        except Exception:
            logger.exception("Discovery cycle error")
        await asyncio.sleep(_CYCLE_INTERVAL_SECONDS)


async def _discover_one_strategy(
    campaign: dict,
    gemini_client: GeminiClient,
    dbs: DBClients,
) -> None:
    """Run one strategy for one campaign, then advance the rotation."""
    campaign_id = str(campaign["id"])
    campaign_name = campaign.get("name", "?")
    icp_brief = (campaign.get("icp_brief") or "").strip()
    target_desc = (campaign.get("target_description") or "").strip()
    if not (icp_brief or target_desc):
        logger.warning(
            "Campaign '%s' has no ICP brief or target description, skipping",
            campaign_name,
        )
        return

    strategy_index = int(campaign.get("discovery_strategy_index") or 0)
    strategy = pick_strategy(strategy_index)

    excluded = await _build_exclude_list(
        dbs.companies, campaign_id, _EXCLUDE_CAP,
    )
    top_seeds = await _build_top_seeds(
        dbs.companies, campaign_id, n=_TOP_SEEDS_N,
    )

    ctx = StrategyContext(
        icp_brief=icp_brief,
        target_description=target_desc,
        excluded_names=excluded,
        top_seeds=top_seeds,
        # Sub-rotation indices are derived from the same outer counter so
        # that S07/S08/S09 also rotate through their value lists across
        # cycles. They wrap independently inside each strategy.
        geo_index=strategy_index,
        sub_niche_index=strategy_index,
        cert_index=strategy_index,
    )

    logger.info(
        "Discovery: campaign='%s' strategy=%s (%s) excluded=%d seeds=%d",
        campaign_name, strategy.id, strategy.name,
        len(excluded), len(top_seeds),
    )

    parsed = await _call_strategy(strategy, ctx, gemini_client)
    if parsed is None:
        await dbs.campaigns.increment_discovery_strategy_index(campaign_id)
        return

    new_count = await _persist_companies(
        parsed, strategy, campaign_id, dbs.companies,
    )

    logger.info(
        "Discovery: campaign='%s' strategy=%s new=%d",
        campaign_name, strategy.id, new_count,
    )
    await dbs.campaigns.increment_discovery_strategy_index(campaign_id)


async def _call_strategy(
    strategy: Strategy,
    ctx: StrategyContext,
    gemini_client: GeminiClient,
) -> list | None:
    """Build the prompt, run the grounded structured call, parse JSON.

    Returns the parsed JSON list on success, or ``None`` if the call
    failed or the output is not a list. The caller handles index
    advancement either way.
    """
    system_prompt, user_message = strategy.build(ctx)

    async def _call(msg: str) -> dict:
        return await gemini_client.generate(
            prompt=system_prompt,
            user_message=msg,
            # No grounding: Gemini 2.5 returns 400 on grounding+json_mode
            # combined (F16). The strategy prompt already carries the
            # campaign's icp_brief, exclusion list, and (for adjacency
            # strategies) top-DPP seeds, so the model has enough context
            # without fresh web search. Restore once tier-aware fallback
            # lands for grounded paths.
            grounding=False,
            json_mode=True,
            max_retries=30,
        )

    try:
        result = await retry_on_malformed_json(_call, user_message)
    except Exception:
        logger.exception(
            "Discovery: strategy=%s Gemini call failed", strategy.id,
        )
        return None

    if result is None:
        logger.warning(
            "Discovery: strategy=%s malformed JSON after retry", strategy.id,
        )
        return None

    parsed, _raw = result
    if not isinstance(parsed, list):
        logger.warning(
            "Discovery: strategy=%s expected JSON array, got %s",
            strategy.id, type(parsed).__name__,
        )
        return None
    return parsed


async def _persist_companies(
    parsed: list,
    strategy: Strategy,
    campaign_id: str,
    companies_db: CompaniesDB,
) -> int:
    """Insert or link each returned company. Returns count of new inserts."""
    new_count = 0
    source = f"{strategy.id} {strategy.name}"
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("company_name") or "").strip()
        if not name:
            continue
        website = (entry.get("website_url") or "").strip()
        try:
            existing = await companies_db.find_by_name(name)
            result = await companies_db.create_company(
                name=name,
                campaign_id=campaign_id,
                website=website,
                source_query=source,
            )
            if existing is None and result is not None:
                new_count += 1
        except Exception:
            logger.exception(
                "Discovery: failed to persist company '%s'", name,
            )
    return new_count


async def _build_exclude_list(
    companies_db: CompaniesDB,
    campaign_id: str,
    cap: int,
) -> list[str]:
    """Most-recent N already-known company names linked to the campaign.

    Direct ``_pool`` access mirrors the precedent in
    ``src/person_research/worker.py`` -- there is no typed wrapper for
    this join in ``CompaniesDB`` yet.
    """
    rows = await companies_db._pool.fetch(
        """
        SELECT c.name FROM companies c
        JOIN company_campaigns cc ON cc.company_id = c.id
        WHERE cc.campaign_id = $1
        ORDER BY c.created_at DESC
        LIMIT $2
        """,
        UUID(campaign_id),
        cap,
    )
    return [r["name"] for r in rows if r["name"]]


async def _build_top_seeds(
    companies_db: CompaniesDB,
    campaign_id: str,
    n: int = _TOP_SEEDS_N,
) -> list[str]:
    """Top-DPP-score companies for the campaign (adjacency strategy S10)."""
    rows = await companies_db._pool.fetch(
        """
        SELECT c.name FROM companies c
        JOIN company_campaigns cc ON cc.company_id = c.id
        WHERE cc.campaign_id = $1
          AND c.dpp_fit_score IS NOT NULL
        ORDER BY c.dpp_fit_score DESC
        LIMIT $2
        """,
        UUID(campaign_id),
        n,
    )
    return [r["name"] for r in rows if r["name"]]


__all__ = ["DBClients", "discovery_worker", "STRATEGIES"]

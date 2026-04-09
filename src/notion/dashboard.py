"""
Dashboard page layout builder for the Notion hub page.

Builds three sections: campaigns overview with instructions,
statistics table placeholder, and database links. Uses dividers,
callouts, and clean headings for a polished layout.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.config import get_config
from src.notion.client import NotionClient

logger = logging.getLogger(__name__)

_BLOCKS_FILE = Path(__file__).resolve().parents[2] / ".dashboard_blocks.json"

# -- Rich text helpers --------------------------------------------------------

def _text(content: str, bold: bool = False, italic: bool = False) -> dict:
    """Build a single rich_text element."""
    rt: dict = {"type": "text", "text": {"content": content}}
    annotations: dict = {}
    if bold:
        annotations["bold"] = True
    if italic:
        annotations["italic"] = True
    if annotations:
        rt["annotations"] = annotations
    return rt


def _paragraph(texts: list[dict] | None = None) -> dict:
    """Build a paragraph block. Empty paragraph if texts is None."""
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": texts or []},
    }


def _heading1(text: str) -> dict:
    """Build a heading_1 block."""
    return {
        "object": "block",
        "type": "heading_1",
        "heading_1": {"rich_text": [_text(text)]},
    }


def _divider() -> dict:
    """Build a divider block."""
    return {"object": "block", "type": "divider", "divider": {}}


def _callout(texts: list[dict], icon: str = "bulb") -> dict:
    """Build a callout block with an icon. Uses 'bulb' external icon."""
    icon_map = {
        "bulb": "https://www.notion.so/icons/light-bulb_gray.svg",
        "info": "https://www.notion.so/icons/info-alternate_gray.svg",
    }
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": texts,
            "icon": {"type": "external", "external": {"url": icon_map.get(icon, icon_map["bulb"])}},
        },
    }


def _link_to_page(database_id: str) -> dict:
    """Build a link_to_page block referencing a database."""
    return {
        "object": "block",
        "type": "link_to_page",
        "link_to_page": {"type": "database_id", "database_id": database_id},
    }


def _link_to_page_by_id(page_id: str) -> dict:
    """Build a link_to_page block referencing a page (not a database)."""
    return {
        "object": "block",
        "type": "link_to_page",
        "link_to_page": {"type": "page_id", "page_id": page_id},
    }


def _table(column_count: int, has_header: bool, rows: list[list[str]]) -> dict:
    """Build a table block with table_row children."""
    table_rows = []
    for row_data in rows:
        cells = [[_text(cell)] for cell in row_data]
        table_rows.append({
            "object": "block",
            "type": "table_row",
            "table_row": {"cells": cells},
        })
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": column_count,
            "has_column_header": has_header,
            "has_row_header": False,
            "children": table_rows,
        },
    }


# -- Section builders ---------------------------------------------------------

def _build_campaigns_section(campaigns_db_id: str) -> list[dict]:
    """Build the campaigns section blocks."""
    instruction_texts = [
        _text("How to use campaigns:\n\n", bold=True),
        _text("Create a campaign: "),
        _text("Add a row in the Campaigns database, fill in Name + Target Description, "
              "and set Status to Active.\n", italic=True),
        _text("Edit a campaign: "),
        _text("Click the campaign row and modify any properties.\n", italic=True),
        _text("Pause / resume: "),
        _text("Change the Status property to Paused or Active.\n\n", italic=True),
        _text("Tip: right-click the database link below and select "
              "'Turn into inline' for an embedded editable view.", bold=True),
    ]
    return [
        _heading1("// Campaigns"),
        _callout(instruction_texts),
        _paragraph(),
        _link_to_page(campaigns_db_id),
        _paragraph(),
        _divider(),
    ]


def _build_stats_section() -> list[dict]:
    """Build the statistics section blocks."""
    headers = [
        "Campaign", "Status", "Companies", "Contacts",
        "Usable Contacts", "Emails Pending", "Emails Sent", "Last Updated",
    ]
    placeholder_row = ["--"] * 8
    return [
        _heading1("// Pipeline Statistics"),
        _paragraph([_text(
            "Updated every 5 minutes. Metrics are computed from live database queries."
        )]),
        _paragraph(),
        _table(8, has_header=True, rows=[headers, placeholder_row]),
        _paragraph(),
        _divider(),
    ]


def _build_leads_section(config) -> list[dict]:
    """Build the High Priority Leads section blocks."""
    if not config.notion_leads_page_id:
        return []
    return [
        _heading1("// High Priority Leads"),
        _paragraph([
            _text("Filtered database of contacts scoring 7/10 or above, grouped by campaign."),
        ]),
        _paragraph(),
        _link_to_page_by_id(config.notion_leads_page_id),
        _paragraph(),
        _divider(),
    ]


def _build_databases_section(config) -> list[dict]:
    """Build the databases section blocks."""
    blocks = [
        _heading1("// Databases"),
        _paragraph([_text("Raw data tables powering the pipeline.")]),
        _paragraph(),
    ]

    db_entries = [
        (
            config.notion_campaigns_db_id,
            "Campaigns",
            "Active outreach campaigns with target descriptions and status tracking.",
        ),
        (
            config.notion_companies_db_id,
            "Companies",
            "Discovered and enriched companies with industry, DPP fit scores, and website data.",
        ),
        (
            config.notion_contacts_db_id,
            "Contacts",
            "Decision-makers found at target companies with verified emails and LinkedIn profiles.",
        ),
        (
            config.notion_emails_db_id,
            "Emails",
            "Generated outreach emails pending review, approved, or sent.",
        ),
    ]
    if config.notion_contact_campaigns_db_id:
        db_entries.append((
            config.notion_contact_campaigns_db_id,
            "Contact Campaigns",
            "Junction table linking contacts to campaigns with relevance scores and outreach status.",
        ))

    for db_id, label, description in db_entries:
        blocks.append(_paragraph([_text(label, bold=True)]))
        blocks.append(_paragraph([_text(description, italic=True)]))
        blocks.append(_link_to_page(db_id))

    return blocks


# -- Page clearing ------------------------------------------------------------

async def _clear_page(client: NotionClient, page_id: str) -> None:
    """Delete all existing child blocks from the hub page.

    Skips child_database and child_page blocks to preserve actual data.
    """
    existing = await client.get_page_body(page_id)
    skipped = 0
    for block in existing:
        btype = block.get("type")
        if btype in ("child_database", "child_page"):
            logger.debug("Keeping %s block %s", btype, block["id"])
            skipped += 1
            continue
        await client._call(client._sdk.blocks.delete, block_id=block["id"])
        logger.debug("Deleted block %s (type=%s)", block["id"], btype)

    logger.info("Cleared %d blocks from hub page %s (kept %d)",
                len(existing) - skipped, page_id, skipped)


# -- Block ID persistence ----------------------------------------------------

def _save_block_ids(hub_page_id: str, stats_table_id: str) -> None:
    """Persist dashboard block IDs to .dashboard_blocks.json."""
    data = {
        "stats_table_id": stats_table_id,
        "hub_page_id": hub_page_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _BLOCKS_FILE.write_text(json.dumps(data, indent=2))
    logger.info("Saved dashboard block IDs to %s", _BLOCKS_FILE)


# -- Public API ---------------------------------------------------------------

async def setup_dashboard(client: NotionClient, config=None) -> dict:
    """Build or rebuild the dashboard layout on the hub page.

    Clears existing page content and creates fresh layout with
    three sections: campaigns, statistics, and databases.

    Args:
        client: NotionClient instance for API calls.
        config: Optional config override. Defaults to get_config().

    Returns:
        Dict with block IDs needed for stats updates:
        {"stats_table_id": "...", "stats_section_id": "..."}
    """
    if config is None:
        config = get_config()

    hub_page_id = config.notion_hub_page_id
    if not hub_page_id:
        raise ValueError("notion_hub_page_id is not set in config")

    logger.info("Setting up dashboard on hub page %s", hub_page_id)

    # Clear existing content
    await _clear_page(client, hub_page_id)

    # Build all section blocks
    campaigns = _build_campaigns_section(config.notion_campaigns_db_id)
    leads = _build_leads_section(config)
    stats = _build_stats_section()

    all_blocks = campaigns + leads + stats + _build_databases_section(config)

    # Notion API limits appends to 100 blocks at a time
    for i in range(0, len(all_blocks), 100):
        batch = all_blocks[i : i + 100]
        await client.append_page_body(hub_page_id, batch)

    logger.info("Appended %d blocks to hub page", len(all_blocks))

    # Retrieve created blocks to find the stats table ID
    created_blocks = await client.get_page_body(hub_page_id)
    stats_table_id = ""
    stats_section_id = ""
    for block in created_blocks:
        if block.get("type") == "table":
            stats_table_id = block["id"]
        if block.get("type") == "heading_1":
            rt = block.get("heading_1", {}).get("rich_text", [])
            if rt and "Pipeline Statistics" in rt[0].get("plain_text", ""):
                stats_section_id = block["id"]

    if not stats_table_id:
        logger.warning("Could not locate stats table block after creation")

    # Persist block IDs for the stats updater
    _save_block_ids(hub_page_id, stats_table_id)

    result = {
        "stats_table_id": stats_table_id,
        "stats_section_id": stats_section_id,
    }
    logger.info("Dashboard setup complete: %s", result)
    return result

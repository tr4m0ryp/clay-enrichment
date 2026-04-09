"""Leads page manager for high-priority contacts per campaign."""

from __future__ import annotations

import asyncio
import logging

from src.notion.client import NotionClient
from src.notion.databases_campaigns import CampaignsDB
from src.notion.databases_contact_campaigns import ContactCampaignsDB
from src.notion.prop_helpers import (
    extract_title, extract_rich_text, extract_select,
    extract_number, extract_url, extract_email, extract_checkbox,
)

logger = logging.getLogger(__name__)

_TITLE_SUFFIX = " -- High Priority Leads"
_MIN_SCORE = 7.0


def _text(content: str, bold: bool = False) -> dict:
    rt: dict = {"type": "text", "text": {"content": content}}
    if bold:
        rt["annotations"] = {"bold": True}
    return rt


def _heading2(text: str) -> dict:
    return {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [_text(text)]}}


def _heading3(text: str) -> dict:
    return {"object": "block", "type": "heading_3",
            "heading_3": {"rich_text": [_text(text)]}}


def _paragraph(content: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [_text(content)] if content else []}}


def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _extract_phone(page: dict) -> str:
    prop = page.get("properties", {}).get("Phone", {})
    return prop.get("phone_number") or ""


def _extract_fields(entry: dict) -> dict:
    """Pull all display fields from a junction record."""
    return {
        "name": extract_title(entry, "Name"),
        "job_title": extract_rich_text(entry, "Job Title"),
        "company_name": extract_rich_text(entry, "Company Name"),
        "email": extract_email(entry, "Email"),
        "email_verified": extract_checkbox(entry, "Email Verified"),
        "phone": _extract_phone(entry),
        "linkedin_url": extract_url(entry, "LinkedIn URL"),
        "industry": extract_select(entry, "Industry"),
        "company_size": extract_rich_text(entry, "Company Size"),
        "location": extract_rich_text(entry, "Location"),
        "company_fit_score": extract_number(entry, "Company Fit Score") or 0,
        "relevance_score": extract_number(entry, "Relevance Score") or 0,
        "score_reasoning": extract_rich_text(entry, "Score Reasoning"),
        "personalized_context": extract_rich_text(entry, "Personalized Context"),
        "email_subject": extract_rich_text(entry, "Email Subject"),
        "outreach_status": extract_select(entry, "Outreach Status"),
    }


def _cell(content: str) -> list[dict]:
    """Build a single table cell (list of rich_text elements)."""
    return [_text(content[:2000])] if content else []


_TABLE_HEADERS = [
    "Contact", "Job Title", "Company", "Score", "Industry",
    "Location", "Email", "Status", "Context",
]


def _contact_row(f: dict) -> list[list[dict]]:
    """Build a table row from extracted contact fields."""
    name = f["name"].split(" - ")[0] if " - " in f["name"] else f["name"]
    vtag = " [v]" if f["email_verified"] else ""
    return [
        _cell(name),
        _cell(f["job_title"] or ""),
        _cell(f["company_name"] or ""),
        _cell(f"{int(f['relevance_score'])}/10"),
        _cell(f["industry"] or ""),
        _cell(f["location"] or ""),
        _cell((f["email"] or "") + vtag),
        _cell(f["outreach_status"] or "New"),
        _cell(f["personalized_context"] or f["score_reasoning"] or ""),
    ]


_MAX_TABLE_ROWS = 99  # Notion limit: 100 children per table (1 header + 99 data)


def _build_contacts_tables(entries_fields: list[dict]) -> list[dict]:
    """Build Notion table blocks, splitting into chunks of 99 rows each."""
    col_count = len(_TABLE_HEADERS)
    tables: list[dict] = []

    for start in range(0, len(entries_fields), _MAX_TABLE_ROWS):
        chunk = entries_fields[start : start + _MAX_TABLE_ROWS]
        header_row = {
            "object": "block",
            "type": "table_row",
            "table_row": {"cells": [_cell(h) for h in _TABLE_HEADERS]},
        }
        rows = [header_row]
        for f in chunk:
            rows.append({
                "object": "block",
                "type": "table_row",
                "table_row": {"cells": _contact_row(f)},
            })
        tables.append({
            "object": "block",
            "type": "table",
            "table": {
                "table_width": col_count,
                "has_column_header": True,
                "has_row_header": False,
                "children": rows,
            },
        })

    return tables


class LeadsPagesManager:
    """Manages per-campaign leads subpages under the High Priority Leads page."""

    def __init__(
        self,
        client: NotionClient,
        contact_campaigns_db: ContactCampaignsDB,
        leads_page_id: str,
    ) -> None:
        self._client = client
        self._cc_db = contact_campaigns_db
        self._leads_page_id = leads_page_id
        self._campaign_pages: dict[str, str] = {}  # campaign_id -> page_id

    async def _load_existing_subpages(self) -> None:
        """Scan child blocks of leads parent to discover existing subpages."""
        for block in await self._client.get_page_body(self._leads_page_id):
            if block.get("type") != "child_page":
                continue
            title = block.get("child_page", {}).get("title", "")
            if title.endswith(_TITLE_SUFFIX):
                self._campaign_pages.setdefault(title, block["id"])

    def _page_title(self, campaign_name: str) -> str:
        return f"{campaign_name}{_TITLE_SUFFIX}"

    async def ensure_campaign_page(self, campaign_id: str, campaign_name: str) -> str:
        """Create campaign leads subpage if it doesn't exist. Returns page ID."""
        if campaign_id in self._campaign_pages:
            return self._campaign_pages[campaign_id]

        # Check by title in loaded subpages
        title = self._page_title(campaign_name)
        if title in self._campaign_pages:
            page_id = self._campaign_pages[title]
            self._campaign_pages[campaign_id] = page_id
            return page_id

        # Create new child page under leads parent via Notion SDK
        result = await self._client._call(
            self._client._sdk.pages.create,
            parent={"type": "page_id", "page_id": self._leads_page_id},
            properties={"title": [{"text": {"content": title}}]},
            children=[],
        )
        page_id = result["id"]
        self._campaign_pages[campaign_id] = page_id
        self._campaign_pages[title] = page_id
        logger.info("Created leads subpage '%s' -> %s", title, page_id)
        return page_id

    async def _clear_page_body(self, page_id: str) -> None:
        """Delete all blocks from a page (parallel, batched)."""
        blocks = await self._client.get_page_body(page_id)
        sem = asyncio.Semaphore(10)

        async def _del(block_id: str) -> None:
            async with sem:
                await self._client._call(
                    self._client._sdk.blocks.delete, block_id=block_id
                )

        await asyncio.gather(*[_del(b["id"]) for b in blocks])

    async def update_campaign_page(
        self, campaign_id: str, campaign_name: str, target_desc: str = "",
    ) -> None:
        """Rebuild the campaign leads page with current high-priority entries."""
        page_id = await self.ensure_campaign_page(campaign_id, campaign_name)
        entries = await self._cc_db.get_high_priority(campaign_id, min_score=_MIN_SCORE)
        entries.sort(key=lambda e: extract_number(e, "Relevance Score") or 0, reverse=True)

        fields = [_extract_fields(e) for e in entries]

        blocks: list[dict] = [_heading2(f"Campaign: {campaign_name}")]
        if target_desc:
            blocks.append(_paragraph(target_desc))
        blocks.append(_divider())
        blocks.append(_heading2(f"High Priority Contacts ({len(entries)})"))
        if fields:
            blocks.extend(_build_contacts_tables(fields))
        else:
            blocks.append(_paragraph("No contacts with score >= 7 yet."))

        await self._clear_page_body(page_id)
        for i in range(0, len(blocks), 100):
            await self._client.append_page_body(page_id, blocks[i : i + 100])
        logger.info("Updated leads page for '%s': %d contacts", campaign_name, len(entries))

    async def update_parent_index(self, campaigns: list[dict]) -> None:
        """Update the parent page with links to all campaign subpages."""
        blocks: list[dict] = [_heading2("High Priority Leads")]

        for campaign in campaigns:
            cid = campaign["id"]
            name = extract_title(campaign, "Name")
            if cid not in self._campaign_pages:
                continue
            page_id = self._campaign_pages[cid]
            entries = await self._cc_db.get_high_priority(cid, min_score=_MIN_SCORE)
            count = len(entries)
            # Clickable link to campaign subpage
            blocks.append({
                "object": "block",
                "type": "link_to_page",
                "link_to_page": {"type": "page_id", "page_id": page_id},
            })
            blocks.append(_paragraph(f"{count} high-priority contacts"))

        # Clear parent body (skip child_page blocks) and rewrite index
        existing = await self._client.get_page_body(self._leads_page_id)
        for block in existing:
            if block.get("type") == "child_page":
                continue
            await self._client._call(
                self._client._sdk.blocks.delete, block_id=block["id"]
            )

        await self._client.append_page_body(self._leads_page_id, blocks)
        logger.info("Updated parent index with %d campaign links", len(campaigns))


# -- Top-level convenience function -------------------------------------------

async def refresh_leads_pages(
    client: NotionClient,
    contact_campaigns_db: ContactCampaignsDB,
    campaigns_db: CampaignsDB,
    leads_page_id: str,
) -> None:
    """Refresh all campaign leads pages. Call periodically."""
    manager = LeadsPagesManager(client, contact_campaigns_db, leads_page_id)
    await manager._load_existing_subpages()

    campaigns = await campaigns_db.get_active_campaigns()
    if not campaigns:
        logger.info("No active campaigns, skipping leads page refresh")
        return

    for campaign in campaigns:
        cid = campaign["id"]
        name = extract_title(campaign, "Name")
        target_desc = extract_rich_text(campaign, "Target Description")
        try:
            await manager.update_campaign_page(cid, name, target_desc)
        except Exception as exc:
            logger.error("Failed to update leads page for '%s': %s", name, exc)

    await manager.update_parent_index(campaigns)
    logger.info("Leads page refresh complete for %d campaigns", len(campaigns))

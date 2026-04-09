"""Leads page manager for high-priority contacts per campaign.

Creates an inline Notion database on each campaign's leads subpage,
populated with denormalized data from the Contact-Campaign junction table.
"""

from __future__ import annotations

import asyncio
import logging

from src.notion.client import NotionClient
from src.notion.databases_campaigns import CampaignsDB
from src.notion.databases_contact_campaigns import ContactCampaignsDB
from src.notion.databases_contact_campaigns_schema import (
    INDUSTRY_OPTIONS, OUTREACH_STATUSES,
)
from src.notion.prop_helpers import (
    extract_title, extract_rich_text, extract_select,
    extract_number, extract_url, extract_email, extract_checkbox,
    title_prop, rich_text_prop, select_prop, number_prop,
    email_prop, checkbox_prop, url_prop,
)

logger = logging.getLogger(__name__)

_TITLE_SUFFIX = " -- High Priority Leads"
_MIN_SCORE = 7.0
_CONCURRENCY = 10

# -- Inline database schema (mirrors junction table, no relations) -----------

_LEADS_DB_SCHEMA: dict = {
    "Name": {"title": {}},
    "Job Title": {"rich_text": {}},
    "Company": {"rich_text": {}},
    "Email": {"email": {}},
    "Email Verified": {"checkbox": {}},
    "LinkedIn URL": {"url": {}},
    "Industry": {
        "select": {"options": [{"name": o} for o in INDUSTRY_OPTIONS]},
    },
    "Location": {"rich_text": {}},
    "Company Fit Score": {"number": {"format": "number"}},
    "Relevance Score": {"number": {"format": "number"}},
    "Score Reasoning": {"rich_text": {}},
    "Personalized Context": {"rich_text": {}},
    "Context": {"rich_text": {}},
    "Email Subject": {"rich_text": {}},
    "Outreach Status": {
        "select": {"options": [{"name": s} for s in OUTREACH_STATUSES]},
    },
}


def _extract_fields(entry: dict) -> dict:
    """Pull all display fields from a junction record."""
    return {
        "name": extract_title(entry, "Name"),
        "job_title": extract_rich_text(entry, "Job Title"),
        "company_name": extract_rich_text(entry, "Company Name"),
        "email": extract_email(entry, "Email"),
        "email_verified": extract_checkbox(entry, "Email Verified"),
        "linkedin_url": extract_url(entry, "LinkedIn URL"),
        "industry": extract_select(entry, "Industry"),
        "location": extract_rich_text(entry, "Location"),
        "company_fit_score": extract_number(entry, "Company Fit Score") or 0,
        "relevance_score": extract_number(entry, "Relevance Score") or 0,
        "score_reasoning": extract_rich_text(entry, "Score Reasoning"),
        "personalized_context": extract_rich_text(entry, "Personalized Context"),
        "context": extract_rich_text(entry, "Context"),
        "email_subject": extract_rich_text(entry, "Email Subject"),
        "outreach_status": extract_select(entry, "Outreach Status"),
    }


def _fields_to_properties(f: dict) -> dict:
    """Convert extracted junction fields into Notion page properties."""
    name = f["name"].split(" - ")[0] if " - " in f["name"] else f["name"]
    props: dict = {"Name": title_prop(name)}
    if f["job_title"]:
        props["Job Title"] = rich_text_prop(f["job_title"])
    if f["company_name"]:
        props["Company"] = rich_text_prop(f["company_name"])
    if f["email"]:
        props["Email"] = email_prop(f["email"])
    if f["email_verified"]:
        props["Email Verified"] = checkbox_prop(True)
    if f["linkedin_url"]:
        props["LinkedIn URL"] = url_prop(f["linkedin_url"])
    if f["industry"]:
        props["Industry"] = select_prop(f["industry"])
    if f["location"]:
        props["Location"] = rich_text_prop(f["location"])
    if f["company_fit_score"]:
        props["Company Fit Score"] = number_prop(f["company_fit_score"])
    if f["relevance_score"]:
        props["Relevance Score"] = number_prop(f["relevance_score"])
    if f["score_reasoning"]:
        props["Score Reasoning"] = rich_text_prop(f["score_reasoning"])
    if f["personalized_context"]:
        props["Personalized Context"] = rich_text_prop(f["personalized_context"])
    if f["context"]:
        props["Context"] = rich_text_prop(f["context"])
    if f["email_subject"]:
        props["Email Subject"] = rich_text_prop(f["email_subject"])
    if f["outreach_status"]:
        props["Outreach Status"] = select_prop(f["outreach_status"])
    return props


# -- Block helpers (parent index only) ----------------------------------------

def _rich(text: str) -> list:
    return [{"type": "text", "text": {"content": text}}]

def _heading2(text: str) -> dict:
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rich(text)}}

def _heading3(text: str) -> dict:
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": _rich(text)}}

def _paragraph(content: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": _rich(content) if content else []}}

def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


# -- Manager class ------------------------------------------------------------

class LeadsPagesManager:
    """Manages per-campaign leads subpages with inline databases."""

    def __init__(self, client: NotionClient,
                 contact_campaigns_db: ContactCampaignsDB,
                 leads_page_id: str) -> None:
        self._client = client
        self._cc_db = contact_campaigns_db
        self._leads_page_id = leads_page_id
        self._campaign_pages: dict[str, str] = {}  # campaign_id|title -> page_id
        self._campaign_dbs: dict[str, str] = {}    # page_id -> database_id

    async def _load_existing_subpages(self) -> None:
        """Discover existing subpages and their inline databases."""
        for block in await self._client.get_page_body(self._leads_page_id):
            if block.get("type") != "child_page":
                continue
            title = block.get("child_page", {}).get("title", "")
            if title.endswith(_TITLE_SUFFIX):
                self._campaign_pages.setdefault(title, block["id"])
        for title, page_id in list(self._campaign_pages.items()):
            for block in await self._client.get_page_body(page_id):
                if block.get("type") == "child_database":
                    self._campaign_dbs[page_id] = block["id"]
                    break

    def _page_title(self, campaign_name: str) -> str:
        return f"{campaign_name}{_TITLE_SUFFIX}"

    async def ensure_campaign_page(self, cid: str, name: str) -> str:
        """Create campaign leads subpage if needed. Returns page ID."""
        if cid in self._campaign_pages:
            return self._campaign_pages[cid]
        title = self._page_title(name)
        if title in self._campaign_pages:
            pid = self._campaign_pages[title]
            self._campaign_pages[cid] = pid
            return pid
        result = await self._client._call(
            self._client._sdk.pages.create,
            parent={"type": "page_id", "page_id": self._leads_page_id},
            properties={"title": [{"text": {"content": title}}]},
            children=[],
        )
        pid = result["id"]
        self._campaign_pages[cid] = pid
        self._campaign_pages[title] = pid
        logger.info("Created leads subpage '%s' -> %s", title, pid)
        return pid

    async def _ensure_leads_db(self, page_id: str) -> str:
        """Find or create the inline leads database on a campaign subpage."""
        if page_id in self._campaign_dbs:
            return self._campaign_dbs[page_id]
        # Clean legacy blocks (old table format), preserve any existing DB
        blocks = await self._client.get_page_body(page_id)
        to_delete = [b["id"] for b in blocks if b.get("type") != "child_database"]
        if to_delete:
            sem = asyncio.Semaphore(_CONCURRENCY)
            async def _del(bid: str) -> None:
                async with sem:
                    await self._client._call(
                        self._client._sdk.blocks.delete, block_id=bid)
            await asyncio.gather(*[_del(bid) for bid in to_delete])
        # Create new inline database
        result = await self._client.create_database(
            parent_page_id=page_id,
            title="High Priority Leads",
            properties=_LEADS_DB_SCHEMA,
        )
        db_id = result["id"]
        self._campaign_dbs[page_id] = db_id
        logger.info("Created leads DB on page %s -> %s", page_id[:8], db_id[:8])
        return db_id

    async def _archive_db_entries(self, db_id: str) -> int:
        """Archive all existing entries in the leads database."""
        entries = await self._client.query_database(db_id)
        if not entries:
            return 0
        sem = asyncio.Semaphore(_CONCURRENCY)
        async def _archive(eid: str) -> None:
            async with sem:
                await self._client._call(
                    self._client._sdk.pages.update, page_id=eid, archived=True)
        await asyncio.gather(*[_archive(e["id"]) for e in entries])
        return len(entries)

    async def _populate_db(self, db_id: str, fields_list: list[dict]) -> None:
        """Create entries in the leads database from junction fields."""
        sem = asyncio.Semaphore(_CONCURRENCY)
        async def _create(f: dict) -> None:
            async with sem:
                await self._client.create_page(db_id, _fields_to_properties(f))
        await asyncio.gather(*[_create(f) for f in fields_list])

    async def update_campaign_page(self, campaign_id: str, campaign_name: str,
                                   target_desc: str = "") -> None:
        """Sync the inline leads database with current high-priority entries."""
        page_id = await self.ensure_campaign_page(campaign_id, campaign_name)
        entries = await self._cc_db.get_high_priority(campaign_id, min_score=_MIN_SCORE)
        entries.sort(
            key=lambda e: extract_number(e, "Relevance Score") or 0, reverse=True)
        fields = [_extract_fields(e) for e in entries]

        db_id = await self._ensure_leads_db(page_id)
        archived = await self._archive_db_entries(db_id)
        await self._populate_db(db_id, fields)
        logger.info("Leads DB '%s': archived=%d added=%d",
                     campaign_name, archived, len(fields))

    async def update_parent_index(self, campaigns: list[dict]) -> None:
        """Update the parent page with direct links to campaign leads databases."""
        blocks: list[dict] = [_heading2("High Priority Leads")]
        for campaign in campaigns:
            cid = campaign["id"]
            name = extract_title(campaign, "Name")
            target_desc = extract_rich_text(campaign, "Target Description")
            if cid not in self._campaign_pages:
                continue
            page_id = self._campaign_pages[cid]
            db_id = self._campaign_dbs.get(page_id)
            if not db_id:
                continue
            entries = await self._cc_db.get_high_priority(cid, min_score=_MIN_SCORE)
            blocks.append(_heading3(f"{name} ({len(entries)} leads)"))
            if target_desc:
                blocks.append(_paragraph(target_desc))
            blocks.append({
                "object": "block", "type": "link_to_page",
                "link_to_page": {"type": "database_id", "database_id": db_id},
            })
            blocks.append(_divider())
        existing = await self._client.get_page_body(self._leads_page_id)
        for block in existing:
            if block.get("type") == "child_page":
                continue
            await self._client._call(
                self._client._sdk.blocks.delete, block_id=block["id"])
        await self._client.append_page_body(self._leads_page_id, blocks)
        logger.info("Updated parent index with %d campaign links", len(campaigns))


# -- Top-level convenience function -------------------------------------------

async def refresh_leads_pages(
    client: NotionClient,
    contact_campaigns_db: ContactCampaignsDB,
    campaigns_db: CampaignsDB,
    leads_page_id: str,
) -> None:
    """Refresh all campaign leads databases. Call periodically."""
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
            logger.error("Failed to update leads DB for '%s': %s", name, exc)
    await manager.update_parent_index(campaigns)
    logger.info("Leads page refresh complete for %d campaigns", len(campaigns))

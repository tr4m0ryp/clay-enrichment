"""Leads page manager for high-priority contacts per campaign.

Creates an inline Notion database on each campaign's leads subpage,
populated with denormalized data from the Contact-Campaign junction table,
enriched with company website URLs and email content.
"""

from __future__ import annotations

import asyncio
import logging

from src.notion.client import NotionClient
from src.notion.databases_campaigns import CampaignsDB
from src.notion.databases_contact_campaigns import ContactCampaignsDB
from src.notion.databases_contact_campaigns_schema import OUTREACH_STATUSES
from src.notion.databases_emails import EmailsDB
from src.notion.prop_helpers import (
    extract_title, extract_rich_text, extract_select,
    extract_number, extract_url, extract_email, extract_checkbox,
    extract_relation_ids,
    title_prop, rich_text_prop, select_prop, number_prop,
    email_prop, checkbox_prop, url_prop,
)

logger = logging.getLogger(__name__)

_TITLE_SUFFIX = " -- High Priority Leads"
_MIN_SCORE = 7.0
_CONCURRENCY = 10

# Column order per design decision D1 (2026-04-12).
# Company is the title property so Notion places it first.

_LEADS_DB_SCHEMA: dict = {
    "Company": {"title": {}},
    "Website": {"url": {}},
    "Location": {"rich_text": {}},
    "Name": {"rich_text": {}},
    "Job Title": {"rich_text": {}},
    "LinkedIn URL": {"url": {}},
    "Email": {"email": {}},
    "Email Verified": {"checkbox": {}},
    "Email Subject": {"rich_text": {}},
    "Email Content": {"rich_text": {}},
    "Outreach Status": {
        "select": {"options": [{"name": s} for s in OUTREACH_STATUSES]},
    },
    "Company Fit Score": {"number": {"format": "number"}},
    "Relevance Score": {"number": {"format": "number"}},
    "Score Reasoning": {"rich_text": {}},
    "Context": {"rich_text": {}},
    "Personalized Context": {"rich_text": {}},
}


def _blocks_to_text(blocks: list[dict]) -> str:
    """Flatten Notion block children into a single text string."""
    parts: list[str] = []
    for block in blocks:
        btype = block.get("type", "")
        data = block.get(btype, {})
        rich = data.get("rich_text", [])
        text = "".join(r.get("plain_text", "") for r in rich)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _extract_fields(entry: dict) -> dict:
    """Pull display fields from a junction record."""
    return {
        "name": extract_title(entry, "Name"),
        "job_title": extract_rich_text(entry, "Job Title"),
        "company_name": extract_rich_text(entry, "Company Name"),
        "email": extract_email(entry, "Email"),
        "email_verified": extract_checkbox(entry, "Email Verified"),
        "linkedin_url": extract_url(entry, "LinkedIn URL"),
        "location": extract_rich_text(entry, "Location"),
        "company_fit_score": extract_number(entry, "Company Fit Score") or 0,
        "relevance_score": extract_number(entry, "Relevance Score") or 0,
        "score_reasoning": extract_rich_text(entry, "Score Reasoning"),
        "personalized_context": extract_rich_text(entry, "Personalized Context"),
        "context": extract_rich_text(entry, "Context"),
        "email_subject": extract_rich_text(entry, "Email Subject"),
        "outreach_status": extract_select(entry, "Outreach Status"),
        "website": "",
        "email_content": "",
    }


def _fields_to_properties(f: dict) -> dict:
    """Convert extracted fields into Notion page properties."""
    company = f["company_name"] or "Unknown"
    props: dict = {"Company": title_prop(company)}
    if f["website"]:
        props["Website"] = url_prop(f["website"])
    if f["location"]:
        props["Location"] = rich_text_prop(f["location"])
    name = f["name"].split(" - ")[0] if " - " in f["name"] else f["name"]
    if name:
        props["Name"] = rich_text_prop(name)
    if f["job_title"]:
        props["Job Title"] = rich_text_prop(f["job_title"])
    if f["linkedin_url"]:
        props["LinkedIn URL"] = url_prop(f["linkedin_url"])
    if f["email"]:
        props["Email"] = email_prop(f["email"])
    if f["email_verified"]:
        props["Email Verified"] = checkbox_prop(True)
    if f["email_subject"]:
        props["Email Subject"] = rich_text_prop(f["email_subject"])
    if f["email_content"]:
        props["Email Content"] = rich_text_prop(f["email_content"][:2000])
    if f["outreach_status"]:
        props["Outreach Status"] = select_prop(f["outreach_status"])
    if f["company_fit_score"]:
        props["Company Fit Score"] = number_prop(f["company_fit_score"])
    if f["relevance_score"]:
        props["Relevance Score"] = number_prop(f["relevance_score"])
    if f["score_reasoning"]:
        props["Score Reasoning"] = rich_text_prop(f["score_reasoning"])
    if f["context"]:
        props["Context"] = rich_text_prop(f["context"])
    if f["personalized_context"]:
        props["Personalized Context"] = rich_text_prop(f["personalized_context"])
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
                 emails_db: EmailsDB,
                 leads_page_id: str) -> None:
        self._client = client
        self._cc_db = contact_campaigns_db
        self._emails_db = emails_db
        self._leads_page_id = leads_page_id
        self._campaign_pages: dict[str, str] = {}
        self._campaign_dbs: dict[str, str] = {}

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
        """Find or create the inline leads database.

        Reuses existing databases to preserve manual column reordering.
        When creating a new database, adds properties one at a time via
        sequential PATCH calls so Notion respects the column order.
        """
        if page_id in self._campaign_dbs:
            return self._campaign_dbs[page_id]

        # No existing DB found -- clean up stale blocks
        blocks = await self._client.get_page_body(page_id)
        if blocks:
            sem = asyncio.Semaphore(_CONCURRENCY)
            async def _del(bid: str) -> None:
                async with sem:
                    await self._client._call(
                        self._client._sdk.blocks.delete, block_id=bid)
            await asyncio.gather(*[_del(b["id"]) for b in blocks])

        # Create DB with title property only
        result = await self._client.create_database(
            parent_page_id=page_id,
            title="High Priority Leads",
            properties={"Company": {"title": {}}},
        )
        db_id = result["id"]

        # Add remaining properties one by one in the desired column order
        for prop_name, prop_config in _LEADS_DB_SCHEMA.items():
            if prop_name == "Company":
                continue
            await self._client.update_database(
                db_id, {prop_name: prop_config},
            )

        self._campaign_dbs[page_id] = db_id
        logger.info("Created leads DB on page %s -> %s (sequential)", page_id[:8], db_id[:8])
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

    async def _fetch_company_websites(self, entries: list[dict]) -> dict[str, str]:
        """Batch-fetch website URLs for companies referenced in entries."""
        company_ids: set[str] = set()
        for entry in entries:
            cids = extract_relation_ids(entry, "Company")
            if cids:
                company_ids.add(cids[0])
        if not company_ids:
            return {}
        websites: dict[str, str] = {}
        sem = asyncio.Semaphore(_CONCURRENCY)
        async def _fetch(cid: str) -> None:
            async with sem:
                try:
                    page = await self._client._call(
                        self._client._sdk.pages.retrieve, page_id=cid)
                    websites[cid] = extract_url(page, "Website") or ""
                except Exception:
                    websites[cid] = ""
        await asyncio.gather(*[_fetch(cid) for cid in company_ids])
        return websites

    async def _fetch_email_contents(
        self, campaign_id: str, contact_ids: set[str],
    ) -> dict[str, str]:
        """Batch-fetch email body text for contacts in this campaign."""
        emails = await self._emails_db.get_emails_for_campaign(campaign_id)
        contact_email: dict[str, str] = {}
        for email_page in emails:
            cids = extract_relation_ids(email_page, "Contact")
            if cids and cids[0] in contact_ids:
                contact_email[cids[0]] = email_page["id"]
        if not contact_email:
            return {}
        contents: dict[str, str] = {}
        sem = asyncio.Semaphore(_CONCURRENCY)
        async def _fetch(contact_id: str, email_page_id: str) -> None:
            async with sem:
                try:
                    blocks = await self._client.get_page_body(email_page_id)
                    contents[contact_id] = _blocks_to_text(blocks)
                except Exception:
                    contents[contact_id] = ""
        await asyncio.gather(*[
            _fetch(cid, eid) for cid, eid in contact_email.items()
        ])
        return contents

    async def update_campaign_page(self, campaign_id: str, campaign_name: str,
                                   target_desc: str = "") -> None:
        """Sync the inline leads database with current high-priority entries."""
        page_id = await self.ensure_campaign_page(campaign_id, campaign_name)
        entries = await self._cc_db.get_high_priority(campaign_id, min_score=_MIN_SCORE)
        entries.sort(
            key=lambda e: extract_number(e, "Relevance Score") or 0, reverse=True)

        # Batch-fetch enrichment data (company websites + email bodies)
        company_websites = await self._fetch_company_websites(entries)
        contact_ids: set[str] = set()
        entry_contact: dict[str, str] = {}
        for entry in entries:
            cids = extract_relation_ids(entry, "Contact")
            if cids:
                contact_ids.add(cids[0])
                entry_contact[entry["id"]] = cids[0]
        email_contents = await self._fetch_email_contents(campaign_id, contact_ids)

        # Extract and enrich fields
        fields_list: list[dict] = []
        for entry in entries:
            f = _extract_fields(entry)
            comp_ids = extract_relation_ids(entry, "Company")
            if comp_ids:
                f["website"] = company_websites.get(comp_ids[0], "")
            cid = entry_contact.get(entry["id"], "")
            if cid:
                f["email_content"] = email_contents.get(cid, "")
            fields_list.append(f)

        db_id = await self._ensure_leads_db(page_id)
        archived = await self._archive_db_entries(db_id)
        await self._populate_db(db_id, fields_list)
        logger.info("Leads DB '%s': archived=%d added=%d",
                     campaign_name, archived, len(fields_list))

    async def update_parent_index(self, campaigns: list[dict]) -> None:
        """Update parent page with links to campaign leads databases."""
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
    emails_db: EmailsDB,
    leads_page_id: str,
) -> None:
    """Refresh all campaign leads databases. Call periodically."""
    manager = LeadsPagesManager(client, contact_campaigns_db, emails_db, leads_page_id)
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

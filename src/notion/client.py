"""
Base Notion API client with rate-limited CRUD operations.

All requests go through the shared RateLimiter at 2.5 req/sec.
Uses the official notion-client Python SDK.
"""

import asyncio
import logging
from functools import partial
from typing import Any

from notion_client import Client as NotionSDKClient

from src.config import get_config
from src.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

_RATE_LIMIT_KEY = "notion"


class NotionClient:
    """
    Thin async wrapper around the notion-client SDK.

    Every API call acquires a rate-limiter slot before executing.
    The SDK itself is synchronous, so calls are dispatched to the
    default executor via asyncio.to_thread.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        """
        Initialise the Notion client.

        Args:
            rate_limiter: Shared RateLimiter instance. If None, a new one
                          is created with default limits.
        """
        cfg = get_config()
        self._sdk = NotionSDKClient(
            auth=cfg.notion_api_key,
            notion_version="2022-06-28",
        )
        self._limiter = rate_limiter or RateLimiter()

    async def _call(self, func: Any, **kwargs: Any) -> Any:
        """
        Acquire a rate-limiter slot, then run a synchronous SDK call
        in a thread executor.

        Args:
            func: A bound method on the SDK (e.g. self._sdk.databases.query).
            **kwargs: Arguments forwarded to the SDK method.

        Returns:
            The SDK response dict.

        Raises:
            Exception: Any error from the Notion API is propagated.
        """
        await self._limiter.acquire(_RATE_LIMIT_KEY)
        bound = partial(func, **kwargs)
        return await asyncio.to_thread(bound)

    async def query_database(
        self,
        database_id: str,
        filter_obj: dict | None = None,
        sorts: list | None = None,
        page_size: int = 100,
    ) -> list[dict]:
        """
        Query a Notion database and return all matching pages.

        Handles pagination automatically, fetching all results.
        Uses raw HTTP because the notion-client SDK removed
        databases.query in recent versions.

        Args:
            database_id: The Notion database UUID.
            filter_obj: Optional Notion filter object.
            sorts: Optional list of sort objects.
            page_size: Number of results per page (max 100).

        Returns:
            List of page objects matching the query.
        """
        import httpx as _httpx

        cfg = get_config()
        headers = {
            "Authorization": f"Bearer {cfg.notion_api_key}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }

        all_results: list[dict] = []
        has_more = True
        start_cursor = None

        while has_more:
            await self._limiter.acquire(_RATE_LIMIT_KEY)
            body: dict[str, Any] = {"page_size": page_size}
            if filter_obj:
                body["filter"] = filter_obj
            if sorts:
                body["sorts"] = sorts
            if start_cursor:
                body["start_cursor"] = start_cursor

            resp = await asyncio.to_thread(
                _httpx.post,
                f"https://api.notion.com/v1/databases/{database_id}/query",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            response = resp.json()
            all_results.extend(response.get("results", []))
            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")

        logger.debug(
            "query_database: %s returned %d pages", database_id, len(all_results)
        )
        return all_results

    async def create_page(
        self,
        database_id: str,
        properties: dict,
        body_blocks: list[dict] | None = None,
    ) -> dict:
        """
        Create a new page in a Notion database.

        Args:
            database_id: The Notion database UUID to create the page in.
            properties: Property values for the new page.
            body_blocks: Optional list of block objects for the page body.

        Returns:
            The created page object.
        """
        kwargs: dict[str, Any] = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }
        if body_blocks:
            kwargs["children"] = body_blocks

        result = await self._call(self._sdk.pages.create, **kwargs)
        logger.debug("create_page: created %s in %s", result["id"], database_id)
        return result

    async def update_page(self, page_id: str, properties: dict) -> dict:
        """
        Update properties on an existing Notion page.

        Args:
            page_id: The Notion page UUID to update.
            properties: Property values to set (partial update).

        Returns:
            The updated page object.
        """
        result = await self._call(
            self._sdk.pages.update, page_id=page_id, properties=properties
        )
        logger.debug("update_page: updated %s", page_id)
        return result

    async def append_page_body(self, page_id: str, blocks: list[dict]) -> None:
        """
        Append block children to an existing Notion page.

        Args:
            page_id: The Notion page UUID to append blocks to.
            blocks: List of block objects to append.
        """
        await self._call(
            self._sdk.blocks.children.append,
            block_id=page_id,
            children=blocks,
        )
        logger.debug("append_page_body: appended %d blocks to %s", len(blocks), page_id)

    async def get_page_body(self, page_id: str) -> list[dict]:
        """
        Retrieve all block children from a Notion page.

        Handles pagination automatically.

        Args:
            page_id: The Notion page UUID to read blocks from.

        Returns:
            List of block objects in the page body.
        """
        all_blocks: list[dict] = []
        has_more = True
        start_cursor = None

        while has_more:
            kwargs: dict[str, Any] = {"block_id": page_id}
            if start_cursor:
                kwargs["start_cursor"] = start_cursor

            response = await self._call(
                self._sdk.blocks.children.list, **kwargs
            )
            all_blocks.extend(response.get("results", []))
            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")

        logger.debug("get_page_body: %s has %d blocks", page_id, len(all_blocks))
        return all_blocks

    async def create_database(
        self,
        parent_page_id: str,
        title: str,
        properties: dict,
    ) -> dict:
        """
        Create a new database as a child of a Notion page.

        Uses raw HTTP because the notion-client SDK does not forward
        the properties parameter correctly to the Notion API.

        Args:
            parent_page_id: The page UUID to create the database under.
            title: Human-readable title for the database.
            properties: Property schema definitions for the database.

        Returns:
            The created database object (includes the new database ID).
        """
        import httpx as _httpx

        await self._limiter.acquire(_RATE_LIMIT_KEY)
        cfg = get_config()
        headers = {
            "Authorization": f"Bearer {cfg.notion_api_key}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        body = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": properties,
        }
        resp = await asyncio.to_thread(
            _httpx.post,
            "https://api.notion.com/v1/databases",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info("create_database: created '%s' -> %s", title, result["id"])
        return result

    async def update_database(self, database_id: str, properties: dict) -> dict:
        """
        Update properties on an existing Notion database schema.

        Args:
            database_id: The Notion database UUID.
            properties: Property schema updates.

        Returns:
            The updated database object.
        """
        result = await self._call(
            self._sdk.databases.update,
            database_id=database_id,
            properties=properties,
        )
        logger.debug("update_database: updated schema for %s", database_id)
        return result

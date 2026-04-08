"""Contact discovery via Google search.

Finds people at companies by searching Google for LinkedIn profiles
and leadership pages, then extracts names and titles from results.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)

DEFAULT_TARGET_TITLES = [
    "CEO",
    "Founder",
    "Head of Sustainability",
    "Head of Operations",
    "COO",
    "Head of Product",
    "Supply Chain Manager",
]

_LEADERSHIP_TERMS = [
    "head of",
    "director",
    "founder",
    "co-founder",
    "chief",
    "ceo",
    "coo",
    "cto",
    "vp",
    "president",
    "manager",
]


@dataclass
class RawContact:
    """A person discovered via search results."""

    name: str
    title: str | None
    source_url: str
    linkedin_url: str | None


class SearchClient(Protocol):
    """Protocol that any Google search client must satisfy."""

    async def search(self, query: str, num_results: int = 10) -> list[dict]:
        """Execute a search query and return result dicts.

        Each dict should have at minimum 'title', 'link', and 'snippet' keys.
        """
        ...


class ContactFinder:
    """Finds contacts at a company using Google search."""

    def __init__(self, search_client: SearchClient) -> None:
        """Initialize with a search client instance.

        Args:
            search_client: Any object implementing the SearchClient protocol
                with an async search() method.
        """
        self._search = search_client

    async def find_contacts(
        self,
        company_name: str,
        domain: str,
        target_titles: list[str] | None = None,
    ) -> list[RawContact]:
        """Search Google for people at a company.

        Args:
            company_name: The company name to search for.
            domain: The company domain (used for context, not filtering).
            target_titles: Job titles to search for. Uses DEFAULT_TARGET_TITLES
                if not provided.

        Returns:
            Deduplicated list of RawContact objects found in search results.
        """
        if target_titles is None:
            target_titles = DEFAULT_TARGET_TITLES

        contacts: list[RawContact] = []

        # Strategy 1: LinkedIn profile searches for each target title
        for title in target_titles:
            query = f'site:linkedin.com/in "{company_name}" "{title}"'
            results = await self._run_search(query)
            parsed = self._parse_linkedin_results(results, title)
            contacts.extend(parsed)

        # Strategy 2: General leadership search
        leadership_query = (
            f'"{company_name}" '
            f'"head of" OR "director" OR "founder" OR "CEO" OR "COO"'
        )
        results = await self._run_search(leadership_query)
        parsed = self._parse_general_results(results, company_name)
        contacts.extend(parsed)

        deduped = self._deduplicate(contacts)
        logger.info(
            "Found %d unique contacts for %s", len(deduped), company_name
        )
        return deduped

    async def _run_search(self, query: str) -> list[dict]:
        """Execute a search query with error handling.

        Args:
            query: The search query string.

        Returns:
            List of result dicts, or empty list on error.
        """
        try:
            return await self._search.search(query, num_results=10)
        except Exception:
            logger.warning("Search failed for query: %s", query, exc_info=True)
            return []

    def _parse_linkedin_results(
        self, results: list[dict], target_title: str
    ) -> list[RawContact]:
        """Extract contacts from LinkedIn search results.

        Args:
            results: Search result dicts with 'title', 'link', 'snippet'.
            target_title: The title that was searched for.

        Returns:
            List of RawContact objects parsed from the results.
        """
        contacts = []
        for result in results:
            link = getattr(result, "url", "") or (result.get("link", "") if isinstance(result, dict) else "")
            title_text = getattr(result, "title", "") or (result.get("title", "") if isinstance(result, dict) else "")
            snippet = getattr(result, "snippet", "") or (result.get("snippet", "") if isinstance(result, dict) else "")

            if "linkedin.com/in/" not in link:
                continue

            name = self._extract_name_from_linkedin_title(title_text)
            if not name:
                continue

            extracted_title = self._extract_title(
                snippet, title_text, target_title
            )

            contacts.append(
                RawContact(
                    name=name,
                    title=extracted_title,
                    source_url=link,
                    linkedin_url=link,
                )
            )
        return contacts

    def _parse_general_results(
        self, results: list[dict], company_name: str
    ) -> list[RawContact]:
        """Extract contacts from general (non-LinkedIn) search results.

        Args:
            results: Search result dicts with 'title', 'link', 'snippet'.
            company_name: The company being searched.

        Returns:
            List of RawContact objects parsed from the results.
        """
        contacts = []
        for result in results:
            link = getattr(result, "url", "") or (result.get("link", "") if isinstance(result, dict) else "")
            title_text = getattr(result, "title", "") or (result.get("title", "") if isinstance(result, dict) else "")
            snippet = getattr(result, "snippet", "") or (result.get("snippet", "") if isinstance(result, dict) else "")

            is_linkedin = "linkedin.com/in/" in link
            combined_text = f"{title_text} {snippet}"

            # Look for name-title patterns in the text
            extracted = self._extract_name_and_title_from_text(
                combined_text, company_name
            )
            for name, title in extracted:
                contacts.append(
                    RawContact(
                        name=name,
                        title=title,
                        source_url=link,
                        linkedin_url=link if is_linkedin else None,
                    )
                )
        return contacts

    def _extract_name_from_linkedin_title(self, title: str) -> str | None:
        """Extract a person's name from a LinkedIn page title.

        LinkedIn titles typically follow the pattern:
        'First Last - Title - Company | LinkedIn'

        Args:
            title: The page title string.

        Returns:
            The extracted name, or None if not parseable.
        """
        # Strip common LinkedIn suffixes
        cleaned = re.sub(
            r"\s*[\|\-]\s*LinkedIn.*$", "", title, flags=re.IGNORECASE
        )

        # Take the first segment before a dash or pipe
        parts = re.split(r"\s*[\|\-]\s*", cleaned)
        if not parts:
            return None

        name_candidate = parts[0].strip()

        # Basic validation: at least 2 characters, contains a space
        # (first + last name), no digits
        if (
            len(name_candidate) < 2
            or not re.search(r"[a-zA-Z]", name_candidate)
            or re.search(r"\d", name_candidate)
        ):
            return None

        return name_candidate

    def _extract_title(
        self, snippet: str, page_title: str, fallback_title: str
    ) -> str:
        """Extract job title from search result text.

        Args:
            snippet: The search result snippet.
            page_title: The search result page title.
            fallback_title: The title that was searched for, used as fallback.

        Returns:
            The best title found, or the fallback.
        """
        combined = f"{page_title} {snippet}".lower()
        for term in _LEADERSHIP_TERMS:
            if term in combined:
                # Try to extract the full title phrase
                pattern = rf"({term}\s+(?:of\s+)?\w+(?:\s+\w+)?)"
                match = re.search(pattern, combined, re.IGNORECASE)
                if match:
                    return match.group(1).strip().title()
        return fallback_title

    def _extract_name_and_title_from_text(
        self, text: str, company_name: str
    ) -> list[tuple[str, str]]:
        """Extract name-title pairs from unstructured text.

        Looks for patterns like 'Name, Title at Company' or
        'Name - Title - Company'.

        Args:
            text: The text to parse.
            company_name: The company name for context matching.

        Returns:
            List of (name, title) tuples found in the text.
        """
        results = []
        company_lower = company_name.lower()

        # Pattern: "Name, Title at/of Company"
        pattern = (
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"
            r",?\s+"
            r"((?:CEO|COO|CTO|CFO|Founder|Co-Founder|Director|"
            r"Head of \w+|VP of \w+|President|Manager)"
            r"(?:\s+(?:of|at)\s+\w+)*)"
        )
        for match in re.finditer(pattern, text):
            name = match.group(1).strip()
            title = match.group(2).strip()
            context_after = text[match.end() : match.end() + 100].lower()
            if company_lower in context_after or company_lower in text.lower():
                results.append((name, title))

        return results

    def _deduplicate(self, contacts: list[RawContact]) -> list[RawContact]:
        """Remove duplicate contacts by normalized name.

        Keeps the first occurrence of each name (which tends to come from
        the more specific LinkedIn search).

        Args:
            contacts: List of contacts to deduplicate.

        Returns:
            Deduplicated list preserving original order.
        """
        seen: set[str] = set()
        unique: list[RawContact] = []
        for contact in contacts:
            key = contact.name.lower().strip()
            if key not in seen:
                seen.add(key)
                unique.append(contact)
        return unique

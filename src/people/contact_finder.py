"""Contact discovery via Google search.

Finds people at companies by searching Google for LinkedIn profiles
and company team pages, then extracts names and titles from results.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


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
        self._search = search_client

    async def find_contacts(
        self,
        company_name: str,
        domain: str,
    ) -> list[RawContact]:
        """Search for people at a company using broad queries.

        Returns deduplicated list of RawContact objects.
        """
        contacts: list[RawContact] = []

        # Strategy 1: Company team/people page search
        if domain:
            team_query = (
                f'"{company_name}" team OR people OR about OR staff '
                f"site:{domain}"
            )
            results = await self._run_search(team_query)
            parsed = self._parse_general_results(results, company_name)
            contacts.extend(parsed)

        # Strategy 2: Broad LinkedIn company search
        linkedin_query = f'site:linkedin.com/in "{company_name}"'
        results = await self._run_search(linkedin_query)
        parsed = self._parse_linkedin_results(results)
        contacts.extend(parsed)

        # Strategy 3: LinkedIn department search (relevant functions)
        dept_query = (
            f'site:linkedin.com/in "{company_name}" '
            f"sustainability OR product OR operations OR supply chain"
        )
        results = await self._run_search(dept_query)
        parsed = self._parse_linkedin_results(results)
        contacts.extend(parsed)

        deduped = self._deduplicate(contacts)
        logger.info(
            "Found %d unique contacts for %s", len(deduped), company_name
        )
        return deduped

    async def _run_search(self, query: str) -> list[dict]:
        """Execute a search query, returning empty list on error."""
        try:
            return await self._search.search(query, num_results=10)
        except Exception:
            logger.warning("Search failed for query: %s", query, exc_info=True)
            return []

    def _parse_linkedin_results(
        self, results: list[dict]
    ) -> list[RawContact]:
        """Extract contacts from LinkedIn search results."""
        contacts = []
        for result in results:
            link = self._get_field(result, "link", "url")
            title_text = self._get_field(result, "title")
            snippet = self._get_field(result, "snippet")

            if "linkedin.com/in/" not in link:
                continue

            name = self._extract_name_from_linkedin_title(title_text)
            if not name:
                continue

            extracted_title = self._extract_title(snippet, title_text)

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
        """Extract contacts from general (non-LinkedIn) search results."""
        contacts = []
        for result in results:
            link = self._get_field(result, "link", "url")
            title_text = self._get_field(result, "title")
            snippet = self._get_field(result, "snippet")

            is_linkedin = "linkedin.com/in/" in link
            combined_text = f"{title_text} {snippet}"

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

    @staticmethod
    def _get_field(result: dict, *keys: str) -> str:
        """Extract a field from a result that may be a dict or object.

        Tries attribute access first, then dict access, for each key.
        """
        for key in keys:
            val = getattr(result, key, None)
            if val:
                return val
            if isinstance(result, dict):
                val = result.get(key, "")
                if val:
                    return val
        return ""

    def _extract_name_from_linkedin_title(self, title: str) -> str | None:
        """Extract name from LinkedIn title ('First Last - Title | LinkedIn')."""
        cleaned = re.sub(
            r"\s*[\|\-]\s*LinkedIn.*$", "", title, flags=re.IGNORECASE
        )

        parts = re.split(r"\s*[\|\-]\s*", cleaned)
        if not parts:
            return None

        name_candidate = parts[0].strip()

        if (
            len(name_candidate) < 2
            or not re.search(r"[a-zA-Z]", name_candidate)
            or re.search(r"\d", name_candidate)
        ):
            return None

        return name_candidate

    def _extract_title(self, snippet: str, page_title: str) -> str | None:
        """Extract job title from result text. Accepts any role, not just leadership."""
        # LinkedIn page titles: "Name - Title at Company | LinkedIn"
        # Split on " | " first, then " - " (with spaces to preserve Co-Founder etc.)
        before_pipe = page_title.split(" | ")[0] if " | " in page_title else page_title
        dash_parts = before_pipe.split(" - ")
        if len(dash_parts) >= 2:
            candidate = dash_parts[1].strip()
            if candidate and not candidate.lower().startswith("linkedin"):
                # Strip "at/@ CompanyName" suffix but keep "of" (part of titles)
                cleaned = re.sub(
                    r"\s+(?:at|@)\s+.*$", "", candidate, flags=re.IGNORECASE
                ).strip()
                # Reject location-like strings ("City, State, Country")
                if re.match(r"^[A-Z][a-z]+,\s+[A-Z]", cleaned):
                    return None
                if cleaned and len(cleaned) >= 3:
                    return cleaned

        # Try common "Title at Company" patterns in snippet
        match = re.search(
            r"(?:^|\.\s+|,\s+)"
            r"([A-Z][A-Za-z /&]+(?:at|for|,)\s+\w+)",
            snippet,
        )
        if match:
            title = match.group(1).strip()
            # Strip "at CompanyName" from snippet matches too
            title = re.sub(
                r"\s+(?:at|@)\s+.*$", "", title, flags=re.IGNORECASE
            ).strip()
            if title and len(title) >= 3:
                return title

        return None

    def _extract_name_and_title_from_text(
        self, text: str, company_name: str
    ) -> list[tuple[str, str]]:
        """Extract name-title pairs from unstructured text (broad matching)."""
        results = []
        company_lower = company_name.lower()

        # Pattern: "Name, Title at/of Company" -- broad title matching
        pattern = (
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"
            r",?\s+"
            r"([A-Z][A-Za-z /&-]+(?:\s+(?:of|at|for)\s+\w+)*)"
        )
        for match in re.finditer(pattern, text):
            name = match.group(1).strip()
            title = match.group(2).strip()
            # Filter out noise: title must be at least 3 chars and
            # the company must appear somewhere in the text
            if len(title) < 3:
                continue
            context_after = text[match.end() : match.end() + 100].lower()
            if company_lower in context_after or company_lower in text.lower():
                results.append((name, title))

        return results

    def _deduplicate(self, contacts: list[RawContact]) -> list[RawContact]:
        """Remove duplicate contacts by normalized name, keeping first seen."""
        seen: set[str] = set()
        unique: list[RawContact] = []
        for contact in contacts:
            key = contact.name.lower().strip()
            if key not in seen:
                seen.add(key)
                unique.append(contact)
        return unique

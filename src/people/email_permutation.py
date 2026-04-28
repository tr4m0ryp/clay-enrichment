"""Email address permutation generator.

Generates common email format candidates from a person's name and
their company domain. Handles edge cases like hyphenated names,
accented characters, and single names.
"""

from __future__ import annotations

import re
import unicodedata


class EmailPermutator:
    """Generates email address candidates from name + domain."""

    def generate(
        self, first_name: str, last_name: str, domain: str
    ) -> list[str]:
        """Generate common email format permutations.

        Produces email candidates ordered by real-world frequency.
        Handles hyphenated names (keeps hyphen), accented characters
        (normalized to ASCII), and single-name cases.

        Args:
            first_name: Person's first name (required, non-empty).
            last_name: Person's last name (may be empty for single names).
            domain: Company email domain (e.g. "company.com").

        Returns:
            List of email address strings, ordered by likelihood.
        """
        first = self._normalize(first_name)
        last = self._normalize(last_name) if last_name else ""
        domain = domain.strip().lower()

        if not first or not domain:
            return []

        if not last:
            return self._single_name_permutations(first, domain)

        return self._full_name_permutations(first, last, domain)

    def _full_name_permutations(
        self, first: str, last: str, domain: str
    ) -> list[str]:
        """Generate permutations when both first and last name exist.

        Args:
            first: Normalized first name.
            last: Normalized last name.
            domain: Email domain.

        Returns:
            Ordered list of email candidates.
        """
        first_initial = first[0]
        last_initial = last[0]

        permutations = [
            f"{first}.{last}@{domain}",
            f"{first}@{domain}",
            f"{first_initial}{last}@{domain}",
            f"{first}{last_initial}@{domain}",
            f"{first}_{last}@{domain}",
            f"{last}.{first}@{domain}",
            f"{last}@{domain}",
            f"{first_initial}.{last}@{domain}",
        ]

        return permutations

    def _single_name_permutations(
        self, name: str, domain: str
    ) -> list[str]:
        """Generate permutations for a single name (no last name).

        Args:
            name: Normalized single name.
            domain: Email domain.

        Returns:
            List with the single plausible email candidate.
        """
        return [f"{name}@{domain}"]

    def _normalize(self, name: str) -> str:
        """Normalize a name for use in email addresses.

        Converts to lowercase, strips accented characters to ASCII
        equivalents, removes characters that are invalid in email
        local parts (except hyphens), and collapses whitespace.

        Args:
            name: Raw name string.

        Returns:
            Cleaned, lowercase ASCII name suitable for email use.
        """
        if not name:
            return ""

        name = name.strip().lower()

        # Decompose unicode and drop combining marks (accents)
        nfkd = unicodedata.normalize("NFKD", name)
        ascii_name = "".join(
            char for char in nfkd if not unicodedata.combining(char)
        )

        # Keep only letters, hyphens, and spaces
        ascii_name = re.sub(r"[^a-z\s\-]", "", ascii_name)

        # Collapse whitespace and strip
        ascii_name = re.sub(r"\s+", "", ascii_name).strip()

        return ascii_name

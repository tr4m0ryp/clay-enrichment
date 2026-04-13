"""Title relevance filter for contact research gating."""

# Target seniority levels (prefix matching, lowercase)
SENIORITY_PREFIXES = [
    "ceo", "cto", "cfo", "coo", "cmo", "cro", "cbo", "cpo", "cso", "cdo",
    "chief", "president", "founder", "co-founder", "cofounder",
    "managing director", "general manager",
    "vp", "svp", "evp", "vice president",
    "director", "head of", "global head",
    "manager", "senior manager",
]

# Target departments (keyword matching)
RELEVANT_DEPARTMENTS = [
    "sustainability", "product", "supply chain", "operations",
    "digital", "technology", "innovation", "compliance",
    "ecommerce", "e-commerce", "sourcing", "procurement",
    "brand", "marketing", "design", "merchandising",
    "retail", "commercial", "sales", "business development",
]


def _has_seniority(t: str) -> bool:
    """Return True if the lowercased title starts with a seniority prefix."""
    for prefix in SENIORITY_PREFIXES:
        if t.startswith(prefix):
            return True
    return False


def _has_department(t: str) -> bool:
    """Return True if the lowercased title contains a relevant department keyword."""
    for dept in RELEVANT_DEPARTMENTS:
        if dept in t:
            return True
    return False


def is_relevant_title(title: str) -> bool:
    """Return True if the title indicates a relevant decision-maker.

    Requires a seniority-level prefix. Department keywords alone are
    not sufficient (e.g. "Sales Associate" is filtered out).
    """
    if not title or not title.strip():
        return False
    t = title.lower().strip()
    if not _has_seniority(t):
        return False
    return True

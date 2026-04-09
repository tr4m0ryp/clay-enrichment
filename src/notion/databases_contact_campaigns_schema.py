"""
Schema definition and constants for the Contact-Campaign junction database.

Imported by databases_contact_campaigns.py and by setup.py.
"""

from __future__ import annotations

OUTREACH_STATUSES = (
    "New",
    "Email Pending Review",
    "Email Approved",
    "Sent",
    "Replied",
    "Meeting Booked",
)

INDUSTRY_OPTIONS = ("Fashion", "Streetwear", "Lifestyle", "Other")


def contact_campaigns_schema(
    contacts_db_id: str,
    campaigns_db_id: str,
    companies_db_id: str,
) -> dict:
    """
    Return the Notion database property schema for the Contact-Campaign junction table.

    Intended for use by setup.py when creating the database via the API.

    Args:
        contacts_db_id: The Notion database UUID for Contacts.
        campaigns_db_id: The Notion database UUID for Campaigns.
        companies_db_id: The Notion database UUID for Companies.

    Returns:
        Property schema dict compatible with the Notion databases.create API.
    """
    return {
        "Name": {"title": {}},
        "Contact": {
            "relation": {
                "database_id": contacts_db_id,
                "single_property": {},
            }
        },
        "Campaign": {
            "relation": {
                "database_id": campaigns_db_id,
                "single_property": {},
            }
        },
        "Company": {
            "relation": {
                "database_id": companies_db_id,
                "single_property": {},
            }
        },
        "Job Title": {"rich_text": {}},
        "Company Name": {"rich_text": {}},
        "Email": {"email": {}},
        "Email Verified": {"checkbox": {}},
        "LinkedIn URL": {"url": {}},
        "Industry": {
            "select": {
                "options": [{"name": opt} for opt in INDUSTRY_OPTIONS]
            }
        },
        "Location": {"rich_text": {}},
        "Company Fit Score": {"number": {"format": "number"}},
        "Relevance Score": {"number": {"format": "number"}},
        "Score Reasoning": {"rich_text": {}},
        "Personalized Context": {"rich_text": {}},
        "Email Subject": {"rich_text": {}},
        "Outreach Status": {
            "select": {
                "options": [{"name": s} for s in OUTREACH_STATUSES]
            }
        },
        "Last Updated": {"date": {}},
    }

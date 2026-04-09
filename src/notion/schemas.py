"""
Notion database property schema definitions.

Imported by setup.py for database creation. Each function returns a
dict compatible with the Notion databases.create API.
"""

from __future__ import annotations


def campaigns_schema() -> dict:
    """
    Return the property schema for the Campaigns database.

    Returns:
        Dict of property name to Notion property schema definition.
    """
    return {
        "Name": {"title": {}},
        "Target Description": {"rich_text": {}},
        "Status": {
            "select": {
                "options": [
                    {"name": "Active", "color": "green"},
                    {"name": "Paused", "color": "yellow"},
                    {"name": "Completed", "color": "gray"},
                ]
            }
        },
        "Created At": {"date": {}},
    }


def companies_schema(campaigns_db_id: str) -> dict:
    """
    Return the property schema for the Companies database.

    Args:
        campaigns_db_id: The Campaigns database ID for the relation.

    Returns:
        Dict of property name to Notion property schema definition.
    """
    return {
        "Name": {"title": {}},
        "Website": {"url": {}},
        "Industry": {
            "select": {
                "options": [
                    {"name": "Fashion", "color": "pink"},
                    {"name": "Streetwear", "color": "purple"},
                    {"name": "Lifestyle", "color": "blue"},
                    {"name": "Other", "color": "gray"},
                ]
            }
        },
        "Location": {"rich_text": {}},
        "Size": {"rich_text": {}},
        "DPP Fit Score": {"number": {"format": "number"}},
        "Status": {
            "select": {
                "options": [
                    {"name": "Discovered", "color": "gray"},
                    {"name": "Enriched", "color": "green"},
                    {"name": "Partially Enriched", "color": "yellow"},
                    {"name": "Contacts Found", "color": "blue"},
                ]
            }
        },
        "Campaign": {
            "relation": {
                "database_id": campaigns_db_id,
                "single_property": {},
            }
        },
        "Source Query": {"rich_text": {}},
        "Last Enriched": {"date": {}},
    }


def contacts_schema(companies_db_id: str, campaigns_db_id: str) -> dict:
    """
    Return the property schema for the Contacts database.

    Args:
        companies_db_id: The Companies database ID for the relation.
        campaigns_db_id: The Campaigns database ID for the relation.

    Returns:
        Dict of property name to Notion property schema definition.
    """
    return {
        "Name": {"title": {}},
        "Job Title": {"rich_text": {}},
        "Email": {"email": {}},
        "Email Verified": {"checkbox": {}},
        "LinkedIn URL": {"url": {}},
        "Company": {
            "relation": {
                "database_id": companies_db_id,
                "single_property": {},
            }
        },
        "Status": {
            "select": {
                "options": [
                    {"name": "Found", "color": "gray"},
                    {"name": "Enriched", "color": "green"},
                    {"name": "Email Generated", "color": "blue"},
                ]
            }
        },
        "Context": {"rich_text": {}},
        "Campaign": {
            "relation": {
                "database_id": campaigns_db_id,
                "single_property": {},
            }
        },
    }


def emails_schema(contacts_db_id: str, campaigns_db_id: str) -> dict:
    """
    Return the property schema for the Emails database.

    Args:
        contacts_db_id: The Contacts database ID for the relation.
        campaigns_db_id: The Campaigns database ID for the relation.

    Returns:
        Dict of property name to Notion property schema definition.
    """
    return {
        "Subject": {"title": {}},
        "Contact": {
            "relation": {
                "database_id": contacts_db_id,
                "single_property": {},
            }
        },
        "Status": {
            "select": {
                "options": [
                    {"name": "Pending Review", "color": "yellow"},
                    {"name": "Approved", "color": "green"},
                    {"name": "Sent", "color": "blue"},
                    {"name": "Rejected", "color": "red"},
                    {"name": "Failed", "color": "gray"},
                ]
            }
        },
        "Sender Address": {"rich_text": {}},
        "Sent At": {"date": {}},
        "Campaign": {
            "relation": {
                "database_id": campaigns_db_id,
                "single_property": {},
            }
        },
        "Bounce": {"checkbox": {}},
    }

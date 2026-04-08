"""
Typed Notion database operations for all four databases.

Re-exports the per-database classes for convenient access:
    from src.notion.databases import CampaignsDB, CompaniesDB, ContactsDB, EmailsDB
"""

from src.notion.databases_campaigns import CampaignsDB
from src.notion.databases_companies import CompaniesDB
from src.notion.databases_contacts import ContactsDB
from src.notion.databases_emails import EmailsDB

__all__ = ["CampaignsDB", "CompaniesDB", "ContactsDB", "EmailsDB"]

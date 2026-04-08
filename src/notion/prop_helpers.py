"""
Shared property builder and extraction helpers for Notion database operations.

These functions construct and parse Notion API property value dicts,
keeping the per-database modules DRY.
"""

from datetime import datetime, timezone
from typing import Any


def title_prop(text: str) -> dict:
    """
    Build a Notion title property value.

    Args:
        text: The title string.

    Returns:
        Notion property dict for a title field.
    """
    return {"title": [{"text": {"content": text[:2000]}}]}


def rich_text_prop(text: str) -> dict:
    """
    Build a Notion rich_text property value, truncated to 2000 chars.

    Args:
        text: The rich text content.

    Returns:
        Notion property dict for a rich_text field.
    """
    return {"rich_text": [{"text": {"content": text[:2000]}}]}


def select_prop(value: str) -> dict:
    """
    Build a Notion select property value.

    Args:
        value: The select option name.

    Returns:
        Notion property dict for a select field.
    """
    return {"select": {"name": value}}


def number_prop(value: float | int) -> dict:
    """
    Build a Notion number property value.

    Args:
        value: The numeric value.

    Returns:
        Notion property dict for a number field.
    """
    return {"number": value}


def url_prop(value: str) -> dict:
    """
    Build a Notion url property value.

    Args:
        value: The URL string.

    Returns:
        Notion property dict for a url field.
    """
    return {"url": value}


def email_prop(value: str) -> dict:
    """
    Build a Notion email property value.

    Args:
        value: The email address.

    Returns:
        Notion property dict for an email field.
    """
    return {"email": value}


def phone_prop(value: str) -> dict:
    """
    Build a Notion phone_number property value.

    Args:
        value: The phone number string.

    Returns:
        Notion property dict for a phone_number field.
    """
    return {"phone_number": value}


def checkbox_prop(value: bool) -> dict:
    """
    Build a Notion checkbox property value.

    Args:
        value: True or False.

    Returns:
        Notion property dict for a checkbox field.
    """
    return {"checkbox": value}


def date_prop(dt: datetime | str | None = None) -> dict:
    """
    Build a Notion date property value.

    Args:
        dt: A datetime object, ISO string, or None for current time.

    Returns:
        Notion property dict for a date field.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    if isinstance(dt, datetime):
        dt = dt.isoformat()
    return {"date": {"start": dt}}


def relation_prop(page_ids: list[str]) -> dict:
    """
    Build a Notion relation property value.

    Args:
        page_ids: List of page UUIDs to relate to.

    Returns:
        Notion property dict for a relation field.
    """
    return {"relation": [{"id": pid} for pid in page_ids]}


def extract_title(page: dict, prop_name: str) -> str:
    """
    Extract the plain text from a title property on a Notion page.

    Args:
        page: A Notion page object.
        prop_name: The property name holding the title.

    Returns:
        The title text, or empty string if not found.
    """
    prop = page.get("properties", {}).get(prop_name, {})
    parts = prop.get("title", [])
    return "".join(p.get("plain_text", "") for p in parts)


def extract_rich_text(page: dict, prop_name: str) -> str:
    """
    Extract the plain text from a rich_text property on a Notion page.

    Args:
        page: A Notion page object.
        prop_name: The property name holding the rich_text.

    Returns:
        The concatenated plain text, or empty string if not found.
    """
    prop = page.get("properties", {}).get(prop_name, {})
    parts = prop.get("rich_text", [])
    return "".join(p.get("plain_text", "") for p in parts)


def extract_select(page: dict, prop_name: str) -> str:
    """
    Extract the selected option name from a select property.

    Args:
        page: A Notion page object.
        prop_name: The property name holding the select.

    Returns:
        The option name, or empty string if not set.
    """
    prop = page.get("properties", {}).get(prop_name, {})
    sel = prop.get("select")
    if sel and isinstance(sel, dict):
        return sel.get("name", "")
    return ""


def extract_number(page: dict, prop_name: str) -> float | None:
    """
    Extract the value from a number property.

    Args:
        page: A Notion page object.
        prop_name: The property name holding the number.

    Returns:
        The numeric value, or None if not set.
    """
    prop = page.get("properties", {}).get(prop_name, {})
    return prop.get("number")


def extract_url(page: dict, prop_name: str) -> str:
    """
    Extract the URL from a url property.

    Args:
        page: A Notion page object.
        prop_name: The property name holding the url.

    Returns:
        The URL string, or empty string if not set.
    """
    prop = page.get("properties", {}).get(prop_name, {})
    return prop.get("url") or ""


def extract_email(page: dict, prop_name: str) -> str:
    """
    Extract the email address from an email property.

    Args:
        page: A Notion page object.
        prop_name: The property name holding the email.

    Returns:
        The email string, or empty string if not set.
    """
    prop = page.get("properties", {}).get(prop_name, {})
    return prop.get("email") or ""


def extract_checkbox(page: dict, prop_name: str) -> bool:
    """
    Extract the value from a checkbox property.

    Args:
        page: A Notion page object.
        prop_name: The property name holding the checkbox.

    Returns:
        The boolean value (defaults to False).
    """
    prop = page.get("properties", {}).get(prop_name, {})
    return prop.get("checkbox", False)


def extract_date(page: dict, prop_name: str) -> str:
    """
    Extract the start date string from a date property.

    Args:
        page: A Notion page object.
        prop_name: The property name holding the date.

    Returns:
        ISO date string, or empty string if not set.
    """
    prop = page.get("properties", {}).get(prop_name, {})
    date_obj = prop.get("date")
    if date_obj and isinstance(date_obj, dict):
        return date_obj.get("start", "")
    return ""


def extract_relation_ids(page: dict, prop_name: str) -> list[str]:
    """
    Extract the related page IDs from a relation property.

    Args:
        page: A Notion page object.
        prop_name: The property name holding the relation.

    Returns:
        List of related page UUIDs.
    """
    prop = page.get("properties", {}).get(prop_name, {})
    relations = prop.get("relation", [])
    return [r.get("id", "") for r in relations if r.get("id")]

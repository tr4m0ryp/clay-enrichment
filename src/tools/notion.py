import os
import time
import threading
from datetime import datetime, timezone

from notion_client import Client
from colorama import Fore, Style

from src.state import CompanyRecord, ContactRecord, EmailRecord

# Rate limiter: Notion API allows 3 requests per second
_rate_lock = threading.Lock()
_last_request_time = 0.0
_MIN_REQUEST_INTERVAL = 0.35  # slightly over 1/3 second for safety

# Cached Notion client instance (thread-safe via GIL for reads)
_client_lock = threading.Lock()
_cached_client = None


def _rate_limit():
    """
    Enforces Notion API rate limit by sleeping if requests are too frequent.
    Thread-safe via a lock.
    """
    global _last_request_time
    with _rate_lock:
        now = time.time()
        elapsed = now - _last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        _last_request_time = time.time()


def _get_client():
    """
    Returns a cached, authenticated Notion client using the API key from
    environment variables. The client is created once and reused across
    all calls.

    Returns:
        A notion_client.Client instance.
    """
    global _cached_client
    if _cached_client is not None:
        return _cached_client
    with _client_lock:
        # Double-check after acquiring lock
        if _cached_client is not None:
            return _cached_client
        api_key = os.getenv("NOTION_API_KEY")
        if not api_key:
            raise ValueError("NOTION_API_KEY environment variable is not set")
        _cached_client = Client(auth=api_key, notion_version="2022-06-28")
        return _cached_client


def _get_companies_db_id():
    """Returns the Notion Companies database ID from environment variables."""
    db_id = os.getenv("NOTION_COMPANIES_DB_ID")
    if not db_id:
        raise ValueError("NOTION_COMPANIES_DB_ID environment variable is not set")
    return db_id


def _get_emails_db_id():
    """Returns the Notion Emails database ID from environment variables."""
    db_id = os.getenv("NOTION_EMAILS_DB_ID")
    if not db_id:
        raise ValueError("NOTION_EMAILS_DB_ID environment variable is not set")
    return db_id


def company_exists(company_name):
    """
    Checks if a company with the given name already exists in the Notion
    Companies database. Used for de-duplication.

    Parameters:
        company_name: The company name to search for.

    Returns:
        True if a matching company exists, False otherwise.
    """
    try:
        _rate_limit()
        client = _get_client()
        response = _query_database(
            client,
            _get_companies_db_id(),
            filter_obj={
                "property": "Company Name",
                "title": {"equals": company_name}
            }
        )
        return len(response.get("results", [])) > 0
    except Exception as e:
        print(Fore.RED + f"Notion error checking company existence: {e}" + Style.RESET_ALL)
        return False


def create_company(company):
    """
    Creates a new company entry in the Notion Companies database.

    Parameters:
        company: A CompanyRecord instance with the company data.

    Returns:
        The Notion page ID of the created entry, or empty string on failure.
    """
    try:
        _rate_limit()
        client = _get_client()
        properties = {
            "Company Name": {"title": [{"text": {"content": company.name}}]},
            "Website": {"url": company.website or None},
            "Industry": {"select": {"name": company.industry}} if company.industry else {"select": None},
            "Location": {"rich_text": [{"text": {"content": company.location}}]},
            "Size": {"rich_text": [{"text": {"content": company.size}}]},
            "LinkedIn": {"url": company.linkedin_url or None},
            "Social Media": {"rich_text": [{"text": {"content": company.social_media}}]},
            "DPP Fit Score": {"number": company.dpp_fit_score},
            "Status": {"select": {"name": company.status}},
            "Summary": {"rich_text": [{"text": {"content": company.summary[:2000]}}]},
            "Discovery Source": {"rich_text": [{"text": {"content": company.discovery_source[:2000]}}]},
        }
        response = client.pages.create(
            parent={"database_id": _get_companies_db_id()},
            properties=properties
        )
        page_id = response["id"]
        print(Fore.GREEN + f"Created company in Notion: {company.name}" + Style.RESET_ALL)
        return page_id
    except Exception as e:
        print(Fore.RED + f"Notion error creating company: {e}" + Style.RESET_ALL)
        return ""


def update_company(page_id, updates):
    """
    Updates properties of an existing company page in Notion.

    Parameters:
        page_id: The Notion page ID to update.
        updates: A dict mapping property names to their new values.
            Supported keys: "Status", "DPP Fit Score", "Industry",
            "Location", "Size", "LinkedIn", "Social Media", "Summary",
            "Contact Name", "Contact Email", "Contact Phone",
            "Contact Title", "Contact LinkedIn".
    """
    try:
        _rate_limit()
        client = _get_client()
        properties = {}
        for key, value in updates.items():
            if key in ("Status", "Industry"):
                properties[key] = {"select": {"name": value}} if value else {"select": None}
            elif key == "DPP Fit Score":
                properties[key] = {"number": value}
            elif key in ("Website", "LinkedIn", "Contact LinkedIn"):
                properties[key] = {"url": value or None}
            elif key == "Contact Email":
                properties[key] = {"email": value or None}
            elif key == "Contact Phone":
                properties[key] = {"phone_number": value or None}
            else:
                properties[key] = {"rich_text": [{"text": {"content": str(value)[:2000]}}]}
        client.pages.update(page_id=page_id, properties=properties)
    except Exception as e:
        print(Fore.RED + f"Notion error updating company {page_id}: {e}" + Style.RESET_ALL)


def query_companies_by_status(status):
    """
    Fetches all companies with a given status from the Notion Companies
    database.

    Parameters:
        status: The status value to filter by (e.g., "Discovered", "Enriched").

    Returns:
        A list of CompanyRecord instances.
    """
    try:
        client = _get_client()
        results = []
        has_more = True
        start_cursor = None

        while has_more:
            _rate_limit()
            body = {
                "filter": {
                    "property": "Status",
                    "select": {"equals": status}
                }
            }
            if start_cursor:
                body["start_cursor"] = start_cursor

            response = _query_database(
                client, _get_companies_db_id(), body=body
            )

            for page in response.get("results", []):
                results.append(_page_to_company_record(page))

            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")

        return results
    except Exception as e:
        print(Fore.RED + f"Notion error querying companies: {e}" + Style.RESET_ALL)
        return []


def get_company_by_page_id(page_id):
    """
    Fetches a single company record by its Notion page ID.

    Parameters:
        page_id: The Notion page ID.

    Returns:
        A CompanyRecord instance, or None if not found.
    """
    try:
        _rate_limit()
        client = _get_client()
        page = client.pages.retrieve(page_id=page_id)
        return _page_to_company_record(page)
    except Exception as e:
        print(Fore.RED + f"Notion error fetching company {page_id}: {e}" + Style.RESET_ALL)
        return None


def create_email(email_record):
    """
    Creates a new email entry in the Notion Emails database.

    Parameters:
        email_record: An EmailRecord instance with the email data.

    Returns:
        The Notion page ID of the created entry, or empty string on failure.
    """
    try:
        _rate_limit()
        client = _get_client()
        properties = {
            "Subject": {"title": [{"text": {"content": email_record.subject}}]},
            "Recipient Email": {"email": email_record.recipient_email or None},
            "Recipient Name": {"rich_text": [{"text": {"content": email_record.recipient_name}}]},
            "Company": {"rich_text": [{"text": {"content": email_record.company_name}}]},
            "Email Body": {"rich_text": [{"text": {"content": email_record.body[:2000]}}]},
            "Status": {"select": {"name": email_record.status}},
            "Company Page ID": {"rich_text": [{"text": {"content": email_record.company_notion_id}}]},
        }
        response = client.pages.create(
            parent={"database_id": _get_emails_db_id()},
            properties=properties
        )
        page_id = response["id"]
        print(Fore.GREEN + f"Created email in Notion for: {email_record.recipient_name}" + Style.RESET_ALL)
        return page_id
    except Exception as e:
        print(Fore.RED + f"Notion error creating email: {e}" + Style.RESET_ALL)
        return ""


def update_email_status(page_id, status, sender=""):
    """
    Updates the status of an email in Notion. Optionally records the sender
    address used.

    Parameters:
        page_id: The Notion page ID of the email.
        status: The new status ("Pending Review", "Approved", "Sent", "Rejected").
        sender: The sender email address (set when status is "Sent").
    """
    try:
        _rate_limit()
        client = _get_client()
        properties = {
            "Status": {"select": {"name": status}},
        }
        if sender:
            properties["Sender Address"] = {"rich_text": [{"text": {"content": sender}}]}
        # Record the sent date when marking as Sent
        if status == "Sent":
            properties["Sent Date"] = {
                "date": {"start": datetime.now(timezone.utc).isoformat()}
            }
        client.pages.update(page_id=page_id, properties=properties)
    except Exception as e:
        print(Fore.RED + f"Notion error updating email status {page_id}: {e}" + Style.RESET_ALL)


def get_emails_by_status(status):
    """
    Fetches all emails with a given status from the Notion Emails database.

    Parameters:
        status: The status to filter by (e.g., "Approved").

    Returns:
        A list of EmailRecord instances.
    """
    try:
        client = _get_client()
        results = []
        has_more = True
        start_cursor = None

        while has_more:
            _rate_limit()
            body = {
                "filter": {
                    "property": "Status",
                    "select": {"equals": status}
                }
            }
            if start_cursor:
                body["start_cursor"] = start_cursor

            response = _query_database(
                client, _get_emails_db_id(), body=body
            )

            for page in response.get("results", []):
                results.append(_page_to_email_record(page))

            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")

        return results
    except Exception as e:
        print(Fore.RED + f"Notion error querying emails: {e}" + Style.RESET_ALL)
        return []


def get_contact_from_company(page_id):
    """
    Reads the primary contact fields stored on a company page and returns
    a ContactRecord. Used by the email layer for Notion recovery when
    restarting or running in single-layer mode.

    Parameters:
        page_id: The Notion page ID of the company.

    Returns:
        A ContactRecord instance, or None if no contact email is stored.
    """
    try:
        _rate_limit()
        client = _get_client()
        page = client.pages.retrieve(page_id=page_id)
        props = page.get("properties", {})

        contact_email = props.get("Contact Email", {}).get("email", "") or ""
        if not contact_email:
            return None

        return ContactRecord(
            name=_get_text_property(props, "Contact Name"),
            email=contact_email,
            title=_get_text_property(props, "Contact Title"),
            linkedin_url=props.get("Contact LinkedIn", {}).get("url", "") or "",
            company_name=_get_title_property(props, "Company Name"),
            company_notion_id=page_id,
        )
    except Exception as e:
        print(Fore.RED + f"Notion error getting contact from company {page_id}: {e}" + Style.RESET_ALL)
        return None


def _query_database(client, database_id, filter_obj=None, body=None):
    """
    Queries a Notion database using the raw request method. This is needed
    because notion-client v3 removed databases.query().

    Parameters:
        client: An authenticated Notion client.
        database_id: The database ID to query.
        filter_obj: Optional filter dict (shorthand for simple queries).
        body: Optional full request body dict (overrides filter_obj).

    Returns:
        The API response dict with "results", "has_more", and "next_cursor".
    """
    if body is None:
        body = {}
    if filter_obj and "filter" not in body:
        body["filter"] = filter_obj
    return client.request(
        path=f"databases/{database_id}/query",
        method="POST",
        body=body,
    )


def _get_text_property(properties, key):
    """
    Extracts a plain text string from a Notion rich_text property.

    Parameters:
        properties: The page properties dict from Notion API.
        key: The property name to extract.

    Returns:
        The text content as a string, or empty string if not found.
    """
    prop = properties.get(key, {})
    rich_text = prop.get("rich_text", [])
    if rich_text:
        return rich_text[0].get("text", {}).get("content", "")
    return ""


def _get_title_property(properties, key):
    """
    Extracts a plain text string from a Notion title property.

    Parameters:
        properties: The page properties dict from Notion API.
        key: The property name to extract.

    Returns:
        The title text as a string, or empty string if not found.
    """
    prop = properties.get(key, {})
    title = prop.get("title", [])
    if title:
        return title[0].get("text", {}).get("content", "")
    return ""


def _page_to_company_record(page):
    """
    Converts a Notion page object into a CompanyRecord instance.

    Parameters:
        page: A Notion page object from the API response.

    Returns:
        A CompanyRecord instance populated with the page data.
    """
    props = page.get("properties", {})
    score = props.get("DPP Fit Score", {}).get("number", 0.0) or 0.0
    status_obj = props.get("Status", {}).get("select")
    status = status_obj.get("name", "Discovered") if status_obj else "Discovered"
    industry_obj = props.get("Industry", {}).get("select")
    industry = industry_obj.get("name", "") if industry_obj else ""

    return CompanyRecord(
        name=_get_title_property(props, "Company Name"),
        website=props.get("Website", {}).get("url", "") or "",
        industry=industry,
        location=_get_text_property(props, "Location"),
        size=_get_text_property(props, "Size"),
        linkedin_url=props.get("LinkedIn", {}).get("url", "") or "",
        social_media=_get_text_property(props, "Social Media"),
        dpp_fit_score=score,
        dpp_fit_reasoning=_get_text_property(props, "DPP Fit Reasoning"),
        status=status,
        notion_page_id=page["id"],
        discovery_source=_get_text_property(props, "Discovery Source"),
        summary=_get_text_property(props, "Summary"),
    )


def _page_to_email_record(page):
    """
    Converts a Notion page object into an EmailRecord instance.

    Parameters:
        page: A Notion page object from the API response.

    Returns:
        An EmailRecord instance populated with the page data.
    """
    props = page.get("properties", {})
    status_obj = props.get("Status", {}).get("select")
    status = status_obj.get("name", "Pending Review") if status_obj else "Pending Review"

    return EmailRecord(
        subject=_get_title_property(props, "Subject"),
        body=_get_text_property(props, "Email Body"),
        recipient_email=props.get("Recipient Email", {}).get("email", "") or "",
        recipient_name=_get_text_property(props, "Recipient Name"),
        company_name=_get_text_property(props, "Company"),
        status=status,
        sender_address=_get_text_property(props, "Sender Address"),
        company_notion_id=_get_text_property(props, "Company Page ID"),
        notion_page_id=page["id"],
    )

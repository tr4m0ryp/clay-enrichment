"""
One-time setup script to create the Notion databases for the Avelero
lead discovery pipeline. Run with: python main.py --setup

Creates two databases:
1. Companies -- stores discovered and enriched companies
2. Emails -- stores generated outreach emails for review and sending

Requires NOTION_API_KEY and a parent page ID in the environment.
"""

import os

from dotenv import load_dotenv
from notion_client import Client
from colorama import Fore, Style

load_dotenv()


def setup_databases():
    """
    Creates the Companies and Emails databases in Notion under a specified
    parent page. Prints the database IDs that should be added to the .env file.

    Requires the NOTION_API_KEY and NOTION_PARENT_PAGE_ID environment
    variables to be set.
    """
    api_key = os.getenv("NOTION_API_KEY")
    parent_page_id = os.getenv("NOTION_PARENT_PAGE_ID")

    if not api_key:
        print(Fore.RED + "NOTION_API_KEY is not set in .env" + Style.RESET_ALL)
        return

    if not parent_page_id:
        print(Fore.RED + "NOTION_PARENT_PAGE_ID is not set in .env" + Style.RESET_ALL)
        print("Set this to the ID of the Notion page where databases should be created.")
        return

    client = Client(auth=api_key)

    # Create Companies database
    print(Fore.YELLOW + "Creating Companies database..." + Style.RESET_ALL)
    companies_db = _create_companies_database(client, parent_page_id)
    if companies_db:
        print(Fore.GREEN + f"Companies database created. ID: {companies_db}" + Style.RESET_ALL)

    # Create Emails database
    print(Fore.YELLOW + "Creating Emails database..." + Style.RESET_ALL)
    emails_db = _create_emails_database(client, parent_page_id)
    if emails_db:
        print(Fore.GREEN + f"Emails database created. ID: {emails_db}" + Style.RESET_ALL)

    print()
    print(Fore.GREEN + "Add these to your .env file:" + Style.RESET_ALL)
    print(f"NOTION_COMPANIES_DB_ID={companies_db}")
    print(f"NOTION_EMAILS_DB_ID={emails_db}")


def _create_companies_database(client, parent_page_id):
    """
    Creates the Companies database with all required properties.

    Parameters:
        client: An authenticated Notion client.
        parent_page_id: The Notion page ID to create the database under.

    Returns:
        The database ID string, or None on failure.
    """
    try:
        response = client.databases.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": "Companies"}}],
            properties={
                "Company Name": {"title": {}},
                "Website": {"url": {}},
                "Industry": {
                    "select": {
                        "options": [
                            {"name": "Streetwear", "color": "blue"},
                            {"name": "Contemporary Fashion", "color": "purple"},
                            {"name": "Premium Footwear", "color": "green"},
                            {"name": "Sustainable Fashion", "color": "yellow"},
                            {"name": "Luxury Accessories", "color": "orange"},
                            {"name": "Lifestyle", "color": "pink"},
                            {"name": "Sportswear", "color": "red"},
                            {"name": "Other", "color": "gray"},
                        ]
                    }
                },
                "Location": {"rich_text": {}},
                "Size": {"rich_text": {}},
                "LinkedIn": {"url": {}},
                "Social Media": {"rich_text": {}},
                "DPP Fit Score": {"number": {"format": "number"}},
                "Status": {
                    "select": {
                        "options": [
                            {"name": "Discovered", "color": "gray"},
                            {"name": "Enriched", "color": "blue"},
                            {"name": "Contacts Found", "color": "purple"},
                            {"name": "Email Drafted", "color": "yellow"},
                            {"name": "Email Sent", "color": "green"},
                            {"name": "Low Fit", "color": "red"},
                        ]
                    }
                },
                "Summary": {"rich_text": {}},
                "Discovery Source": {"rich_text": {}},
                "Contact Name": {"rich_text": {}},
                "Contact Email": {"email": {}},
                "Contact Phone": {"phone_number": {}},
                "Contact Title": {"rich_text": {}},
                "Contact LinkedIn": {"url": {}},
                "DPP Fit Reasoning": {"rich_text": {}},
            }
        )
        return response["id"]
    except Exception as e:
        print(Fore.RED + f"Error creating Companies database: {e}" + Style.RESET_ALL)
        return None


def _create_emails_database(client, parent_page_id):
    """
    Creates the Emails database with all required properties.

    Parameters:
        client: An authenticated Notion client.
        parent_page_id: The Notion page ID to create the database under.

    Returns:
        The database ID string, or None on failure.
    """
    try:
        response = client.databases.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": "Outreach Emails"}}],
            properties={
                "Subject": {"title": {}},
                "Recipient Email": {"email": {}},
                "Recipient Name": {"rich_text": {}},
                "Company": {"rich_text": {}},
                "Email Body": {"rich_text": {}},
                "Status": {
                    "select": {
                        "options": [
                            {"name": "Pending Review", "color": "yellow"},
                            {"name": "Approved", "color": "blue"},
                            {"name": "Sent", "color": "green"},
                            {"name": "Rejected", "color": "red"},
                        ]
                    }
                },
                "Sender Address": {"rich_text": {}},
                "Sent Date": {"date": {}},
            }
        )
        return response["id"]
    except Exception as e:
        print(Fore.RED + f"Error creating Emails database: {e}" + Style.RESET_ALL)
        return None


if __name__ == "__main__":
    setup_databases()

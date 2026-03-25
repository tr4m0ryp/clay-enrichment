import os
import re

import requests
from colorama import Fore, Style


_RAPIDAPI_HOST = "fresh-linkedin-scraper-api.p.rapidapi.com"
_BASE_URL = f"https://{_RAPIDAPI_HOST}/api/v1"


def find_linkedin_profile_url(search_results):
    """
    Extracts a personal LinkedIn profile URL from a list of search results.
    Looks for URLs containing 'linkedin.com/in/' and filters out company
    pages and post URLs.

    Parameters:
        search_results: A list of dicts, each with a "link" key.

    Returns:
        The first matching LinkedIn personal profile URL, or empty string
        if none found.
    """
    for result in search_results:
        link = result.get("link", "")
        if "linkedin.com/in/" in link and "/posts" not in link:
            return link
    return ""


def find_linkedin_company_url(search_results):
    """
    Extracts a LinkedIn company page URL from a list of search results.
    Looks for URLs containing 'linkedin.com/company/'.

    Parameters:
        search_results: A list of dicts, each with a "link" key.

    Returns:
        The first matching LinkedIn company URL, or empty string if none found.
    """
    for result in search_results:
        link = result.get("link", "")
        if "linkedin.com/company/" in link:
            return link
    return ""


def scrape_linkedin(linkedin_url, is_company=False):
    """
    Scrapes LinkedIn profile data using the Fresh LinkedIn Scraper API
    on RapidAPI. Returns None gracefully if no API key is configured or
    the API is unavailable, so the pipeline can continue without LinkedIn
    enrichment.

    Parameters:
        linkedin_url: The LinkedIn profile or company URL to scrape.
        is_company: If True, scrapes a company profile. If False, scrapes
            a personal profile.

    Returns:
        A dict containing the scraped profile data, or None if the request
        fails or the API is not configured.
    """
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        return None

    # Extract the slug/username from the LinkedIn URL
    slug = _extract_slug(linkedin_url, is_company)
    if not slug:
        return None

    if is_company:
        url = f"{_BASE_URL}/company/profile"
        params = {"company": slug}
    else:
        url = f"{_BASE_URL}/user/profile"
        params = {"username": slug}

    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": _RAPIDAPI_HOST,
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict) and data.get("success") is False:
                return None
            # Return the nested data dict for consistency
            return data.get("data") if isinstance(data, dict) else data
        elif response.status_code in (403, 404):
            return None
        else:
            print(Fore.RED + f"LinkedIn scrape failed with status code: {response.status_code}" + Style.RESET_ALL)
            return None
    except requests.RequestException as e:
        print(Fore.RED + f"LinkedIn scrape error: {e}" + Style.RESET_ALL)
        return None


def _extract_slug(linkedin_url, is_company):
    """
    Extracts the username or company slug from a LinkedIn URL.
    For example:
        https://www.linkedin.com/in/william-gates-123abc -> william-gates-123abc
        https://linkedin.com/company/norse-projects/ -> norse-projects

    Parameters:
        linkedin_url: The full LinkedIn URL.
        is_company: If True, extracts from /company/ path. If False,
            extracts from /in/ path.

    Returns:
        The extracted slug string, or empty string if the URL does not
        match the expected pattern.
    """
    if not linkedin_url:
        return ""

    if is_company:
        match = re.search(r"linkedin\.com/company/([^/?#]+)", linkedin_url)
    else:
        match = re.search(r"linkedin\.com/in/([^/?#]+)", linkedin_url)

    if match:
        return match.group(1).strip("/")
    return ""

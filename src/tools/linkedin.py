import os

import requests
from colorama import Fore, Style


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
    Scrapes LinkedIn profile data using the RapidAPI LinkedIn scraper.

    Parameters:
        linkedin_url: The LinkedIn profile or company URL to scrape.
        is_company: If True, scrapes a company profile. If False, scrapes
            a personal profile.

    Returns:
        A dict containing the scraped profile data, or None if the request
        fails.
    """
    if is_company:
        url = "https://fresh-linkedin-profile-data.p.rapidapi.com/get-company-by-linkedinurl"
    else:
        url = "https://fresh-linkedin-profile-data.p.rapidapi.com/get-linkedin-profile"

    querystring = {"linkedin_url": linkedin_url}
    headers = {
        "x-rapidapi-key": os.getenv("RAPIDAPI_KEY"),
        "x-rapidapi-host": "fresh-linkedin-profile-data.p.rapidapi.com"
    }

    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=15)
        if response.status_code == 200:
            return response.json()
        else:
            print(Fore.RED + f"LinkedIn scrape failed with status code: {response.status_code}" + Style.RESET_ALL)
            return None
    except requests.RequestException as e:
        print(Fore.RED + f"LinkedIn scrape error: {e}" + Style.RESET_ALL)
        return None

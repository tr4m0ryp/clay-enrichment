import os

import requests
from colorama import Fore, Style


def google_search(query, num_results=10):
    """
    Performs a web search using the Serper API (returns Google search results).

    Parameters:
        query: The search query string.
        num_results: Maximum number of results to return (default 10).

    Returns:
        A list of dicts, each containing "title", "link", and "snippet" keys.
        Returns an empty list if the request fails.
    """
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        print(Fore.RED + "SERPER_API_KEY not set" + Style.RESET_ALL)
        return []

    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            },
            json={"q": query, "num": num_results},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("organic", []):
            results.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        return results
    except Exception as e:
        print(Fore.RED + f"Serper search error: {e}" + Style.RESET_ALL)
        return []


def google_news_search(company, num_results=10):
    """
    Searches for recent news about a company using the Serper News API.

    Parameters:
        company: The company name to search news for.
        num_results: Maximum number of results to return (default 10).

    Returns:
        A formatted string of news results with title, snippet, and URL.
        Returns an empty string if the request fails.
    """
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        print(Fore.RED + "SERPER_API_KEY not set" + Style.RESET_ALL)
        return ""

    try:
        response = requests.post(
            "https://google.serper.dev/news",
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            },
            json={"q": f"{company} news", "num": num_results},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        news_string = ""
        for item in data.get("news", []):
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            link = item.get("link", "")
            news_string += f"Title: {title}\nSnippet: {snippet}\nURL: {link}\n\n"

        return news_string
    except Exception as e:
        print(Fore.RED + f"Serper news search error: {e}" + Style.RESET_ALL)
        return ""

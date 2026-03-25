import os

from googleapiclient.discovery import build
from colorama import Fore, Style


def google_search(query, num_results=10):
    """
    Performs a Google search using the Custom Search JSON API.

    Parameters:
        query: The search query string.
        num_results: Maximum number of results to return (default 10, max 10
            per request).

    Returns:
        A list of dicts, each containing "title", "link", and "snippet" keys.
        Returns an empty list if the request fails.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    cse_id = os.getenv("GOOGLE_CSE_ID")

    if not api_key or not cse_id:
        print(Fore.RED + "GOOGLE_API_KEY or GOOGLE_CSE_ID not set" + Style.RESET_ALL)
        return []

    try:
        service = build("customsearch", "v1", developerKey=api_key)
        result = service.cse().list(q=query, cx=cse_id, num=min(num_results, 10)).execute()

        items = result.get("items", [])
        results = []
        for item in items:
            results.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        return results
    except Exception as e:
        print(Fore.RED + f"Google search error: {e}" + Style.RESET_ALL)
        return []


def google_news_search(company, num_results=20):
    """
    Searches Google for recent news about a company using the Custom Search
    JSON API with date-restricted results.

    Parameters:
        company: The company name to search news for.
        num_results: Maximum number of results to return (default 20).

    Returns:
        A formatted string of news results with title, snippet, and URL.
        Returns an error message string if the request fails.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    cse_id = os.getenv("GOOGLE_CSE_ID")

    if not api_key or not cse_id:
        print(Fore.RED + "GOOGLE_API_KEY or GOOGLE_CSE_ID not set" + Style.RESET_ALL)
        return ""

    try:
        service = build("customsearch", "v1", developerKey=api_key)

        # Fetch results in batches of 10 (API limit per request)
        all_items = []
        for start_index in range(1, num_results + 1, 10):
            batch_size = min(10, num_results - len(all_items))
            result = service.cse().list(
                q=f"{company} news",
                cx=cse_id,
                num=batch_size,
                start=start_index,
                dateRestrict="y1",
                sort="date",
            ).execute()
            all_items.extend(result.get("items", []))
            if len(result.get("items", [])) < batch_size:
                break

        news_string = ""
        for item in all_items:
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            link = item.get("link", "")
            news_string += f"Title: {title}\nSnippet: {snippet}\nURL: {link}\n\n"

        return news_string
    except Exception as e:
        print(Fore.RED + f"Google news search error: {e}" + Style.RESET_ALL)
        return ""

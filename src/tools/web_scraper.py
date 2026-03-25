import re

import html2text
import requests
from bs4 import BeautifulSoup
from colorama import Fore, Style


def scrape_website_to_markdown(url):
    """
    Scrapes a website and converts its HTML content to markdown format.

    Parameters:
        url: The URL of the website to scrape.

    Returns:
        The website content as a cleaned-up markdown string.
        Returns an empty string if the request fails.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.77 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(Fore.RED + f"Failed to fetch {url}. Status code: {response.status_code}" + Style.RESET_ALL)
            return ""

        # Remove script and style tags before conversion
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.ignore_tables = True
        markdown_content = h.handle(str(soup))

        # Clean up excess newlines
        markdown_content = re.sub(r"\n{3,}", "\n\n", markdown_content)
        markdown_content = markdown_content.strip()

        return markdown_content
    except requests.RequestException as e:
        print(Fore.RED + f"Error scraping {url}: {e}" + Style.RESET_ALL)
        return ""

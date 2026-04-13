"""
Prompt for Gemini grounded website lookup.

Used as a fallback when the SearXNG-based website resolver fails to find
a valid brand website. Asks Gemini with Google Search grounding to locate
the company's official website URL.
"""

from src.prompts.base_context import build_system_prompt

FIND_COMPANY_WEBSITE = build_system_prompt("""\
## Task: Find Official Company Website

Find the official website URL for the following company:

Company name: {company_name}

### Instructions

Search for this company's official website. Return ONLY a JSON object:

```json
{{"website_url": "https://example.com", "confidence": "high"}}
```

### Rules

- Return the company's OWN website, not a retailer, marketplace, or directory
- Do NOT return social media profiles (LinkedIn, Instagram, Facebook)
- Do NOT return marketplace pages (Amazon, Zalando, ASOS, Farfetch)
- Do NOT return directory listings (Crunchbase, Bloomberg, Wikipedia)
- Do NOT return search engines or aggregators
- If you cannot find an official website, return: {{"website_url": "", "confidence": "none"}}
- URL must be root domain (e.g. "https://example.com", not deep paths)
""")

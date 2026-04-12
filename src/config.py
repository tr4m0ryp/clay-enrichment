from dataclasses import dataclass, field
from dotenv import load_dotenv
import os
import re

load_dotenv()


@dataclass
class SenderAccount:
    email: str
    password: str


@dataclass
class Config:
    # Gemini
    gemini_api_key: str = ""
    model_discovery: str = "gemini-2.5-flash-lite"
    model_enrichment: str = "gemini-2.5-flash-lite"
    model_scoring: str = "gemini-2.5-flash-lite"
    model_contact_extraction: str = "gemini-2.5-flash-lite"
    model_email_generation: str = "gemini-2.5-flash"
    model_research: str = "gemini-2.5-flash"

    # Google Search (legacy, deprecated)
    google_api_key: str = ""
    google_cse_id: str = ""

    # SearXNG (self-hosted meta-search)
    searxng_url: str = "http://localhost:8888"

    # Brave Search API
    brave_search_api_key: str = ""

    # Notion
    notion_api_key: str = ""
    notion_hub_page_id: str = ""
    notion_campaigns_db_id: str = ""
    notion_companies_db_id: str = ""
    notion_contacts_db_id: str = ""
    notion_emails_db_id: str = ""
    notion_contact_campaigns_db_id: str = ""
    notion_leads_page_id: str = ""

    # Email
    smtp_host: str = ""
    smtp_port: int = 587
    senders: list = field(default_factory=list)
    email_daily_limit: int = 10
    email_min_delay: int = 180
    email_max_delay: int = 480

    # Enrichment
    enrichment_stale_days: int = 90


def _discover_senders() -> list:
    senders = []
    indices = set()
    for key in os.environ:
        m = re.match(r"^SENDER_(\d+)_EMAIL$", key)
        if m:
            indices.add(int(m.group(1)))
    for idx in sorted(indices):
        email_val = os.environ.get(f"SENDER_{idx}_EMAIL", "").strip()
        password_val = os.environ.get(f"SENDER_{idx}_PASSWORD", "").strip()
        if email_val and password_val:
            senders.append(SenderAccount(email=email_val, password=password_val))
    return senders


def _load_config() -> Config:
    cfg = Config(
        gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
        model_discovery=os.environ.get("MODEL_DISCOVERY", "gemini-2.5-flash-lite").strip(),
        model_enrichment=os.environ.get("MODEL_ENRICHMENT", "gemini-2.5-flash-lite").strip(),
        model_scoring=os.environ.get("MODEL_SCORING", "gemini-2.5-flash-lite").strip(),
        model_contact_extraction=os.environ.get("MODEL_CONTACT_EXTRACTION", "gemini-2.5-flash-lite").strip(),
        model_email_generation=os.environ.get("MODEL_EMAIL_GENERATION", "gemini-2.5-flash").strip(),
        model_research=os.environ.get("MODEL_RESEARCH", "gemini-2.5-flash").strip(),
        google_api_key=os.environ.get("GOOGLE_API_KEY", "").strip(),
        google_cse_id=os.environ.get("GOOGLE_CSE_ID", "").strip(),
        searxng_url=os.environ.get("SEARXNG_URL", "http://localhost:8888").strip(),
        brave_search_api_key=os.environ.get("BRAVE_SEARCH_API_KEY", "").strip(),
        notion_api_key=os.environ.get("NOTION_API_KEY", "").strip(),
        notion_hub_page_id=os.environ.get("NOTION_HUB_PAGE_ID", "").strip(),
        notion_campaigns_db_id=os.environ.get("NOTION_CAMPAIGNS_DB_ID", "").strip(),
        notion_companies_db_id=os.environ.get("NOTION_COMPANIES_DB_ID", "").strip(),
        notion_contacts_db_id=os.environ.get("NOTION_CONTACTS_DB_ID", "").strip(),
        notion_emails_db_id=os.environ.get("NOTION_EMAILS_DB_ID", "").strip(),
        notion_contact_campaigns_db_id=os.environ.get("NOTION_CONTACT_CAMPAIGNS_DB_ID", "").strip(),
        notion_leads_page_id=os.environ.get("NOTION_LEADS_PAGE_ID", "").strip(),
        smtp_host=os.environ.get("SMTP_HOST", "").strip(),
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        senders=_discover_senders(),
        email_daily_limit=int(os.environ.get("EMAIL_DAILY_LIMIT_PER_SENDER", "10")),
        email_min_delay=int(os.environ.get("EMAIL_MIN_DELAY_SECONDS", "180")),
        email_max_delay=int(os.environ.get("EMAIL_MAX_DELAY_SECONDS", "480")),
        enrichment_stale_days=int(os.environ.get("ENRICHMENT_STALE_DAYS", "90")),
    )

    required = {
        "GEMINI_API_KEY": cfg.gemini_api_key,
        "NOTION_API_KEY": cfg.notion_api_key,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
        print("Set them in your .env file before running.")

    return cfg


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = _load_config()
    return _config

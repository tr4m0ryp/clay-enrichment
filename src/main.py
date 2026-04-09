"""
Main orchestrator and entry point.

Loads config, initializes all clients, runs Notion database setup,
and launches all workers as concurrent asyncio tasks with supervision
and graceful shutdown.

Run as: python3 -m src.main
"""

import asyncio
import logging
import signal
import sys
from types import SimpleNamespace

from src.config import get_config, Config
from src.utils.logger import setup_logging, get_logger
from src.utils.rate_limiter import RateLimiter, DEFAULT_LIMITS
from src.models.gemini import GeminiClient
from src.notion.client import NotionClient
from src.notion.setup import setup_databases
from src.notion.databases import CampaignsDB, CompaniesDB, ContactsDB, EmailsDB
from src.search.brave_search import BraveSearchClient
from src.search.searxng import SearXNGClient
from src.search.scraper import WebScraper
from src.discovery.contact_finder import ContactFinder
from src.discovery.email_permutation import EmailPermutator
from src.discovery.smtp_verify import SMTPVerifier
from src.layers.discovery import (
    discovery_worker,
    NotionClients as DiscoveryNotionClients,
)
from src.layers.enrichment import enrichment_worker
from src.layers.people import (
    people_worker,
    NotionClients as PeopleNotionClients,
)
from src.layers.person_research import person_research_worker
from src.layers.campaign_scoring import campaign_scoring_worker
from src.layers.email_gen import email_gen_worker
from src.email.sender import email_sender_worker
from src.notion.dashboard import setup_dashboard
from src.layers.dashboard_worker import dashboard_stats_worker
from src.notion.databases_contact_campaigns import ContactCampaignsDB
from src.notion.leads_pages import refresh_leads_pages

logger: logging.Logger | None = None

shutdown_event: asyncio.Event | None = None

RESTART_DELAY_SECONDS = 30.0


def _get_shutdown_event() -> asyncio.Event:
    """Return the shutdown event, creating it lazily for the current loop."""
    global shutdown_event
    if shutdown_event is None:
        shutdown_event = asyncio.Event()
    return shutdown_event


def _validate_config(config: Config) -> None:
    """Validate required config fields are set. Exits on failure."""
    required = {
        "GEMINI_API_KEY": config.gemini_api_key,
        "NOTION_API_KEY": config.notion_api_key,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        msg = f"Missing required config: {', '.join(missing)}"
        if logger:
            logger.error(msg)
        else:
            print(f"ERROR: {msg}")
        sys.exit(1)


def _log_startup_summary(config: Config) -> None:
    """Log a startup summary with non-secret configuration info."""
    assert logger is not None
    logger.info("--- Avelero Clay Enrichment starting ---")
    logger.info("Models: discovery=%s enrichment=%s scoring=%s contact=%s email=%s",
                config.model_discovery, config.model_enrichment,
                config.model_scoring, config.model_contact_extraction,
                config.model_email_generation)
    logger.info("Notion hub page: %s", config.notion_hub_page_id or "(not set)")
    logger.info("SearXNG URL: %s", config.searxng_url)
    logger.info("SMTP configured: %s (host=%s port=%d)",
                bool(config.smtp_host), config.smtp_host or "(none)", config.smtp_port)
    logger.info("Senders configured: %d (daily limit %d per sender)",
                len(config.senders), config.email_daily_limit)
    logger.info("Enrichment stale threshold: %d days", config.enrichment_stale_days)
    logger.info("Contact-Campaigns DB: %s", config.notion_contact_campaigns_db_id or "(auto)")
    logger.info("Leads page: %s", config.notion_leads_page_id or "(auto)")


async def supervised_worker(name: str, worker_fn, *args, **kwargs) -> None:
    """Run a worker with automatic restart on crash (30s delay)."""
    assert logger is not None
    evt = _get_shutdown_event()
    while not evt.is_set():
        try:
            logger.info("Worker '%s' starting", name)
            await worker_fn(*args, **kwargs)
        except asyncio.CancelledError:
            logger.info("Worker '%s' cancelled", name)
            return
        except Exception as exc:
            logger.error(
                "Worker '%s' crashed: %s. Restarting in %ds.",
                name, exc, int(RESTART_DELAY_SECONDS),
            )
            try:
                await asyncio.wait_for(
                    evt.wait(), timeout=RESTART_DELAY_SECONDS
                )
                return
            except asyncio.TimeoutError:
                pass


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """Install SIGINT/SIGTERM handlers for graceful shutdown."""
    def _handle_signal(sig_name: str) -> None:
        if logger:
            logger.info("Received %s, shutting down...", sig_name)
        _get_shutdown_event().set()
        tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig.name)


_LEADS_REFRESH_INTERVAL = 300  # seconds between leads page refreshes


async def _leads_refresh_loop(
    notion_client: NotionClient,
    contact_campaigns_db,
    campaigns_db,
    leads_page_id: str,
) -> None:
    """Periodically refresh the High Priority Leads pages."""
    log = get_logger("leads_refresh")
    log.info("Leads refresh loop started (interval=%ds)", _LEADS_REFRESH_INTERVAL)
    while True:
        if leads_page_id:
            try:
                await refresh_leads_pages(
                    notion_client, contact_campaigns_db, campaigns_db, leads_page_id,
                )
            except Exception as exc:
                log.error("Leads refresh failed: %s", exc)
        else:
            log.warning("No leads_page_id configured, skipping refresh")
        await asyncio.sleep(_LEADS_REFRESH_INTERVAL)


async def main() -> None:
    """Main entry point. Initializes everything and launches workers."""
    global logger

    setup_logging()
    logger = get_logger("main")

    config = get_config()
    _validate_config(config)
    _log_startup_summary(config)

    # Rate limiter (shared across all clients)
    rate_limiter = RateLimiter(DEFAULT_LIMITS)

    # Core clients
    gemini = GeminiClient(config, rate_limiter)
    notion_client = NotionClient(rate_limiter=rate_limiter)
    if config.brave_search_api_key:
        search_client = BraveSearchClient(api_key=config.brave_search_api_key)
        logger.info("Using Brave Search API")
    else:
        search_client = SearXNGClient(base_url=config.searxng_url)
        logger.info("Using SearXNG at %s", config.searxng_url)
    scraper = WebScraper()

    # Discovery utilities
    contact_finder = ContactFinder(search_client)
    email_permutator = EmailPermutator()
    smtp_verifier = SMTPVerifier()

    # Auto-create Notion databases if needed
    db_ids = await setup_databases(client=notion_client)
    logger.info("Notion databases ready: %s",
                {k: v[:8] + "..." for k, v in db_ids.items() if v})

    # Build dashboard layout (runs once on startup)
    try:
        await setup_dashboard(notion_client, config)
        logger.info("Dashboard layout initialized")
    except Exception:
        logger.exception("Dashboard setup failed, continuing without dashboard")

    # Database wrappers (all pull their DB ID from config singleton)
    campaigns_db = CampaignsDB(notion_client)
    companies_db = CompaniesDB(notion_client)
    contacts_db = ContactsDB(notion_client)
    emails_db = EmailsDB(notion_client)

    # Override DB IDs if setup just created them (config may not have them)
    if db_ids.get("campaigns"):
        campaigns_db.db_id = db_ids["campaigns"]
    if db_ids.get("companies"):
        companies_db.db_id = db_ids["companies"]
    if db_ids.get("contacts"):
        contacts_db.db_id = db_ids["contacts"]
    if db_ids.get("emails"):
        emails_db.db_id = db_ids["emails"]

    # Contact-Campaigns junction DB
    cc_db_id = db_ids.get("contact_campaigns") or config.notion_contact_campaigns_db_id
    contact_campaigns_db = ContactCampaignsDB(client=notion_client, db_id=cc_db_id)

    # Leads page ID (for refresh_leads_pages worker)
    leads_page_id = db_ids.get("leads_page") or config.notion_leads_page_id

    # Build per-worker notion client aggregates
    discovery_notion = DiscoveryNotionClients(
        campaigns=campaigns_db, companies=companies_db
    )
    people_notion = PeopleNotionClients(
        companies=companies_db, contacts=contacts_db
    )
    sender_notion = SimpleNamespace(
        emails=emails_db,
        contacts=contacts_db,
    )

    # Install signal handlers
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop)

    workers = [
        ("discovery", discovery_worker,
         [config, gemini, discovery_notion, search_client]),
        ("enrichment", enrichment_worker,
         [config, gemini, notion_client, companies_db, campaigns_db, scraper]),
        ("people", people_worker,
         [config, gemini, people_notion, contact_finder, email_permutator, smtp_verifier]),
        ("person_research", person_research_worker,
         [config, gemini, notion_client, contacts_db, search_client]),
        ("campaign_scoring", campaign_scoring_worker,
         [config, gemini, notion_client, contacts_db, companies_db, campaigns_db,
          contact_campaigns_db]),
        ("email_gen", email_gen_worker,
         [config, gemini, notion_client, contacts_db, campaigns_db, emails_db,
          contact_campaigns_db]),
        ("email_sender", email_sender_worker, [config, sender_notion]),
        ("leads_refresh", _leads_refresh_loop,
         [notion_client, contact_campaigns_db, campaigns_db, leads_page_id]),
        ("dashboard_stats", dashboard_stats_worker,
         [notion_client, campaigns_db, companies_db, contacts_db, emails_db]),
    ]
    logger.info("Launching %d workers", len(workers))

    try:
        await asyncio.gather(*(
            supervised_worker(name, fn, *args) for name, fn, args in workers
        ))
    except asyncio.CancelledError:
        pass

    logger.info("--- Avelero Clay Enrichment stopped ---")


if __name__ == "__main__":
    asyncio.run(main())

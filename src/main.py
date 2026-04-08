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
from src.layers.email_gen import email_gen_worker
from src.email.sender import email_sender_worker

logger: logging.Logger | None = None

shutdown_event: asyncio.Event | None = None

RESTART_DELAY_SECONDS = 30.0


def _get_shutdown_event() -> asyncio.Event:
    """Return the shutdown event, creating it if needed.

    Creates a new Event bound to the current running loop. This avoids
    issues with module-level Event objects becoming bound to stale loops.

    Returns:
        The global shutdown asyncio.Event.
    """
    global shutdown_event
    if shutdown_event is None:
        shutdown_event = asyncio.Event()
    return shutdown_event


def _validate_config(config: Config) -> None:
    """Validate that all required config fields are set. Exits on failure.

    Args:
        config: The loaded application configuration.

    Raises:
        SystemExit: If required configuration is missing.
    """
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
    """Log a startup summary with non-secret configuration info.

    Args:
        config: The loaded application configuration.
    """
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


async def supervised_worker(name: str, worker_fn, *args, **kwargs) -> None:
    """Run a worker function with automatic restart on crash.

    If the worker raises an exception, logs the error and restarts
    after a 30-second delay. Respects the global shutdown_event to
    stop cleanly.

    Args:
        name: Human-readable name for the worker (used in logs).
        worker_fn: The async worker coroutine to run.
        *args: Positional arguments forwarded to worker_fn.
        **kwargs: Keyword arguments forwarded to worker_fn.
    """
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
    """Install SIGINT and SIGTERM handlers for graceful shutdown.

    Sets the shutdown_event so workers can exit their loops, then
    cancels all running tasks.

    Args:
        loop: The running asyncio event loop.
    """
    def _handle_signal(sig_name: str) -> None:
        if logger:
            logger.info("Received %s, shutting down...", sig_name)
        _get_shutdown_event().set()
        tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig.name)


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

    # Build per-worker notion client aggregates
    discovery_notion = DiscoveryNotionClients(
        campaigns=campaigns_db, companies=companies_db
    )
    people_notion = PeopleNotionClients(
        companies=companies_db, contacts=contacts_db
    )
    email_gen_dbs = {
        "campaigns": campaigns_db,
        "contacts": contacts_db,
        "emails": emails_db,
    }
    sender_notion = SimpleNamespace(
        emails=emails_db,
        contacts=contacts_db,
    )

    # Install signal handlers
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop)

    logger.info("Launching 5 workers")

    # Launch all workers with supervision
    try:
        await asyncio.gather(
            supervised_worker(
                "discovery",
                discovery_worker,
                config, gemini, discovery_notion, search_client,
            ),
            supervised_worker(
                "enrichment",
                enrichment_worker,
                config, gemini, notion_client, companies_db, campaigns_db, scraper,
            ),
            supervised_worker(
                "people",
                people_worker,
                config, gemini, people_notion,
                contact_finder, email_permutator, smtp_verifier,
            ),
            supervised_worker(
                "email_gen",
                email_gen_worker,
                config, gemini, notion_client, email_gen_dbs,
            ),
            supervised_worker(
                "email_sender",
                email_sender_worker,
                config, sender_notion,
            ),
        )
    except asyncio.CancelledError:
        pass

    logger.info("--- Avelero Clay Enrichment stopped ---")


if __name__ == "__main__":
    asyncio.run(main())

"""
Main orchestrator and entry point.

Loads config, creates asyncpg connection pool and DB instances,
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
from src.db.connection import get_pool, close_pool
from src.db.campaigns import CampaignsDB
from src.db.companies import CompaniesDB
from src.db.contacts import ContactsDB
from src.db.emails import EmailsDB
from src.db.contact_campaigns import ContactCampaignsDB
from src.search.brave_search import BraveSearchClient
from src.search.searxng import SearXNGClient
from src.search.scraper import WebScraper
from src.discovery.contact_finder import ContactFinder
from src.discovery.email_permutation import EmailPermutator
from src.discovery.smtp_verify import SMTPVerifier
from src.layers.discovery import (
    discovery_worker,
    DBClients as DiscoveryDBClients,
)
from src.layers.enrichment import enrichment_worker
from src.layers.people import (
    people_worker,
    DBClients as PeopleDBClients,
)
from src.layers.person_research import person_research_worker
from src.layers.campaign_scoring import campaign_scoring_worker
from src.layers.email_gen import email_gen_worker
from src.email.sender import email_sender_worker
from src.layers.dashboard_worker import dashboard_stats_worker

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
        "DATABASE_URL": config.database_url,
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
    logger.info("Database: %s", config.database_url[:30] + "...")
    logger.info("SearXNG URL: %s", config.searxng_url)
    logger.info("SMTP configured: %s (host=%s port=%d)",
                bool(config.smtp_host), config.smtp_host or "(none)", config.smtp_port)
    logger.info("Senders configured: %d (daily limit %d per sender)",
                len(config.senders), config.email_daily_limit)
    logger.info("Enrichment stale threshold: %d days", config.enrichment_stale_days)


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


async def main() -> None:
    """Main entry point. Initializes everything and launches workers."""
    global logger

    setup_logging()
    logger = get_logger("main")

    config = get_config()
    _validate_config(config)
    _log_startup_summary(config)

    # Rate limiter (shared across Gemini and search clients)
    rate_limiter = RateLimiter(DEFAULT_LIMITS)

    # Core clients
    gemini = GeminiClient(config, rate_limiter)
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

    # Create asyncpg connection pool and DB instances
    pool = await get_pool()
    logger.info("Postgres connection pool ready")

    campaigns_db = CampaignsDB(pool)
    companies_db = CompaniesDB(pool)
    contacts_db = ContactsDB(pool)
    emails_db = EmailsDB(pool)
    contact_campaigns_db = ContactCampaignsDB(pool)

    # Build per-worker DB client aggregates
    discovery_dbs = DiscoveryDBClients(
        campaigns=campaigns_db, companies=companies_db
    )
    people_dbs = PeopleDBClients(
        companies=companies_db, contacts=contacts_db
    )
    sender_dbs = SimpleNamespace(
        emails=emails_db,
        contacts=contacts_db,
        contact_campaigns=contact_campaigns_db,
    )

    # Install signal handlers
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop)

    workers = [
        ("discovery", discovery_worker,
         [config, gemini, discovery_dbs, search_client]),
        ("enrichment", enrichment_worker,
         [config, gemini, companies_db, campaigns_db, scraper,
          search_client]),
        ("people", people_worker,
         [config, gemini, people_dbs, contact_finder, email_permutator,
          smtp_verifier]),
        ("person_research", person_research_worker,
         [config, gemini, contacts_db, companies_db]),
        ("campaign_scoring", campaign_scoring_worker,
         [config, gemini, contacts_db, companies_db, campaigns_db,
          contact_campaigns_db]),
        ("email_gen", email_gen_worker,
         [config, gemini, campaigns_db, companies_db, contacts_db,
          emails_db, contact_campaigns_db]),
        ("email_sender", email_sender_worker, [config, sender_dbs]),
    ]
    logger.info("Launching %d workers", len(workers))

    try:
        await asyncio.gather(*(
            supervised_worker(name, fn, *args) for name, fn, args in workers
        ))
    except asyncio.CancelledError:
        pass

    # Cleanup
    await close_pool()
    logger.info("--- Avelero Clay Enrichment stopped ---")


if __name__ == "__main__":
    asyncio.run(main())

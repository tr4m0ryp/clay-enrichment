"""
Async connection pool management using asyncpg.

Provides a module-level singleton pool accessed via get_pool().
Call close_pool() during application shutdown to release connections.
"""

import logging

import asyncpg

from src.config import get_config

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """
    Return the shared asyncpg connection pool, creating it on first call.

    The pool connects using the database_url from Config. Pool size is
    bounded to min=1, max=5 connections.

    Returns:
        The shared asyncpg.Pool instance.

    Raises:
        ValueError: If database_url is not configured.
        Exception: Any connection error from asyncpg is propagated.
    """
    global _pool
    if _pool is None:
        cfg = get_config()
        if not cfg.database_url:
            raise ValueError(
                "DATABASE_URL is not set. Add it to your .env file."
            )
        _pool = await asyncpg.create_pool(
            dsn=cfg.database_url,
            min_size=1,
            max_size=5,
        )
        logger.info("asyncpg connection pool created")
    return _pool


async def close_pool() -> None:
    """
    Close the shared connection pool if it exists.

    Safe to call multiple times or when no pool has been created.
    """
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("asyncpg connection pool closed")

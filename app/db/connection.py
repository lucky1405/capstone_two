"""Asynchronous SQLite connection management using aiosqlite."""
import os
import aiosqlite
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from app.config import settings


def get_db_path() -> str:
    """Extracts or resolves the database file path from config."""
    db_url = settings.DATABASE_URL
    if db_url.startswith("sqlite+aiosqlite:///"):
        path = db_url.replace("sqlite+aiosqlite:///", "")
    elif db_url.startswith("sqlite:///"):
        path = db_url.replace("sqlite:///", "")
    else:
        path = settings.DB_PATH
    
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    return path


@asynccontextmanager
async def get_db_connection(db_path: str = None) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Yields a managed aiosqlite database connection configured with WAL and foreign keys."""
    resolved_path = db_path or get_db_path()
    conn = await aiosqlite.connect(resolved_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL;")
    await conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
    finally:
        await conn.close()

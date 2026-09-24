"""Test configuration, fixtures, and isolated SQLite test database."""
import os
import time
import hmac
import hashlib
import tempfile
import pytest
from httpx import AsyncClient, ASGITransport

from app.config import settings
from app.main import app
from app.db.migrations import init_db
from app.db.seed import seed_data


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def test_db():
    """Creates a temporary, isolated SQLite database for each test run."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    original_db = settings.DB_PATH
    original_url = settings.DATABASE_URL
    settings.DB_PATH = db_path
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"

    await init_db(db_path)
    await seed_data(db_path)

    yield db_path

    # Cleanup
    settings.DB_PATH = original_db
    settings.DATABASE_URL = original_url
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


@pytest.fixture
async def client(test_db):
    """Async test client bound to FastAPI application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def generate_stripe_signature(payload: bytes, secret: str = None) -> str:
    """Computes a valid Stripe-Signature header matching Stripe's HMAC-SHA256 scheme."""
    sec = secret or settings.STRIPE_WEBHOOK_SECRET
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.".encode("utf-8") + payload
    signature = hmac.new(sec.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"

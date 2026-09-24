"""FastAPI route dependencies for database connections and tenant resolution."""
from typing import AsyncGenerator, Optional
from fastapi import Header, Request
import aiosqlite

from app.db.connection import get_db_connection
from app.core.errors import TenantNotFoundException, BadRequestException


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Dependency providing a managed asynchronous SQLite database connection."""
    async with get_db_connection() as conn:
        yield conn


async def resolve_tenant_id(
    request: Request,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> str:
    """
    Resolves and verifies tenant identification from request headers.
    
    Order of resolution:
    1. Explicit 'X-Tenant-Id' header.
    2. Lookup via 'X-API-Key' in the database.
    3. Query parameter 'tenant_id'.
    4. Default fallback to 'tenant_free' for unauthenticated demo access.
    """
    async with get_db_connection() as conn:
        if x_tenant_id:
            cursor = await conn.execute("SELECT id FROM tenants WHERE id = ?", (x_tenant_id,))
            row = await cursor.fetchone()
            if not row:
                raise TenantNotFoundException(f"Tenant '{x_tenant_id}' not found.")
            return x_tenant_id

        if x_api_key:
            cursor = await conn.execute("SELECT id FROM tenants WHERE api_key = ?", (x_api_key,))
            row = await cursor.fetchone()
            if not row:
                raise TenantNotFoundException("Invalid API key.")
            return row["id"]

        # Check query parameter if present
        query_tenant = request.query_params.get("tenant_id")
        if query_tenant:
            cursor = await conn.execute("SELECT id FROM tenants WHERE id = ?", (query_tenant,))
            row = await cursor.fetchone()
            if not row:
                raise TenantNotFoundException(f"Tenant '{query_tenant}' not found.")
            return query_tenant

        # Default fallback tenant for demo simplicity
        cursor = await conn.execute("SELECT id FROM tenants WHERE id = 'tenant_free'")
        row = await cursor.fetchone()
        if row:
            return "tenant_free"

        raise BadRequestException("Missing authentication. Provide 'X-Tenant-Id' or 'X-API-Key'.")

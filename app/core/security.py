"""Security and Tenant identification helpers."""
import hashlib
from typing import Optional


def hash_api_key(api_key: str) -> str:
    """Computes a SHA-256 hash of an API key for safe storage."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def compute_request_hash(method: str, path: str, body: bytes) -> str:
    """Computes a cryptographic fingerprint of a request for idempotency verification."""
    hasher = hashlib.sha256()
    hasher.update(method.upper().encode("utf-8"))
    hasher.update(b":")
    hasher.update(path.encode("utf-8"))
    hasher.update(b":")
    hasher.update(body)
    return hasher.hexdigest()

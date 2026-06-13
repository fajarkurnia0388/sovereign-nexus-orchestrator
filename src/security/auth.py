"""
SNO Security — API Key Authentication  ✨ NEW ✨

Provides a simple shared-secret authentication layer for the MCP server.
Enable with: ENABLE_AUTH=true and SNO_API_KEY=<your-secret> in .env

The MCP client (e.g. Hermes Agent) must include:
    X-SNO-API-Key: <your-secret>
in every request header.

For production, upgrade to:
  - JWT tokens with expiry
  - Per-client scoped API keys stored in a database
  - OAuth2 / mTLS
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from src.utils.logger import get_logger

logger = get_logger("security.auth")

HEADER_NAME = "X-SNO-API-Key"


def constant_time_compare(a: str, b: str) -> bool:
    """
    Compare two strings in constant time to prevent timing attacks.
    Uses hmac.compare_digest on the SHA-256 hashes.
    """
    ha = hmac.new(b"sno-key-compare", a.encode(), hashlib.sha256).digest()
    hb = hmac.new(b"sno-key-compare", b.encode(), hashlib.sha256).digest()
    return hmac.compare_digest(ha, hb)


@dataclass
class AuthResult:
    allowed: bool
    reason: str = ""
    client_id: str = "anonymous"


@dataclass
class RateLimiter:
    """
    Token-bucket rate limiter per client IP / key hash.
    Limits: `max_calls` requests per `window_seconds`.
    """
    max_calls: int = 60
    window_seconds: float = 60.0
    _buckets: dict[str, list[float]] = field(default_factory=dict, init=False)

    def is_allowed(self, client_key: str) -> bool:
        now = time.monotonic()
        window_start = now - self.window_seconds
        bucket = self._buckets.setdefault(client_key, [])
        # Remove old entries
        self._buckets[client_key] = [t for t in bucket if t > window_start]
        if len(self._buckets[client_key]) >= self.max_calls:
            return False
        self._buckets[client_key].append(now)
        return True


class SNOAuthenticator:
    """
    Validates incoming API key headers against the configured secret.

    Usage:
        auth = SNOAuthenticator(api_key=settings.sno_api_key, enabled=settings.enable_auth)
        result = auth.authenticate(headers={"X-SNO-API-Key": "..."})
        if not result.allowed:
            raise PermissionError(result.reason)
    """

    def __init__(
        self,
        api_key: str,
        enabled: bool = True,
        rate_limit: RateLimiter | None = None,
    ):
        self._key = api_key
        self._enabled = enabled
        self._rate_limiter = rate_limit or RateLimiter()

        if enabled and not api_key:
            raise ValueError(
                "SNO Auth is enabled (ENABLE_AUTH=true) but SNO_API_KEY is empty. "
                "Set a strong secret in .env."
            )
        if not enabled:
            logger.warning(
                "⚠️  Authentication is DISABLED. "
                "Set ENABLE_AUTH=true and SNO_API_KEY=<secret> for production."
            )

    def authenticate(self, headers: dict[str, str]) -> AuthResult:
        """
        Validate the API key from headers.

        Args:
            headers: Dict of HTTP headers (case-insensitive lookup attempted).

        Returns:
            AuthResult with allowed=True/False and a reason string.
        """
        if not self._enabled:
            return AuthResult(allowed=True, reason="auth disabled", client_id="anonymous")

        # Case-insensitive header lookup
        provided = None
        for k, v in headers.items():
            if k.lower() == HEADER_NAME.lower():
                provided = v
                break

        if not provided:
            logger.warning(f"Request missing '{HEADER_NAME}' header")
            return AuthResult(allowed=False, reason=f"Missing {HEADER_NAME} header")

        if not constant_time_compare(provided, self._key):
            logger.warning("Request rejected: invalid API key")
            return AuthResult(allowed=False, reason="Invalid API key")

        # Rate limiting — key the bucket on the first 8 chars of the key hash
        client_id = hashlib.sha256(provided.encode()).hexdigest()[:8]
        if not self._rate_limiter.is_allowed(client_id):
            logger.warning(f"Rate limit exceeded for client {client_id}")
            return AuthResult(
                allowed=False,
                reason="Rate limit exceeded. Slow down.",
                client_id=client_id,
            )

        return AuthResult(allowed=True, client_id=client_id)

    @staticmethod
    def generate_key(length: int = 32) -> str:
        """Generate a cryptographically secure random API key."""
        return secrets.token_urlsafe(length)


class MCPAuthMiddleware:
    """
    ASGI/Starlette middleware to authenticate incoming MCP HTTP requests.
    Intercepts requests to HTTP endpoints and validates the API key.
    """
    def __init__(self, app: Any, authenticator: SNOAuthenticator):
        self.app = app
        self.authenticator = authenticator

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        # We only authenticate HTTP requests (not lifetime or websockets/stdio)
        if scope["type"] == "http":
            from starlette.requests import Request
            from starlette.responses import JSONResponse

            request = Request(scope, receive=receive)
            
            # Authenticate requests to the MCP endpoint or tools endpoints
            path = request.url.path
            if path.startswith("/mcp") or path.startswith("/sse") or path.startswith("/tools"):
                # Case-insensitive header dictionary conversion
                headers = {k.decode("utf-8"): v.decode("utf-8") for k, v in request.headers.raw}
                result = self.authenticator.authenticate(headers)
                if not result.allowed:
                    status_code = 429 if "Rate limit" in result.reason else 401
                    response = JSONResponse(
                        {"detail": f"Unauthorized: {result.reason}"},
                        status_code=status_code,
                    )
                    await response(scope, receive, send)
                    return

        # Proceed to the next ASGI handler
        await self.app(scope, receive, send)
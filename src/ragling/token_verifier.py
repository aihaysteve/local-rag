"""Token verifier for ragling SSE authentication."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from mcp.server.auth.provider import AccessToken, TokenVerifier

if TYPE_CHECKING:
    from ragling.config import Config

logger = logging.getLogger(__name__)

# Rate limiting constants
MAX_FAILURES = 5  # Rate limiting kicks in after this many failures
MAX_BACKOFF_SECONDS = 300  # Cap exponential backoff at 5 minutes
CLEANUP_INTERVAL_SECONDS = 600  # Run cleanup every 10 minutes
STALE_ENTRY_SECONDS = 600  # Remove entries whose next_allowed is 10+ min in the past


class RateLimitedError(Exception):
    """Raised when a token is rate-limited due to too many failed attempts."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Try again in {retry_after:.0f} seconds.")


class RaglingTokenVerifier(TokenVerifier):
    """Validates API keys against ragling config users.

    Maps each API key to a username via resolve_api_key(), then returns
    an AccessToken with client_id set to the username. Tool functions
    use get_access_token().client_id to look up user context.

    Includes exponential backoff rate limiting: after MAX_FAILURES failed
    attempts with the same token, subsequent attempts are rejected with
    RateLimitedError until the backoff period expires. Backoff doubles
    with each failure (2^count seconds), capped at MAX_BACKOFF_SECONDS.

    Args:
        config: Application config containing users with API keys.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        # {token: (failure_count, next_allowed_time)}
        self._failures: dict[str, tuple[int, float]] = {}
        self._last_cleanup: float = time.monotonic()

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a bearer token against configured API keys.

        Checks rate limiting before verifying. On failure, records the
        attempt for rate limiting. On success, clears any failure record.

        Args:
            token: The bearer token from the Authorization header.

        Returns:
            AccessToken with client_id=username if valid, None otherwise.

        Raises:
            RateLimitedError: If the token has exceeded the failure threshold
                and the backoff period has not yet elapsed.
        """
        self._maybe_cleanup()
        self._check_rate_limit(token)

        from ragling.auth import resolve_api_key

        user_ctx = resolve_api_key(token, self._config)
        if user_ctx is None:
            self._record_failure(token)
            return None

        # Successful auth: clear any failure record
        self._failures.pop(token, None)
        return AccessToken(
            token=token,
            client_id=user_ctx.username,
            scopes=[],
        )

    def _check_rate_limit(self, token: str) -> None:
        """Raise RateLimitedError if the token is currently rate-limited.

        A token is rate-limited when its failure count exceeds MAX_FAILURES
        and the current time is before next_allowed_time. Each rate-limited
        rejection also increments the failure count so the backoff grows.

        Args:
            token: The token to check.

        Raises:
            RateLimitedError: If the token is rate-limited.
        """
        if token not in self._failures:
            return
        count, next_allowed = self._failures[token]
        now = time.monotonic()
        if count > MAX_FAILURES and now < next_allowed:
            # Still increment so backoff keeps growing
            self._record_failure(token)
            _, new_next_allowed = self._failures[token]
            retry_after = new_next_allowed - now
            logger.warning(
                "Rate-limited token attempt (count=%d, retry_after=%.0fs)",
                count + 1,
                retry_after,
            )
            raise RateLimitedError(retry_after=retry_after)

    def _record_failure(self, token: str) -> None:
        """Record a failed authentication attempt.

        Increments the failure count and sets the next allowed time using
        exponential backoff: min(2^count, MAX_BACKOFF_SECONDS) seconds.

        Args:
            token: The token that failed authentication.
        """
        now = time.monotonic()
        if token in self._failures:
            count, _ = self._failures[token]
            count += 1
        else:
            count = 1
        backoff = min(2**count, MAX_BACKOFF_SECONDS)
        self._failures[token] = (count, now + backoff)

    def _maybe_cleanup(self) -> None:
        """Trigger cleanup if enough time has passed since the last one."""
        now = time.monotonic()
        if now - self._last_cleanup >= CLEANUP_INTERVAL_SECONDS:
            self._cleanup_stale_entries()

    def _cleanup_stale_entries(self) -> None:
        """Remove stale failure entries to prevent unbounded dict growth.

        Entries are removed if their next_allowed_time is more than
        STALE_ENTRY_SECONDS in the past.
        """
        now = time.monotonic()
        stale_keys = [
            key
            for key, (_, next_allowed) in self._failures.items()
            if now - next_allowed >= STALE_ENTRY_SECONDS
        ]
        for key in stale_keys:
            del self._failures[key]
        self._last_cleanup = now
        if stale_keys:
            logger.debug("Cleaned up %d stale rate-limit entries", len(stale_keys))

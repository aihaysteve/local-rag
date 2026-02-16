"""Token verifier for ragling SSE authentication."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.server.auth.provider import AccessToken, TokenVerifier

if TYPE_CHECKING:
    from ragling.config import Config


class RaglingTokenVerifier(TokenVerifier):
    """Validates API keys against ragling config users.

    Maps each API key to a username via resolve_api_key(), then returns
    an AccessToken with client_id set to the username. Tool functions
    use get_access_token().client_id to look up user context.

    Args:
        config: Application config containing users with API keys.
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a bearer token against configured API keys.

        Args:
            token: The bearer token from the Authorization header.

        Returns:
            AccessToken with client_id=username if valid, None otherwise.
        """
        from ragling.auth import resolve_api_key

        user_ctx = resolve_api_key(token, self._config)
        if user_ctx is None:
            return None
        return AccessToken(
            token=token,
            client_id=user_ctx.username,
            scopes=[],
        )

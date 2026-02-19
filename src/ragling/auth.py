"""Authentication and user context for ragling SSE transport."""

from dataclasses import dataclass, field

from ragling.config import Config


@dataclass
class UserContext:
    """Resolved user context from API key authentication."""

    username: str
    system_collections: list[str] = field(default_factory=list)
    path_mappings: dict[str, str] = field(default_factory=dict)

    def visible_collections(self, global_collection: str | None = None) -> list[str]:
        """Compute the list of collection names this user can search.

        Returns:
            List of collection names: user's own + global + system collections.
        """
        collections = [self.username]
        if global_collection:
            collections.append(global_collection)
        collections.extend(self.system_collections)
        return collections


def resolve_api_key(api_key: str, config: Config) -> UserContext | None:
    """Resolve an API key to a UserContext.

    Args:
        api_key: The API key from the request.
        config: Application configuration with users.

    Returns:
        UserContext if key matches, None otherwise.
    """
    if not api_key or not config.users:
        return None

    key_to_user = {uc.api_key: (uname, uc) for uname, uc in config.users.items()}
    match = key_to_user.get(api_key)
    if match is None:
        return None
    username, user_config = match
    return UserContext(
        username=username,
        system_collections=user_config.system_collections,
        path_mappings=user_config.path_mappings,
    )

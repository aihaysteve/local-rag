# Multi-Agent Setup

ragling supports SSE transport for scenarios where multiple users or AI agents share a single server. Each user gets scoped access to specific collections.

## Starting the SSE Server

SSE uses HTTPS with auto-generated self-signed certificates (stored in `~/.ragling/tls/`). TLS is mandatory because Bearer tokens must not travel in plaintext.

```bash
ragling serve --sse --no-stdio --port 10001
ragling serve --sse --port 10001 --config /path/to/config.json
```

Generate MCP client config (includes CA cert path):

```bash
ragling mcp-config --port 10001
```

## User Configuration

Each user gets an API key, collection visibility, and path mappings. Add users to your [config file](configuration.md):

```json
{
  "home": "~/agents/groups",
  "global_paths": ["~/agents/global"],
  "users": {
    "agent-1": {
      "api_key": "rag_your_generated_key",
      "system_collections": ["obsidian"],
      "path_mappings": {
        "~/agents/groups/agent-1/": "/workspace/group/",
        "~/agents/global/": "/workspace/global/"
      }
    }
  }
}
```

Generate API keys:

```bash
python3 -c "import secrets; print(f'rag_{secrets.token_hex(16)}')"
```

## Collection Scoping

Authenticated users see only:
- Their own collection (named after their username)
- The `global` collection (if `global_paths` are configured)
- System collections listed in their `system_collections` config

Queries against inaccessible collections return zero results.

## Path Mappings

Path mappings rewrite `source_path` and `source_uri` in search results so file paths make sense to the client. Keys are server-side prefixes (`~/` expanded); values are client-side replacements.

This is essential when the MCP server and client see different filesystem paths (e.g., Docker containers, remote agents).

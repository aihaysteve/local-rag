# NANOCLAW.md -- Ragling Setup Guide

You are guiding the user through installing and configuring ragling as the RAG
backend for NanoClaw. Ragling runs on the host machine; NanoClaw agents in
containers connect to it over SSE.

Follow these steps in order. At each step, verify the result before proceeding.
If something fails, help the user troubleshoot before continuing.

---

## Step 1: Check Prerequisites

Verify these are installed on the host machine:

### Homebrew

```bash
brew --version
```

If not installed: direct to https://brew.sh

### Ollama

```bash
ollama --version
```

If not installed:

```bash
brew install ollama
```

Verify it is running:

```bash
curl http://localhost:11434
# Should return: "Ollama is running"
```

If not running, start it:

```bash
ollama serve &
```

Or have the user launch Ollama.app, which starts the server automatically.

### bge-m3 embedding model

```bash
ollama list | grep bge-m3
```

If not present:

```bash
ollama pull bge-m3
```

### uv (Python package manager)

```bash
uv --version
```

If not installed:

```bash
brew install uv
```

---

## Step 2: Clone and Verify Ragling

```bash
git clone git@github.com:aihaysteve/local-rag.git ~/ragling
cd ~/ragling
uv run ragling --help
```

The first run takes a minute or two while uv creates the virtualenv and installs
all dependencies. Verify the help output shows `index`, `search`, `serve`,
`collections`, and `status` commands.

---

## Step 3: Configure Ragling for NanoClaw

Ask the user for:

- **NanoClaw groups directory** -- where each agent's workspace lives on the
  host (default: `~/NanoClaw/groups`)
- **Global shared documents directory** -- documents shared across all agents
  (default: `~/NanoClaw/global`)
- **System collections to expose** -- which of `obsidian`, `email`, `calibre`,
  `rss` they want agents to search (default: none)
- **SSE port** (default: `10001`)

### Generate a secure API key

For each agent that will connect, generate a key:

```bash
python3 -c "import secrets; print(f'rag_{secrets.token_hex(16)}')"
```

### Create the config file

Create `~/.ragling/config.json`:

```json
{
  "db_path": "~/.ragling/rag.db",
  "shared_db_path": "~/.ragling/doc_store.sqlite",
  "embedding_model": "bge-m3",
  "embedding_dimensions": 1024,

  "home": "~/NanoClaw/groups",
  "global_paths": ["~/NanoClaw/global"],

  "obsidian_vaults": ["~/Documents/MyVault"],
  "calibre_libraries": ["~/CalibreLibrary"],

  "users": {
    "AGENT_NAME": {
      "api_key": "rag_GENERATED_KEY",
      "system_collections": ["obsidian"],
      "path_mappings": {
        "~/NanoClaw/groups/AGENT_NAME/": "/workspace/group/",
        "~/NanoClaw/global/": "/workspace/global/"
      }
    }
  }
}
```

Adjust to match the user's actual setup:

- Replace `AGENT_NAME` with the real agent name (must match the directory name
  under `home`).
- Replace `rag_GENERATED_KEY` with the key generated above.
- Add one entry under `users` for each agent.
- Set `system_collections` to whichever system collections that agent should
  be able to search.
- `path_mappings` translate host paths to container paths so that search results
  returned to the agent reference paths the agent can actually access. The keys
  are host-side prefixes (with `~/` expanded at load time), and the values are
  the corresponding container-side paths.
- Remove `obsidian_vaults` and `calibre_libraries` if the user does not have
  those sources, or adjust the paths.

---

## Step 4: Start Ragling with SSE

```bash
cd ~/ragling
uv run ragling serve --sse --port 10001 --config ~/.ragling/config.json
```

Verify the server started:

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:10001/sse
```

Should return `200` (no auth configured) or `401` (auth required -- means
Bearer token validation is active, which is correct when `users` are configured).

### Serve command flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--sse` | off | Enable SSE transport (required for container access) |
| `--port PORT` | 10001 | Port for SSE transport |
| `--no-stdio` | off | Disable stdio transport (SSE only) |
| `-g GROUP` | `default` | Group name for per-group indexes |
| `-c PATH` | `~/.ragling/config.json` | Path to config file |
| `-v` | off | Enable debug logging |

For container-only use (no local Claude Desktop), add `--no-stdio`:

```bash
uv run ragling serve --sse --no-stdio --port 10001 -c ~/.ragling/config.json
```

### Optional: launchd Service for Persistence

To keep ragling running across reboots, create a launchd plist.

Create `~/Library/LaunchAgents/com.ragling.serve.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ragling.serve</string>

    <key>ProgramArguments</key>
    <array>
        <string>UV_PATH</string>
        <string>run</string>
        <string>--directory</string>
        <string>RAGLING_DIR</string>
        <string>ragling</string>
        <string>serve</string>
        <string>--sse</string>
        <string>--no-stdio</string>
        <string>--port</string>
        <string>10001</string>
        <string>--config</string>
        <string>CONFIG_PATH</string>
    </array>

    <key>WorkingDirectory</key>
    <string>RAGLING_DIR</string>

    <key>KeepAlive</key>
    <true/>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>LOG_DIR/ragling.out.log</string>

    <key>StandardErrorPath</key>
    <string>LOG_DIR/ragling.err.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

Replace the placeholders:

| Placeholder | Example value |
|-------------|---------------|
| `UV_PATH` | Full path to `uv` binary (run `which uv`) |
| `RAGLING_DIR` | `~/ragling` expanded (e.g., `/Users/steve/ragling`) |
| `CONFIG_PATH` | `~/.ragling/config.json` expanded |
| `LOG_DIR` | e.g., `/Users/steve/.ragling/logs` (create the directory first) |

Load and start:

```bash
mkdir -p ~/.ragling/logs
launchctl load ~/Library/LaunchAgents/com.ragling.serve.plist
```

Verify:

```bash
launchctl list | grep ragling
curl -s -o /dev/null -w "%{http_code}" http://localhost:10001/sse
```

To stop and unload:

```bash
launchctl unload ~/Library/LaunchAgents/com.ragling.serve.plist
```

---

## Step 5: Wire Up NanoClaw Containers

Each container needs these environment variables:

| Variable | Value |
|----------|-------|
| `RAG_URL` | `http://host.docker.internal:10001` (Docker) |
| `RAG_API_KEY` | The `rag_...` key from the agent's user config |

For Apple containers (Containerization framework), use the appropriate host
gateway instead of `host.docker.internal`. Check Apple's documentation for the
correct hostname -- it may be `host.containers.internal` or the host's IP.

The agent's MCP config inside the container should connect to ragling over SSE
with Bearer token authentication. Example MCP client config (container-side):

```json
{
  "mcpServers": {
    "ragling": {
      "url": "http://host.docker.internal:10001/sse",
      "headers": {
        "Authorization": "Bearer rag_GENERATED_KEY"
      }
    }
  }
}
```

The ragling server validates the Bearer token against the `users` entries in
`config.json`. On success, the agent can only search its own collection, the
global collection, and whichever `system_collections` are listed in its user
config. Search results have host paths rewritten to container paths via
`path_mappings`.

---

## Step 6: Index Initial Content

If you already have content in the groups and global directories:

```bash
cd ~/ragling
uv run ragling index all --config ~/.ragling/config.json
```

This indexes all configured sources: system collections (obsidian, email,
calibre, rss) plus any code groups. Startup sync also handles this
automatically -- when `ragling serve` starts, it discovers and indexes
new/changed files under `home` and `global_paths` in a background thread.

For manual indexing of specific sources:

```bash
# Index just obsidian
uv run ragling index obsidian -c ~/.ragling/config.json

# Index a specific code group
uv run ragling index group my-org -c ~/.ragling/config.json

# Index a project folder
uv run ragling index project "docs" ~/NanoClaw/global -c ~/.ragling/config.json
```

---

## Step 7: Test End-to-End

### Host-side test

```bash
uv run ragling search "test query" -c ~/.ragling/config.json
```

Should return results if content has been indexed. If no results, run
`uv run ragling status -c ~/.ragling/config.json` to check that collections
have documents.

### Container test

From inside a running container, or from the host simulating a container
request:

```bash
curl -H "Authorization: Bearer rag_GENERATED_KEY" http://host.docker.internal:10001/sse
```

A `200` response confirms the connection and authentication work. The agent's
MCP client will handle the SSE protocol from there.

### Verify path mappings

Run a search via the MCP tool (or curl) with the agent's API key. Check that
`source_path` values in the results use container paths (e.g.,
`/workspace/group/...`) rather than host paths (e.g.,
`/Users/steve/NanoClaw/groups/agent/...`).

---

## Troubleshooting

### Ollama not running

**Symptom**: `ragling search` or `ragling serve` fails with a connection error
mentioning localhost:11434.

**Fix**: Start Ollama:

```bash
ollama serve &
# or launch Ollama.app
```

Then verify:

```bash
curl http://localhost:11434
```

### SSE returns 401 Unauthorized

**Symptom**: Container gets 401 when connecting to ragling SSE endpoint.

**Cause**: The Bearer token does not match any API key in `config.json`.

**Fix**: Check that:

1. The `RAG_API_KEY` env var in the container matches the `api_key` value for
   that agent in `config.json` exactly.
2. The `Authorization` header is formatted as `Bearer rag_...` (with the
   `Bearer ` prefix).
3. You restarted `ragling serve` after changing `config.json`.

### Empty search results

**Symptom**: Search returns no results.

**Cause**: Content has not been indexed yet.

**Fix**:

```bash
uv run ragling status -c ~/.ragling/config.json
uv run ragling collections list -c ~/.ragling/config.json
```

If collections show zero chunks, run indexing:

```bash
uv run ragling index all -c ~/.ragling/config.json
```

For SSE users, remember that each agent can only see its own collection, the
global collection, and its `system_collections`. Verify the agent's user config
includes the collections you expect.

### Container cannot reach host

**Symptom**: Container gets "connection refused" or "host not found" when
connecting to ragling.

**Docker**: Use `http://host.docker.internal:10001`. This is a special DNS name
Docker provides to reach the host machine. Verify it resolves:

```bash
# Inside the container
curl http://host.docker.internal:10001/sse
```

**Apple containers**: The hostname for reaching the host may differ. Check
Apple's container documentation. You may need to use the host's actual IP
address on the bridge network.

**Firewall**: Ensure macOS firewall is not blocking the port. Check System
Settings > Network > Firewall.

### First run is slow

**Symptom**: `uv run ragling ...` takes a long time the first time.

**Cause**: uv is creating the virtualenv and installing dependencies (including
large packages like docling and transformers). Subsequent runs reuse the
cached venv and start quickly.

### Embedding model not found

**Symptom**: Error about model not found when indexing or searching.

**Fix**: Pull the model:

```bash
ollama pull bge-m3
```

Verify it is available:

```bash
ollama list | grep bge-m3
```

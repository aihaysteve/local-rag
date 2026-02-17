---
name: nanoclaw
description: Use when setting up ragling as the RAG backend for NanoClaw, configuring SSE transport for container agents, or wiring NanoClaw containers to the ragling server
---

# NanoClaw — Ragling Setup Guide

## Overview

Guide the user through installing and configuring ragling as the RAG backend for NanoClaw. Ragling runs on the host machine; NanoClaw agents in containers connect over SSE.

Follow the steps in order. Verify each step before proceeding. If something fails, troubleshoot before continuing.

## Step 1: Check Prerequisites

Verify on the host machine:

```bash
brew --version          # Homebrew
ollama --version        # Ollama
uv --version            # uv (Python package manager)
```

Install anything missing:
```bash
brew install ollama uv
```

Verify Ollama is running:
```bash
curl http://localhost:11434
# Should return: "Ollama is running"
```

Pull the embedding model:
```bash
ollama pull bge-m3
```

## Step 2: Clone and Verify Ragling

```bash
git clone git@github.com:aihaysteve/local-rag.git ~/ragling
cd ~/ragling
uv run ragling --help
```

First run takes a minute or two while uv creates the venv and installs dependencies. Verify help output shows `index`, `search`, `serve`, `collections`, and `status` commands.

## Step 3: Configure for NanoClaw

Ask the user for:
- **NanoClaw groups directory** — where each agent's workspace lives (default: `~/NanoClaw/groups`)
- **Global shared documents** — documents shared across all agents (default: `~/NanoClaw/global`)
- **System collections to expose** — which of `obsidian`, `email`, `calibre`, `rss` agents should search (default: none)
- **SSE port** (default: `10001`)

Generate a secure API key for each agent:
```bash
python3 -c "import secrets; print(f'rag_{secrets.token_hex(16)}')"
```

Create `~/.ragling/config.json`:

```json
{
  "db_path": "~/.ragling/rag.db",
  "shared_db_path": "~/.ragling/doc_store.sqlite",
  "embedding_model": "bge-m3",
  "embedding_dimensions": 1024,
  "home": "~/NanoClaw/groups",
  "global_paths": ["~/NanoClaw/global"],
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

Adjust for each agent:
- Replace `AGENT_NAME` with the real agent name (must match directory under `home`)
- Replace `rag_GENERATED_KEY` with the generated key
- One `users` entry per agent
- Set `system_collections` per agent
- `path_mappings` translate host → container paths

## Step 4: Start Ragling with SSE

```bash
cd ~/ragling
uv run ragling serve --sse --port 10001 --config ~/.ragling/config.json
```

SSE always uses HTTPS with auto-generated self-signed certificates (stored in `~/.ragling/tls/`). TLS is mandatory because SSE uses Bearer token authentication — tokens must not be transmitted in plaintext. Certs are created on first run.

Verify:
```bash
curl -sk -o /dev/null -w "%{http_code}" https://localhost:10001/sse
# 401 = auth active (correct when users configured)
```

The `-k` flag skips certificate verification for the self-signed cert. Containers will need the CA cert instead (see Step 5).

Generate MCP client config JSON:
```bash
uv run ragling mcp-config --port 10001
```

### Serve flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--sse` | off | Enable SSE transport (HTTPS) |
| `--port` | 10001 | SSE port |
| `--no-stdio` | off | Disable stdio (SSE only) |
| `-c PATH` | `~/.ragling/config.json` | Config file |
| `-v` | off | Debug logging |

For container-only use: `--sse --no-stdio`

### Optional: launchd for Persistence

See @launchd-setup.md for the full plist template and instructions.

## Step 5: Wire Up Containers

Each container needs:

| Variable | Value |
|----------|-------|
| `RAG_URL` | `https://host.docker.internal:10001` |
| `RAG_API_KEY` | The agent's `rag_...` key |

Mount the CA certificate so containers trust the self-signed TLS:
```bash
# Docker volume mount
-v ~/.ragling/tls/ca.pem:/etc/ragling/ca.pem:ro
```

Set the environment variable so the MCP client trusts it:
```bash
SSL_CERT_FILE=/etc/ragling/ca.pem
# or for Node.js clients:
NODE_EXTRA_CA_CERTS=/etc/ragling/ca.pem
```

Container-side MCP config:
```json
{
  "mcpServers": {
    "ragling": {
      "url": "https://host.docker.internal:10001/sse",
      "headers": {
        "Authorization": "Bearer rag_GENERATED_KEY"
      }
    }
  }
}
```

**Note:** The server cert SAN covers `localhost` and `127.0.0.1`. Containers connecting via `host.docker.internal` may need to set the CA cert as trusted (shown above) since the hostname won't match the SAN.

Ragling validates the Bearer token, scopes visibility to the agent's collection + global + system_collections, and rewrites host paths to container paths via `path_mappings`.

## Step 6: Index Initial Content

```bash
uv run ragling index all --config ~/.ragling/config.json
```

Startup sync also handles this automatically — `ragling serve` discovers and indexes new files under `home` and `global_paths` in a background thread.

## Step 7: Test End-to-End

Host-side:
```bash
uv run ragling search "test query" -c ~/.ragling/config.json
```

Simulated container request:
```bash
curl -sk -H "Authorization: Bearer rag_GENERATED_KEY" https://localhost:10001/sse
# 200 = connection and auth work
```

Verify path mappings: search results should show container paths (`/workspace/group/...`) not host paths.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Connection error on localhost:11434 | Ollama not running | `ollama serve &` or launch Ollama.app |
| SSE returns 401 | Bearer token mismatch | Check key matches config.json exactly; restart serve after config changes |
| Empty search results | Content not indexed | `uv run ragling index all -c ~/.ragling/config.json` |
| Container "connection refused" | Wrong hostname | Docker: use `host.docker.internal`; Apple containers: check docs for host gateway |
| TLS certificate error | CA not trusted | Mount `~/.ragling/tls/ca.pem` into container and set `SSL_CERT_FILE` |
| First run slow | uv installing deps | Normal — cached after first run |
| Model not found | bge-m3 not pulled | `ollama pull bge-m3` |

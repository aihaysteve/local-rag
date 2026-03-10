# Auth

## Purpose

API key resolution, TLS certificate management, and rate-limited token
verification for the MCP server transport layer.

## Core Mechanism

API key comparison uses `hmac.compare_digest` for timing-safety. Rate limiting
uses exponential backoff to prevent brute-force attempts without permanently
locking out users. TLS certificates are self-signed ECDSA P-256 with
auto-renewal.

TLS certificates use ECDSA P-256 and are auto-renewed on expiry. A near-expiry
warning is logged when certificates are within 30 days of expiration. Rate
limiter stale entries (tokens not seen recently) are cleaned every 10 minutes
to prevent memory growth.

**Key files:**
- `auth.py` -- API key resolution and user context
- `tls.py` -- self-signed certificate generation
- `token_verifier.py` -- rate-limited token verification

## Public Interface

| Export | Used By | Contract |
|---|---|---|
| `resolve_api_key(key, config)` | MCP server | Timing-safe key lookup; returns `UserContext` or `None` |
| `UserContext` | MCP server | Dataclass with username; `visible_collections()` computes access |
| `RaglingTokenVerifier` | MCP server | Rate-limited token verification with exponential backoff |
| `RateLimitedError` | MCP server | Raised when client exceeds failure threshold |
| `ensure_tls_certs(tls_dir?)` | CLI (serve) | Returns `TLSConfig` with (cert_path, key_path, ca_path); auto-renews on expiry |

## Invariants

| ID | Invariant | Why It Matters |
|---|---|---|
| INV-7 | `resolve_api_key()` uses `hmac.compare_digest` for all key comparisons | Prevents timing side-channel attacks on API keys |
| INV-12 | Token verifier rate-limits failed auth attempts with exponential backoff capped at 300 seconds | Prevents brute-force API key guessing without permanently locking out users |
| INV-13 | TLS certificates auto-renewed on expiry; near-expiry warning logged at 30-day threshold | Prevents silent certificate expiration that would break SSE transport |
| INV-14 | Rate limiter cleans stale entries every 10 minutes | Prevents unbounded memory growth from one-time failed authentication attempts |

## Failure Modes

| ID | Symptom | Cause | Fix |
|---|---|---|---|
| FAIL-7 | Rate limiter blocks legitimate user after failed attempts | More than MAX_FAILURES (5) consecutive failures with wrong key (triggers on 6th attempt, `count > 5`) | Wait for backoff to expire (max 300s); or restart the server to clear rate-limit state |

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| `config.py` (Config) | internal | `src/ragling/SPEC.md` |
| cryptography | external | N/A -- X.509 certificate generation |

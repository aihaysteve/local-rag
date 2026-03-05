# Auth

## Purpose

API key resolution, TLS certificate management, and rate-limited token
verification for the MCP server transport layer.

## Core Mechanism

API key comparison uses `hmac.compare_digest` for timing-safety. Rate limiting
uses exponential backoff to prevent brute-force attempts without permanently
locking out users. TLS certificates are self-signed ECDSA P-256 with
auto-renewal.

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

## Failure Modes

| ID | Symptom | Cause | Fix |
|---|---|---|---|
| FAIL-7 | Rate limiter blocks legitimate user after failed attempts | More than MAX_FAILURES (5) consecutive failures with wrong key (triggers on 6th attempt, `count > 5`) | Wait for backoff to expire (max 300s); or restart the server to clear rate-limit state |

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| `config.py` (Config) | internal | `src/ragling/SPEC.md` |
| cryptography | external | N/A -- X.509 certificate generation |

# Auth

## Purpose

API key resolution, TLS certificate management, and rate-limited token
verification for the MCP server transport layer.

## Core Mechanism

`auth.py` resolves API keys to `UserContext` using `hmac.compare_digest` for
timing-safe comparison. `UserContext` carries the username and
`visible_collections()` computes collection access based on user permissions.

`token_verifier.py` implements `RaglingTokenVerifier` with rate limiting via
exponential backoff (max 5 failures, max 300s backoff, cleanup every 10
minutes). Raises `RateLimitedError` when a client exceeds the failure
threshold.

`tls.py` generates self-signed ECDSA P-256 certificates (CA ~10 years, server
cert 1 year) with auto-renewal. `ensure_tls_certs()` returns a `TLSConfig`
with paths to all certificate and key files.

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

## Testing

```bash
uv run pytest tests/test_auth.py tests/test_tls.py tests/test_token_verifier.py -v
```

### Coverage

| Spec Item | Test | Description |
|---|---|---|
| INV-7 | -- | No direct test; `hmac.compare_digest` usage in `resolve_api_key()` untested |
| INV-12 | `test_token_verifier.py::TestRateLimiting::test_rate_limiting_kicks_in_after_threshold_failures` | Rejects immediately after MAX_FAILURES exceeded |
| INV-12 | `test_token_verifier.py::TestRateLimiting::test_backoff_time_increases_exponentially` | Backoff time doubles per failure |
| FAIL-7 | `test_token_verifier.py::TestRateLimiting::test_rate_limiting_kicks_in_after_threshold_failures` | Rate limiter blocks after threshold exceeded |

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| `config.py` (Config) | internal | `src/ragling/SPEC.md` |
| cryptography | external | N/A -- X.509 certificate generation |

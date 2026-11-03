# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-03

### Added
- `TeePay` (sync) and `AsyncTeePay` (async) clients for API version `2026-10-18`.
- `whoami()`, `capabilities()`.
- `collections`: `create`, `retrieve`, `list`, `list_all`.
- `checkout_sessions`: `create`, `retrieve`, `list`, `list_all`.
- `control_numbers`: `create`, `retrieve`, `list`, `list_all`.
- `disbursements`: `quote`, `create`, `retrieve`, `list`, `list_all`.
- Webhook verification (`verify_webhook`, `client.webhooks.verify`) with constant-time comparison and
  timestamp tolerance; `generate_test_headers` for tests.
- Automatic idempotency keys, safe retries with backoff and `Retry-After`, per-request timeouts.
- Typed errors including `AccountRestrictedError`; response metadata via `last_response`.

# Phalanx discovery — Juice Shop (llm)

- Target: `http://127.0.0.1:3000` — OWASP Juice Shop v17.3.0
- Mode: `llm` — app-agnostic wordlist `benchmarks/wordlists/common_paths.txt` + generic SQLi/XSS; no target-specific paths
- Official scoped challenges: **1/10** found
- Precision: 1.0 · Recall: 0.1 · F1: 0.1818
- Steps: 80 · URLs visited: 80

## Found (true positives)

- `exposedMetricsChallenge` — Exposed Metrics (Sensitive Data Exposure)

## Missed (false negatives)

- `adminSectionChallenge` — Admin Section (Broken Access Control) — Reach an administration surface without being an admin.
- `dbSchemaChallenge` — Database Schema (Injection) — Use UNION-based SQLi on product search to read the DB schema.
- `directoryListingChallenge` — Confidential Document (Sensitive Data Exposure) — Browse an exposed static directory listing and read a confidential file.
- `errorHandlingChallenge` — Error Handling (Security Misconfiguration) — Send malformed input to any endpoint; app returns an unhandled error page.
- `forgottenBackupChallenge` — Forgotten Sales Backup (Sensitive Data Exposure) — Download a backup/archive artifact left in a reachable directory.
- `localXssChallenge` — DOM XSS (XSS) — Inject a script via the search parameter that executes in the DOM.
- `loginAdminChallenge` — Login Admin (Injection) — SQL-injection auth bypass on the login endpoint.
- `restfulXssChallenge` — API-only XSS (XSS) — Persist an XSS payload through a REST endpoint.
- `scoreBoardChallenge` — Score Board (Miscellaneous) — Find the hidden score-board page.

## Unmapped findings (false positives)

_None._

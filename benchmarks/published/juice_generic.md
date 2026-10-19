# Phalanx discovery — Juice Shop (generic)

- Target: `http://127.0.0.1:3000`
- Mode: `generic` (generic probes; NOT RideLite regression seeds)
- In-scope GT bugs found: **6/8**
- Precision: 1.0 · Recall: 0.75 · F1: 0.8571
- Steps: 55 · URLs visited: 55

## True positives

- `authz:admin-config` — Unauthenticated admin application-configuration (adminSectionChallenge)
- `misconfig:backup-file` — Backup artifacts linked under /ftp (forgottenBackupChallenge)
- `misconfig:directory-listing` — FTP / confidential document directory listing (directoryListingChallenge)
- `misconfig:metrics` — Prometheus metrics endpoint exposed (n/a)
- `sqli:error-page` — SQL error page on product search (errorHandlingChallenge)
- `sqli:login` — SQL injection login bypass (admin token) (loginAdminChallenge)

## False negatives (missed)

- `authz:admin-section` — Administration section reachable
- `xss:dom-search` — DOM XSS via search (Angular)

## False positives (extra findings vs GT)

_None._

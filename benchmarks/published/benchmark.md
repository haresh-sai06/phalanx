# Phalanx benchmark

- Mode: `heuristic`
- Bugs found: **12/12**
- Precision: 1.0 · Recall: 1.0 · F1: 1.0
- Steps: 16 · URLs visited: 16

## True positives

- `404:/help` — Broken Help nav link returns 404 (medium/medium)
- `authz:admin-open` — Admin panel reachable without auth (critical/critical)
- `cookie:no-httponly` — debug_token cookie set without HttpOnly (medium/medium)
- `idor:api-ride` — Unauthenticated JSON IDOR on /api/rides/<id> (high/high)
- `idor:cancel` — Any user can cancel another user's ride (high/high)
- `idor:ride-detail` — IDOR: /rides/<id> has no ownership check (high/high)
- `idor:rides-list` — IDOR: /rides lists every user's rides (high/high)
- `open-redirect:profile` — Open redirect via /profile?next= (medium/medium)
- `secrets:plaintext-passwords` — Admin panel renders plaintext passwords (critical/critical)
- `sqli:search` — SQL-injection shaped 500 on /search (high/high)
- `validation:negative-tip` — Negative tip accepted, fare can go negative (medium/medium)
- `xss:estimate` — Reflected XSS on /estimate?q= (high/high)

## False negatives (missed)


## False positives

_None._

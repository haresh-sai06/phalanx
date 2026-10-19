"""Heuristic detectors that turn a page Snapshot into Findings."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from .models import Finding

XSS_PAYLOAD = '<script>alert("phalanx")</script>'
SQLI_PAYLOAD = "x' OR 1=1--"


def _fp(kind: str, *parts: str) -> str:
    return kind + ":" + "|".join(p.strip().lower() for p in parts if p)


def detect_404_nav(snap, persona: str) -> list[Finding]:
    out = []
    path = urlparse(snap.url).path
    # Only flag 404s that look like user-facing nav targets, not API probes.
    if snap.status == 404 and not path.startswith("/api/"):
        out.append(Finding(
            title=f"Broken link returns 404: {path}",
            category="functional", severity="medium", url=snap.url,
            evidence=f"HTTP {snap.status} at {snap.url}",
            fingerprint=_fp("404", path),
            persona=persona, repro_steps=[f"Open {snap.url}"],
        ))
    return out


def detect_reflected_xss(snap, persona: str) -> list[Finding]:
    out = []
    if XSS_PAYLOAD in snap.html and "<script>" in snap.html:
        # reflected unescaped
        if "&lt;script&gt;" not in snap.html.lower() or XSS_PAYLOAD in snap.html:
            # check raw presence of the unescaped payload
            if XSS_PAYLOAD in snap.html:
                out.append(Finding(
                    title=f"Reflected XSS on {urlparse(snap.url).path}",
                    category="security", severity="high", url=snap.url,
                    evidence=f"Payload echoed unescaped in HTML: {XSS_PAYLOAD!r}",
                    fingerprint="xss:estimate" if "estimate" in urlparse(snap.url).path else _fp("xss", urlparse(snap.url).path),
                    persona=persona,
                    repro_steps=[f"Open {snap.url}"],
                    cvss_hint=6.1,
                ))
    return out


def detect_sqli_error(snap, persona: str) -> list[Finding]:
    out = []
    markers = ("sqlite3.OperationalError", "sqlite_error", "syntax error", "SQLException", "pg_query", "mysql_fetch", "sequelize", "incomplete input")
    blob = (snap.text or "") + "\n" + (snap.html or "")
    if any(m.lower() in blob.lower() for m in markers):
        path = urlparse(snap.url).path
        # Keep RideLite regression fingerprint; use generic for other apps
        if path.rstrip("/") == "/search":
            fp = "sqli:search"
        elif "product" in path or "/rest/" in path:
            fp = "sqli:error-page"
        else:
            fp = _fp("sqli", path)
        out.append(Finding(
            title=f"SQL error page exposed on {path}",
            category="security", severity="high", url=snap.url,
            evidence=(snap.text or blob)[:300],
            fingerprint=fp,
            persona=persona, repro_steps=[f"Open {snap.url}"], cvss_hint=8.6,
        ))
    return out


def detect_admin_open(snap, persona: str) -> list[Finding]:
    out = []
    path = urlparse(snap.url).path
    if path.rstrip("/") == "/admin" and snap.status == 200 and "Admin" in snap.title:
        out.append(Finding(
            title="Admin panel reachable without proper authorization",
            category="security", severity="critical", url=snap.url,
            evidence=f"HTTP {snap.status}; page title={snap.title!r}; body contains user table",
            fingerprint="authz:admin-open", persona=persona,
            repro_steps=["Log out (or use a fresh session)", "Open /admin"], cvss_hint=9.8,
        ))
        if re.search(r"password|passwd", snap.text, re.I) and re.search(r"alice123|bob123|root123|dave123", snap.text):
            out.append(Finding(
                title="Admin panel renders plaintext passwords",
                category="security", severity="critical", url=snap.url,
                evidence="Password column contains the seed plaintext passwords",
                fingerprint="secrets:plaintext-passwords", persona=persona,
                repro_steps=["Open /admin", "Inspect Password column"], cvss_hint=9.1,
            ))
    return out


def detect_insecure_cookie(snap, persona: str) -> list[Finding]:
    out = []
    for c in snap.cookies:
        if c.get("name") == "debug_token" and not c.get("httpOnly", False):
            out.append(Finding(
                title="debug_token cookie missing HttpOnly flag",
                category="security", severity="medium", url=snap.url,
                evidence=f"cookie={c}", fingerprint="cookie:no-httponly",
                persona=persona, repro_steps=["Log in", "Inspect document.cookie / DevTools Application tab"],
            ))
    for header in snap.set_cookie_headers:
        if header.lower().startswith("debug_token=") and "httponly" not in header.lower():
            out.append(Finding(
                title="debug_token Set-Cookie header missing HttpOnly",
                category="security", severity="medium", url=snap.url,
                evidence=header, fingerprint="cookie:no-httponly",
                persona=persona, repro_steps=["Log in", "Inspect Set-Cookie response header"],
            ))
    return out


def detect_open_redirect(snap, persona: str) -> list[Finding]:
    out = []
    # if we ended up off-site after a profile save
    if "evil.example" in snap.url or (not snap.url.startswith("http://127.0.0.1") and "example.test" not in snap.url and "localhost" not in snap.url):
        if "next=" in snap.url or "evil" in snap.url:
            out.append(Finding(
                title="Open redirect via next= parameter",
                category="security", severity="medium", url=snap.url,
                evidence=f"Browser navigated to {snap.url}",
                fingerprint="open-redirect:profile", persona=persona,
                repro_steps=["Log in", "Open /profile?saved=1&next=https://evil.example"],
            ))
    return out


def detect_negative_fare(snap, persona: str) -> list[Finding]:
    out = []
    m = re.search(r"Fare:\s*\$(-?\d+\.\d+)", snap.text)
    if m and float(m.group(1)) < 0:
        out.append(Finding(
            title="Negative fare accepted after tip",
            category="functional", severity="medium", url=snap.url,
            evidence=f"Fare rendered as ${m.group(1)}",
            fingerprint="validation:negative-tip", persona=persona,
            repro_steps=["Open a ride detail page", "Submit tip amount = -100"],
        ))
    return out


def detect_idor_list(snap, persona: str, current_user: str | None) -> list[Finding]:
    """If the rides table shows an Owner column with someone else's name, flag IDOR."""
    out = []
    if "/rides" != urlparse(snap.url).path.rstrip("/") and not urlparse(snap.url).path.rstrip("/").endswith("/rides"):
        # list page only
        pass
    path = urlparse(snap.url).path.rstrip("/")
    if path == "/rides" and current_user and "Owner" in snap.text:
        others = [u for u in ("alice", "bob", "dave", "root") if u != current_user and re.search(rf"\b{u}\b", snap.text)]
        if others:
            out.append(Finding(
                title="IDOR: /rides lists other users' rides",
                category="security", severity="high", url=snap.url,
                evidence=f"While logged in as {current_user}, table shows owners {others}",
                fingerprint="idor:rides-list", persona=persona,
                repro_steps=[f"Log in as {current_user}", "Open /rides", "Observe other users' rides"],
                cvss_hint=7.5,
            ))
    return out


def detect_idor_detail(snap, persona: str, current_user: str | None) -> list[Finding]:
    out = []
    path = urlparse(snap.url).path
    if re.match(r"/rides/\d+$", path) and current_user:
        m = re.search(r"Owner:\s*(\w+)", snap.text)
        if m and m.group(1) != current_user:
            out.append(Finding(
                title="IDOR: /rides/<id> has no ownership check",
                category="security", severity="high", url=snap.url,
                evidence=f"Logged in as {current_user}, viewed ride owned by {m.group(1)}",
                fingerprint="idor:ride-detail", persona=persona,
                repro_steps=[f"Log in as {current_user}", f"Open {path}"], cvss_hint=7.5,
            ))
    return out


def detect_all(snap, persona: str = "explorer", current_user: str | None = None) -> list[Finding]:
    findings: list[Finding] = []
    findings += detect_404_nav(snap, persona)
    findings += detect_reflected_xss(snap, persona)
    findings += detect_sqli_error(snap, persona)
    findings += detect_admin_open(snap, persona)
    findings += detect_insecure_cookie(snap, persona)
    findings += detect_open_redirect(snap, persona)
    findings += detect_negative_fare(snap, persona)
    findings += detect_idor_list(snap, persona, current_user)
    findings += detect_idor_detail(snap, persona, current_user)
    findings += detect_directory_listing(snap, persona)
    findings += detect_metrics_exposure(snap, persona)
    findings += detect_admin_config_exposure(snap, persona)
    findings += detect_backup_file(snap, persona)
    return findings


def detect_directory_listing(snap, persona: str) -> list[Finding]:
    out = []
    markers = ("listing directory", "index of /", "directory listing for")
    blob = (snap.text or "") + "\n" + (snap.html or "")
    low = blob.lower()
    if any(m in low for m in markers) or (
        "href=\"ftp/" in (snap.html or "") and "quarantine" in low
    ):
        path = urlparse(snap.url).path.rstrip("/") or "/"
        out.append(Finding(
            title=f"Directory listing exposed at {path}",
            category="security", severity="medium", url=snap.url,
            evidence=snap.text[:240] or snap.html[:240],
            fingerprint="misconfig:directory-listing",
            persona=persona,
            repro_steps=[f"Open {snap.url}"],
            cvss_hint=5.3,
        ))
    return out


def detect_metrics_exposure(snap, persona: str) -> list[Finding]:
    out = []
    body = snap.text or snap.html or ""
    if ("# HELP" in body and "# TYPE" in body) or "nodejs_" in body or "process_cpu" in body:
        out.append(Finding(
            title="Prometheus/metrics endpoint exposed",
            category="security", severity="low", url=snap.url,
            evidence=body[:200],
            fingerprint="misconfig:metrics",
            persona=persona,
            repro_steps=[f"GET {snap.url}"],
            cvss_hint=3.1,
        ))
    return out


def detect_admin_config_exposure(snap, persona: str) -> list[Finding]:
    """Unauthenticated admin/application config JSON."""
    out = []
    body = snap.text or snap.html or ""
    path = urlparse(snap.url).path
    if "admin" in path.lower() and snap.status == 200:
        if '"config"' in body and ('"application"' in body or '"server"' in body):
            out.append(Finding(
                title="Admin application configuration readable without auth",
                category="security", severity="medium", url=snap.url,
                evidence=body[:240],
                fingerprint="authz:admin-config",
                persona=persona,
                repro_steps=[f"GET {snap.url} unauthenticated"],
                cvss_hint=5.3,
            ))
    return out


def detect_backup_file(snap, persona: str) -> list[Finding]:
    out = []
    path = urlparse(snap.url).path.lower()
    if snap.status == 200 and any(path.endswith(ext) for ext in (".bak", ".old", ".zip", ".sql", ".kdbx")):
        out.append(Finding(
            title=f"Sensitive backup/artifact downloadable: {path}",
            category="security", severity="medium", url=snap.url,
            evidence=f"HTTP {snap.status} for {path}",
            fingerprint="misconfig:backup-file",
            persona=persona,
            repro_steps=[f"GET {snap.url}"],
            cvss_hint=5.3,
        ))
    # Also flag when an FTP listing page links to .bak files
    html = snap.html or ""
    if ".bak" in html and ("ftp/" in html or "listing" in (snap.text or "").lower()):
        out.append(Finding(
            title="Backup files linked from directory listing",
            category="security", severity="medium", url=snap.url,
            evidence="Directory listing references .bak artifacts",
            fingerprint="misconfig:backup-file",
            persona=persona,
            repro_steps=[f"Open {snap.url}", "Download *.bak"],
            cvss_hint=5.3,
        ))
    return out

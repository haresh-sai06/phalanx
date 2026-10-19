"""Thin Playwright wrapper used by both the heuristic and LLM explorers."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Browser, Page, sync_playwright


@dataclass
class Snapshot:
    url: str
    title: str
    status: int | None
    text: str
    html: str
    links: list[str]
    forms: list[dict[str, Any]]
    cookies: list[dict[str, Any]]
    set_cookie_headers: list[str] = field(default_factory=list)


class BrowserSession:
    def __init__(self, base_url: str, headless: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.headless = headless
        self._pw = None
        self.browser: Browser | None = None
        self.page: Page | None = None
        self.last_status: int | None = None
        self.last_set_cookie: list[str] = []

    def __enter__(self) -> "BrowserSession":
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=self.headless)
        context = self.browser.new_context(ignore_https_errors=True)
        self.page = context.new_page()

        def on_response(resp):
            if resp.request.resource_type == "document":
                self.last_status = resp.status
                # capture raw Set-Cookie so we can check flags
                try:
                    headers = resp.headers_array()
                    self.last_set_cookie = [h["value"] for h in headers if h["name"].lower() == "set-cookie"]
                except Exception:
                    pass

        self.page.on("response", on_response)
        return self

    def __exit__(self, *exc) -> None:
        if self.browser:
            self.browser.close()
        if self._pw:
            self._pw.stop()

    def goto(self, path_or_url: str) -> Snapshot:
        assert self.page
        url = path_or_url if path_or_url.startswith("http") else urljoin(self.base_url + "/", path_or_url.lstrip("/"))
        self.last_status = None
        self.last_set_cookie = []
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=10_000)
        except Exception as exc:
            return Snapshot(url=url, title="", status=None, text=str(exc), html="", links=[], forms=[], cookies=[])
        return self.snapshot()

    def snapshot(self) -> Snapshot:
        assert self.page
        page = self.page
        html = page.content()
        text = page.inner_text("body") if page.query_selector("body") else ""
        links = []
        for a in page.query_selector_all("a[href]"):
            href = a.get_attribute("href") or ""
            abs_url = urljoin(page.url, href)
            if urlparse(abs_url).netloc == urlparse(self.base_url).netloc:
                links.append(abs_url)
        forms = []
        for form in page.query_selector_all("form"):
            action = form.get_attribute("action") or page.url
            method = (form.get_attribute("method") or "get").lower()
            fields = []
            for inp in form.query_selector_all("input, textarea, select"):
                fields.append({
                    "name": inp.get_attribute("name"),
                    "type": inp.get_attribute("type") or inp.evaluate("e => e.tagName.toLowerCase()"),
                    "value": inp.get_attribute("value") or "",
                })
            forms.append({"action": urljoin(page.url, action), "method": method, "fields": fields})
        cookies = page.context.cookies()
        return Snapshot(
            url=page.url, title=page.title(), status=self.last_status, text=text, html=html,
            links=sorted(set(links)), forms=forms, cookies=cookies,
            set_cookie_headers=list(self.last_set_cookie),
        )

    def fill_and_submit(self, form_index: int = 0, values: dict[str, str] | None = None) -> Snapshot:
        assert self.page
        forms = self.page.query_selector_all("form")
        if form_index >= len(forms):
            return self.snapshot()
        form = forms[form_index]
        values = values or {}
        for inp in form.query_selector_all("input, textarea"):
            name = inp.get_attribute("name")
            typ = (inp.get_attribute("type") or "text").lower()
            if not name or typ in ("hidden", "submit", "button"):
                continue
            if name in values:
                inp.fill(str(values[name]))
            elif typ == "password":
                inp.fill("alice123")
            elif typ == "number":
                inp.fill("1")
            else:
                inp.fill("Airport")
        # submit
        btn = form.query_selector("button[type=submit], button:not([type]), input[type=submit]")
        if btn:
            btn.click()
        else:
            form.evaluate("f => f.submit()")
        self.page.wait_for_load_state("domcontentloaded", timeout=10_000)
        return self.snapshot()

    def request_api(self, path: str) -> tuple[int, str]:
        """Unauthenticated (or current-cookie) HTTP GET via Playwright request context."""
        assert self.page
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        resp = self.page.context.request.get(url)
        return resp.status, resp.text()

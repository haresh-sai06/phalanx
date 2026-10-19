"""Thin Playwright wrapper used by both the heuristic and LLM explorers.

Navigation is flaky under concurrent redirects (login/logout, open-redirect
probes). Every public method retries on "Execution context was destroyed"
and re-acquires locators after each navigation — never reuse ElementHandles
across a goto/click that may navigate.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Browser, Error as PlaywrightError, Page, sync_playwright

_NAV_HINTS = (
    "execution context was destroyed",
    "navigation",
    "frame was detached",
    "target closed",
    "page crashed",
)


def _is_nav_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(h in msg for h in _NAV_HINTS)


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
        self.page.set_default_timeout(15_000)

        def on_response(resp):
            try:
                if resp.request.resource_type == "document":
                    self.last_status = resp.status
                    try:
                        headers = resp.headers_array()
                        self.last_set_cookie = [
                            h["value"] for h in headers if h["name"].lower() == "set-cookie"
                        ]
                    except Exception:
                        pass
            except Exception:
                pass

        self.page.on("response", on_response)
        return self

    def __exit__(self, *exc) -> None:
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass

    def _settle(self, timeout_ms: int = 8_000) -> None:
        assert self.page
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        try:
            # networkidle is ideal but SPAs never idle; use a short commit wait
            self.page.wait_for_load_state("load", timeout=min(timeout_ms, 3_000))
        except Exception:
            pass

    def goto(self, path_or_url: str, retries: int = 4) -> Snapshot:
        assert self.page
        url = (
            path_or_url
            if path_or_url.startswith("http")
            else urljoin(self.base_url + "/", path_or_url.lstrip("/"))
        )
        last_exc: BaseException | None = None
        for attempt in range(retries):
            self.last_status = None
            self.last_set_cookie = []
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                self._settle()
                return self.snapshot(retries=3)
            except PlaywrightError as exc:
                last_exc = exc
                if _is_nav_error(exc) and attempt < retries - 1:
                    self._settle()
                    time.sleep(0.15 * (attempt + 1))
                    continue
                if attempt < retries - 1:
                    time.sleep(0.15 * (attempt + 1))
                    continue
            except Exception as exc:
                last_exc = exc
                if _is_nav_error(exc) and attempt < retries - 1:
                    self._settle()
                    time.sleep(0.15 * (attempt + 1))
                    continue
                break
        return Snapshot(
            url=url,
            title="",
            status=None,
            text=str(last_exc) if last_exc else "goto failed",
            html="",
            links=[],
            forms=[],
            cookies=[],
        )

    def snapshot(self, retries: int = 3) -> Snapshot:
        assert self.page
        page = self.page
        last_exc: BaseException | None = None
        for attempt in range(retries):
            try:
                self._settle(timeout_ms=5_000)
                html = page.content()
                body = page.query_selector("body")
                text = body.inner_text() if body else ""
                links: list[str] = []
                for a in page.query_selector_all("a[href]"):
                    href = a.get_attribute("href") or ""
                    abs_url = urljoin(page.url, href)
                    if urlparse(abs_url).netloc == urlparse(self.base_url).netloc:
                        links.append(abs_url)
                forms: list[dict[str, Any]] = []
                for form in page.query_selector_all("form"):
                    action = form.get_attribute("action") or page.url
                    method = (form.get_attribute("method") or "get").lower()
                    fields = []
                    for inp in form.query_selector_all("input, textarea, select"):
                        fields.append({
                            "name": inp.get_attribute("name"),
                            "type": inp.get_attribute("type")
                            or inp.evaluate("e => e.tagName.toLowerCase()"),
                            "value": inp.get_attribute("value") or "",
                        })
                    forms.append({
                        "action": urljoin(page.url, action),
                        "method": method,
                        "fields": fields,
                    })
                cookies = page.context.cookies()
                return Snapshot(
                    url=page.url,
                    title=page.title(),
                    status=self.last_status,
                    text=text,
                    html=html,
                    links=sorted(set(links)),
                    forms=forms,
                    cookies=cookies,
                    set_cookie_headers=list(self.last_set_cookie),
                )
            except Exception as exc:
                last_exc = exc
                if _is_nav_error(exc) and attempt < retries - 1:
                    self._settle()
                    time.sleep(0.1 * (attempt + 1))
                    continue
                if attempt < retries - 1:
                    time.sleep(0.1 * (attempt + 1))
                    continue
        return Snapshot(
            url=page.url if page else "",
            title="",
            status=self.last_status,
            text=str(last_exc) if last_exc else "",
            html="",
            links=[],
            forms=[],
            cookies=[],
        )

    def fill_and_submit(
        self,
        form_index: int = 0,
        values: dict[str, str] | None = None,
        retries: int = 4,
    ) -> Snapshot:
        assert self.page
        values = values or {}
        last_exc: BaseException | None = None
        for attempt in range(retries):
            try:
                self._settle()
                forms = self.page.query_selector_all("form")
                if form_index >= len(forms):
                    return self.snapshot()
                form = forms[form_index]
                for inp in form.query_selector_all("input, textarea"):
                    name = inp.get_attribute("name")
                    typ = (inp.get_attribute("type") or "text").lower()
                    if not name or typ in ("hidden", "submit", "button"):
                        continue
                    if name in values:
                        inp.fill(str(values[name]))
                    elif typ == "password":
                        inp.fill(values.get("password", "alice123"))
                    elif typ == "number":
                        inp.fill(values.get(name, "1"))
                    else:
                        inp.fill(values.get(name, "Airport"))
                # Re-acquire submit control after fills (DOM may have shifted)
                forms = self.page.query_selector_all("form")
                if form_index >= len(forms):
                    return self.snapshot()
                form = forms[form_index]
                btn = form.query_selector(
                    "button[type=submit], button:not([type]), input[type=submit]"
                )
                if btn:
                    btn.click()
                else:
                    form.evaluate("f => f.submit()")
                self._settle(timeout_ms=10_000)
                return self.snapshot()
            except Exception as exc:
                last_exc = exc
                if _is_nav_error(exc) and attempt < retries - 1:
                    self._settle()
                    time.sleep(0.2 * (attempt + 1))
                    continue
                if attempt < retries - 1:
                    time.sleep(0.2 * (attempt + 1))
                    continue
        return Snapshot(
            url=self.page.url if self.page else "",
            title="",
            status=None,
            text=str(last_exc) if last_exc else "fill_and_submit failed",
            html="",
            links=[],
            forms=[],
            cookies=[],
        )

    def click_selector(self, selector: str, retries: int = 3) -> Snapshot:
        assert self.page
        for attempt in range(retries):
            try:
                self._settle()
                el = self.page.query_selector(selector)
                if not el:
                    return self.snapshot()
                el.click()
                self._settle(timeout_ms=10_000)
                return self.snapshot()
            except Exception as exc:
                if _is_nav_error(exc) and attempt < retries - 1:
                    self._settle()
                    time.sleep(0.15 * (attempt + 1))
                    continue
                if attempt < retries - 1:
                    continue
                return self.snapshot()
        return self.snapshot()

    def request_api(self, path: str) -> tuple[int, str]:
        """Unauthenticated (or current-cookie) HTTP GET via Playwright request context."""
        assert self.page
        url = path if path.startswith("http") else urljoin(self.base_url + "/", path.lstrip("/"))
        for attempt in range(3):
            try:
                resp = self.page.context.request.get(url, timeout=10_000)
                return resp.status, resp.text()
            except Exception:
                if attempt == 2:
                    return 0, ""
                time.sleep(0.2)
        return 0, ""

    def request_api_post(self, path: str, data: dict | str, as_json: bool = True) -> tuple[int, str]:
        assert self.page
        import json as _json
        url = path if path.startswith("http") else urljoin(self.base_url + "/", path.lstrip("/"))
        try:
            if as_json:
                payload = data if isinstance(data, str) else _json.dumps(data)
                resp = self.page.context.request.post(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=10_000,
                )
            else:
                resp = self.page.context.request.post(url, form=data, timeout=10_000)
            return resp.status, resp.text()
        except Exception as exc:
            return 0, str(exc)

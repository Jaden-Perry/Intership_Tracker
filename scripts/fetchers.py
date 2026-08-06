"""Fetchers that turn a firm's careers page into a list of candidate posting links.

Most firm career sites (Goldman's higher.gs.com, JPMorgan's Oracle Cloud portal,
Citi's TalentBrew front end, various tal.net/Oleeo student boards, etc.) are
JS-rendered single-page apps that return little to no useful markup on a plain
HTTP GET. So the default strategy renders the page in headless Chromium via
Playwright and scrapes the fully-rendered DOM. A small number of firms
(confirmed running Workday for their student board) get a faster, more
reliable direct-JSON-API path instead.
"""
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from classify import is_candidate

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

TIMEOUT = 30
PAGE_TIMEOUT_MS = 45_000


class FetchResult:
    def __init__(self, candidates, low_confidence=False, note=""):
        self.candidates = candidates  # list of {"title": str, "url": str}
        self.low_confidence = low_confidence
        self.note = note


def _extract_candidates_from_html(html: str, base_url: str) -> tuple[list[dict], int]:
    soup = BeautifulSoup(html, "html.parser")
    visible_text_len = len(soup.get_text(strip=True))

    candidates = []
    seen_urls = set()
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(separator=" ", strip=True).split())
        if not text or not is_candidate(text):
            continue
        href = urljoin(base_url, a["href"])
        href = href.split("#")[0]
        if href in seen_urls:
            continue
        seen_urls.add(href)
        candidates.append({"title": text, "url": href})

    return candidates, visible_text_len


_browser_ctx = {"playwright": None, "browser": None}


def _get_browser():
    if _browser_ctx["browser"] is None:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        _browser_ctx["playwright"] = pw
        _browser_ctx["browser"] = browser
    return _browser_ctx["browser"]


def close_browser():
    if _browser_ctx["browser"] is not None:
        _browser_ctx["browser"].close()
        _browser_ctx["playwright"].stop()
        _browser_ctx["browser"] = None
        _browser_ctx["playwright"] = None


def fetch_html(url: str) -> FetchResult:
    """Render the page with headless Chromium and scrape the resulting DOM."""
    browser = _get_browser()
    page = browser.new_page(user_agent=HEADERS["User-Agent"])
    try:
        page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass  # some sites never go idle (polling widgets); use what we have
        html = page.content()
        final_url = page.url
    finally:
        page.close()

    candidates, visible_text_len = _extract_candidates_from_html(html, final_url)
    low_confidence = visible_text_len < 500
    return FetchResult(candidates, low_confidence=low_confidence)


def _derive_workday_api(careers_url: str):
    """Given a standard Workday careers URL — either
    https://{tenant}.{host}/{locale}/{site}  or  https://{tenant}.{host}/{site}
    (some tenants omit the locale segment) — derive the CxS JSON API endpoint
    and the base URL job links are relative to.
    """
    parsed = urlparse(careers_url)
    host = parsed.netloc
    tenant = host.split(".")[0]
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) == 2:
        locale, site = parts
        job_base = f"https://{host}/{locale}/{site}"
    elif len(parts) == 1:
        site = parts[0]
        job_base = f"https://{host}/{site}"
    else:
        raise ValueError(f"Can't derive Workday site from URL: {careers_url}")
    api_url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    return api_url, job_base


def fetch_workday(careers_url: str, search_text: str = "", api_url: str = None, job_base: str = None) -> FetchResult:
    if not api_url or not job_base:
        derived_api, derived_base = _derive_workday_api(careers_url)
        api_url = api_url or derived_api
        job_base = job_base or derived_base

    candidates = []
    offset = 0
    limit = 20
    total = None
    while total is None or offset < min(total, 200):  # safety cap
        body = {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": search_text}
        resp = requests.post(api_url, headers={**HEADERS, "Content-Type": "application/json"}, json=body, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        total = data.get("total", 0)
        postings = data.get("jobPostings", [])
        if not postings:
            break
        for p in postings:
            title = p.get("title", "")
            path = p.get("externalPath", "")
            if not title or not path:
                continue
            candidates.append({"title": title, "url": job_base + path})
        offset += limit

    return FetchResult(candidates)


def fetch_greenhouse(board_token: str) -> FetchResult:
    resp = requests.get(
        f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs",
        headers=HEADERS, timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    candidates = [
        {"title": j["title"], "url": j["absolute_url"]}
        for j in data.get("jobs", [])
        if j.get("title") and j.get("absolute_url")
    ]
    return FetchResult(candidates)


def fetch_for_firm(fetch_cfg: dict) -> FetchResult:
    ftype = fetch_cfg.get("type", "html")
    if ftype == "workday_api":
        return fetch_workday(
            fetch_cfg["url"],
            search_text=fetch_cfg.get("search_text", ""),
            api_url=fetch_cfg.get("api_url"),
            job_base=fetch_cfg.get("job_base"),
        )
    if ftype == "greenhouse_api":
        return fetch_greenhouse(fetch_cfg["board_token"])
    return fetch_html(fetch_cfg["url"])

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


def _render_page(url: str):
    browser = _get_browser()
    page = browser.new_page(user_agent=HEADERS["User-Agent"])
    try:
        page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass  # some sites never go idle (polling widgets); use what we have
        # Lazy-loaded lists (e.g. Eightfold) only render more rows as you scroll.
        for _ in range(5):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(600)
        return page.content(), page.url
    finally:
        page.close()


def fetch_html(url: str, paginate: dict = None) -> FetchResult:
    """Render the page with headless Chromium and scrape the resulting DOM.

    paginate={"param": "p", "max_pages": 10} also reads ?p=2, ?p=3, ... until a
    page adds nothing new. Without it a paginated board is read only on page 1
    (Citi's board has 44 postings across 3 pages)."""
    html, final_url = _render_page(url)
    candidates, visible_text_len = _extract_candidates_from_html(html, final_url)
    low_confidence = visible_text_len < 500

    if paginate and not low_confidence:
        seen = {c["url"] for c in candidates}
        param = paginate.get("param", "p")
        for n in range(2, paginate.get("max_pages", 10) + 1):
            sep = "&" if "?" in url else "?"
            more_html, more_url = _render_page(f"{url}{sep}{param}={n}")
            more, _ = _extract_candidates_from_html(more_html, more_url)
            fresh = [c for c in more if c["url"] not in seen]
            if not fresh:
                break
            seen.update(c["url"] for c in fresh)
            candidates.extend(fresh)
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


def fetch_workday(
    careers_url: str,
    search_text: str = "",
    api_url: str = None,
    job_base: str = None,
    title_must_contain: str = None,
    search_texts: list = None,
) -> FetchResult:
    """title_must_contain is a client-side safety net for shared-tenant Workday
    boards (e.g. Greenhill postings living inside Mizuho's feed, PGIM inside
    Prudential's). Workday's own searchText is fuzzy/OR-matched, not a strict
    filter — it lets unrelated postings from the shared parent through — so
    for those cases we additionally require the firm's own name literally
    appear in the title before treating it as that firm's posting."""
    if not api_url or not job_base:
        derived_api, derived_base = _derive_workday_api(careers_url)
        api_url = api_url or derived_api
        job_base = job_base or derived_base

    # Big boards (e.g. Wells Fargo, 1,500+ jobs) can't be read in full within
    # the page cap, so a firm may list several search terms; results are unioned.
    candidates, seen_urls = [], set()
    for term in (search_texts or [search_text]):
        for c in _workday_search(api_url, job_base, term, title_must_contain):
            if c["url"] not in seen_urls:
                seen_urls.add(c["url"])
                candidates.append(c)
    return FetchResult(candidates)


def _workday_search(api_url, job_base, search_text, title_must_contain):
    candidates = []
    offset = 0
    limit = 20
    total = None  # locked from the first page only — Workday's "total" has been
    # observed to flake to 0 on a later page in the same pagination sequence,
    # which would otherwise silently truncate the results early.
    while total is None or offset < min(total, 600):  # safety cap
        body = {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": search_text}
        resp = requests.post(api_url, headers={**HEADERS, "Content-Type": "application/json"}, json=body, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        postings = data.get("jobPostings", [])

        if total is None:
            total = data.get("total", 0)
        elif not postings:
            # A later page came back empty even though we expected more —
            # could be a real end-of-results or a transient blip. Retry once
            # before trusting it and stopping.
            resp = requests.post(api_url, headers={**HEADERS, "Content-Type": "application/json"}, json=body, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            postings = data.get("jobPostings", [])

        if not postings:
            break
        for p in postings:
            title = p.get("title", "")
            path = p.get("externalPath", "")
            if not title or not path:
                continue
            if title_must_contain and title_must_contain.lower() not in title.lower():
                continue
            candidates.append({"title": title, "url": job_base + path, "location": p.get("locationsText", "")})
        offset += limit

    return candidates


def fetch_oracle_hcm(host: str, site: str, us_only: bool = True) -> FetchResult:
    """Oracle Recruiting Cloud (HCM) public job API, used by JPMorgan, Lazard and
    Jefferies. Unlike their marketing pages, it lists every real posting and
    isn't behind a bot check. us_only narrows the query to the United States
    facet so a 7,000-job board becomes ~5,000 and non-US roles never load."""
    base = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    headers = {**HEADERS, "Accept": "application/json"}

    def call(finder: str, expand: bool = True) -> dict:
        params = {"onlyData": "true", "finder": finder}
        if expand:
            params["expand"] = "requisitionList.secondaryLocations"
        r = requests.get(base, params=params, headers=headers, timeout=90)
        r.raise_for_status()
        return r.json()["items"][0]

    loc_filter = ""
    if us_only:
        facets = call(f"findReqs;siteNumber={site},limit=1,facetsList=LOCATIONS", expand=False).get("locationsFacet", [])
        us = next((f for f in facets if f.get("Name") == "United States"), None)
        if us:
            loc_filter = f",selectedLocationsFacet={us['Id']}"

    candidates, offset, total = [], 0, None
    while total is None or offset < total:
        item = call(f"findReqs;siteNumber={site}{loc_filter},limit=200,offset={offset},sortBy=POSTING_DATES_DESC")
        if total is None:
            total = item.get("TotalJobsCount", 0)
        rows = item.get("requisitionList", [])
        if not rows:
            break
        for q in rows:
            if q.get("Title") and q.get("Id"):
                candidates.append({
                    "title": q["Title"],
                    "url": f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{q['Id']}",
                    "location": q.get("PrimaryLocation", ""),
                })
        offset += 200
    return FetchResult(candidates)


def fetch_goldman() -> FetchResult:
    """Goldman's job site (higher.gs.com) is a bot-checked app that a headless
    browser only ever saw the first 20 results of. It's backed by a GraphQL
    API; experiences=["CAMPUS"] is the filter its Students board uses."""
    query = """query GetRoles($searchQueryInput: RoleSearchQueryInput!) {
      roleSearch(searchQueryInput: $searchQueryInput) {
        totalCount
        items { roleId jobTitle locations { city state country } }
      }
    }"""
    headers = {**HEADERS, "Origin": "https://higher.gs.com", "Referer": "https://higher.gs.com/"}
    candidates, page, total = [], 0, None
    while total is None or page * 100 < total:
        variables = {"searchQueryInput": {
            "page": {"pageSize": 100, "pageNumber": page},
            "sort": {"sortStrategy": "RELEVANCE", "sortOrder": "DESC"},
            "filters": [], "experiences": ["CAMPUS"], "searchTerm": "",
        }}
        r = requests.post("https://api-higher.gs.com/gateway/api/v1/graphql",
                          json={"query": query, "variables": variables}, headers=headers, timeout=60)
        r.raise_for_status()
        body = r.json()
        if body.get("errors") or not (body.get("data") or {}).get("roleSearch"):
            raise RuntimeError(f"Goldman GraphQL error: {str(body.get('errors'))[:200]}")
        rs = body["data"]["roleSearch"]
        if total is None:
            total = rs["totalCount"]
        if not rs["items"]:
            break
        for it in rs["items"]:
            loc = (it.get("locations") or [{}])[0]
            where = ", ".join(x for x in (loc.get("city"), loc.get("state"), loc.get("country")) if x)
            role_num = str(it["roleId"]).split("_")[0]
            candidates.append({"title": it["jobTitle"], "url": f"https://higher.gs.com/roles/{role_num}", "location": where})
        page += 1
    return FetchResult(candidates)


def fetch_bofa() -> FetchResult:
    """Bank of America's student job search shows 10 postings per page, but the
    campus-jobs API behind it returns the whole board (about 30) in one call."""
    r = requests.get(
        "https://careers.bankofamerica.com/services/campusjobssearchservlet",
        params={"start": 0, "rows": 1000, "search": "getAllJobs"},
        headers={**HEADERS, "Accept": "application/json"}, timeout=60,
    )
    r.raise_for_status()
    candidates = []
    for j in r.json().get("jobsList", []):
        if j.get("postingTitle") and j.get("jcrURL"):
            where = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
            candidates.append({"title": j["postingTitle"], "url": "https://careers.bankofamerica.com" + j["jcrURL"], "location": where})
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
            title_must_contain=fetch_cfg.get("title_must_contain"),
            search_texts=fetch_cfg.get("search_texts"),
        )
    if ftype == "oracle_hcm_api":
        return fetch_oracle_hcm(fetch_cfg["host"], fetch_cfg["site"], fetch_cfg.get("us_only", True))
    if ftype == "goldman_api":
        return fetch_goldman()
    if ftype == "bofa_api":
        return fetch_bofa()
    if ftype == "greenhouse_api":
        return fetch_greenhouse(fetch_cfg["board_token"])
    return fetch_html(fetch_cfg["url"], paginate=fetch_cfg.get("paginate"))

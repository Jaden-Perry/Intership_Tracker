"""Hourly job: check every tracked firm's careers page for new postings,
diff against the last known state, email alerts for anything new, and
regenerate the dashboard's data file.

Usage: python check_postings.py
Env vars (only required if there's something new to email about):
    RESEND_API_KEY, ALERT_EMAIL, ALERT_FROM_EMAIL (optional)
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from classify import classify, is_candidate
from emailer import send_alerts
from fetchers import fetch_for_firm, close_browser

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "firms.json"
TRACKED_PROGRAMS_PATH = ROOT / "config" / "tracked_programs.json"
STATE_PATH = ROOT / "data" / "state.json"
DASHBOARD_PATH = ROOT / "docs" / "dashboard.json"

STATUS_LABELS = {
    "open_now": "Open to me now",
    "not_yet_eligible": "Not yet eligible (junior seat)",
    "unknown": "Needs review",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def posting_id(firm_id: str, url: str) -> str:
    return hashlib.sha1(f"{firm_id}|{url}".encode()).hexdigest()[:16]


def load_json(path: Path, default):
    if not path.exists():
        return default
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
        f.write("\n")


def main():
    firms = load_json(CONFIG_PATH, [])
    tracked_programs = load_json(TRACKED_PROGRAMS_PATH, [])
    state = load_json(STATE_PATH, {"seen": {}})
    seen = state.setdefault("seen", {})

    run_time = now_iso()
    new_postings = []
    firm_status = []

    for firm in firms:
        firm_id, name, category = firm["id"], firm["name"], firm["category"]
        result = None
        error = None
        try:
            result = fetch_for_firm(firm["fetch"])
        except Exception as e:
            error = str(e)

        if error:
            firm_status.append({"firm": name, "status": "error", "detail": error, "checked_at": run_time})
            continue

        if result.low_confidence:
            firm_status.append({
                "firm": name, "status": "low_confidence",
                "detail": "Page returned little content — scrape may be incomplete; verify config/firms.json URL.",
                "checked_at": run_time,
            })
        else:
            firm_status.append({"firm": name, "status": "ok", "checked_at": run_time})

        current_ids = set()
        for cand in result.candidates:
            if not is_candidate(cand["title"]):
                continue  # e.g. unrelated full-time roles on a general job board
            pid = posting_id(firm_id, cand["url"])
            current_ids.add(pid)
            status = classify(cand["title"])

            existing = seen.get(pid)
            if existing is None:
                entry = {
                    "id": pid,
                    "firm": name,
                    "firm_id": firm_id,
                    "category": category,
                    "title": cand["title"],
                    "url": cand["url"],
                    "status": status,
                    "first_seen": run_time,
                    "last_seen": run_time,
                    "currently_listed": True,
                }
                seen[pid] = entry
                new_postings.append({**entry, "status_label": STATUS_LABELS.get(status, status)})
            else:
                existing["last_seen"] = run_time
                existing["currently_listed"] = True
                existing["status"] = status  # re-classify in case title text changed

        # Anything belonging to this firm not seen in this successful fetch is delisted.
        for pid, entry in seen.items():
            if entry["firm_id"] == firm_id and pid not in current_ids:
                entry["currently_listed"] = False

    close_browser()

    state["last_run"] = run_time
    state["firm_status"] = firm_status
    save_json(STATE_PATH, state)

    # Build dashboard buckets
    open_now = [e for e in seen.values() if e["currently_listed"] and e["status"] == "open_now"]
    not_yet_eligible = [e for e in seen.values() if e["currently_listed"] and e["status"] == "not_yet_eligible"]
    needs_review = [e for e in seen.values() if e["currently_listed"] and e["status"] == "unknown"]

    detected_program_keys = {(e["firm_id"]) for e in open_now}
    opens_soon = [
        p for p in tracked_programs
        if not any(e["firm_id"] == p["firm_id"] and p["program_keyword"].lower() in e["title"].lower() for e in open_now)
    ]

    for bucket in (open_now, not_yet_eligible, needs_review):
        bucket.sort(key=lambda e: e["first_seen"], reverse=True)

    dashboard = {
        "generated_at": run_time,
        "open_now": open_now,
        "opens_soon": opens_soon,
        "not_yet_eligible": not_yet_eligible,
        "needs_review": needs_review,
        "firm_status": firm_status,
    }
    save_json(DASHBOARD_PATH, dashboard)

    if new_postings:
        for p in new_postings:
            p["status_label"] = STATUS_LABELS.get(p["status"], p["status"])
        send_alerts(new_postings)
        print(f"Sent alert for {len(new_postings)} new posting(s).")
    else:
        print("No new postings.")

    error_firms = [f for f in firm_status if f["status"] == "error"]
    if error_firms:
        print(f"WARNING: {len(error_firms)} firm(s) failed to fetch:", file=sys.stderr)
        for f in error_firms:
            print(f"  - {f['firm']}: {f['detail']}", file=sys.stderr)


if __name__ == "__main__":
    main()

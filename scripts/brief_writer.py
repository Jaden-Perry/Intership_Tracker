"""Turn raw market data + headlines into an interview-ready HTML brief via Claude."""
from __future__ import annotations

import html as html_lib
import os
import re

import requests

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-5"


def _strip_code_fence(text: str) -> str:
    """Strip a leading/trailing ``` or ```html fence, if the model added one
    despite being told not to.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: -3]
    return text.strip()


def _format_market_line(m: dict) -> str:
    if m.get("unavailable"):
        return (
            f"- {m['label']}: DATA UNAVAILABLE this run (the feed only had stale "
            f"data). Do not state any level or % move for it; say it's "
            f"unavailable if you mention it at all."
        )
    if m.get("change_bps") is not None:
        return (
            f"- {m['label']}: {m['price']:.3f}% "
            f"({m['change_bps']:+.1f} bps vs. previous close)"
        )
    line = f"- {m['label']}: {m['price']:.2f}"
    if m["pct_change"] is not None:
        line += f" ({m['pct_change']:+.2f}% vs. previous close)"
    return line


def _source_blocks(market_data: list[dict], headlines: list[dict]) -> tuple[str, str]:
    """The exact source material the writer sees; the fact-checker gets the
    same blocks so it checks the draft against what the writer actually had.
    """
    market_lines = "\n".join(_format_market_line(m) for m in market_data) or (
        "(no market data available this run)"
    )
    headline_lines = "\n".join(
        f"- ({h['published']}) [{h['source']}] {h['title']} — {h['summary']}"
        for h in headlines
    ) or "(no headlines available this run)"
    return market_lines, headline_lines


def _call_claude(system: str, user: str) -> tuple[str, str]:
    """One Messages API call. Returns (text, stop_reason); raises on API failure."""
    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 8000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=180,
    )
    if not resp.ok:
        print(f"Anthropic API error {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    data = resp.json()
    for block in data["content"]:
        if block.get("type") == "text":
            return _strip_code_fence(block["text"]), data.get("stop_reason", "")
    raise RuntimeError(f"No text content block in Anthropic response: {data}")


def _mechanical_mismatches(draft: str, market_data: list[dict]) -> list[str]:
    """Deterministic check that the snapshot's numbers match the data we
    fetched. Lenient on formatting (commas, $, rounding), so a hit means a
    figure is actually missing or different, not just styled differently.
    """
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", draft))
    text = text.replace(",", "").replace("\u2212", "-")
    bad = []
    for m in market_data:
        if m.get("unavailable"):
            continue
        price_ok = any(f"{m['price']:.{d}f}" in text for d in (2, 3))
        if m.get("change_bps") is not None:
            bps = m["change_bps"]
            move_ok = (
                f"{bps:+.1f}" in text
                or f"{abs(bps):.1f}" in text
                or f"{abs(round(bps))} bp" in text
            )
            want = f"{bps:+.1f} bps"
        elif m.get("pct_change") is not None:
            move_ok = f"{m['pct_change']:+.2f}" in text
            want = f"{m['pct_change']:+.2f}%"
        else:
            continue
        if not (price_ok and move_ok):
            bad.append(f"{m['label']}: expected level {m['price']:.2f} and move {want}")
    return bad


def generate_brief_html(
    run_type: str,
    date_str: str,
    session_date_str: str,
    market_data: list[dict],
    headlines: list[dict],
    recruiting_context: str,
) -> str:
    """Calls the Anthropic API and returns an HTML email-body fragment.

    Raises on API failure so the workflow run shows as failed rather than
    silently sending nothing.
    """
    market_lines, headline_lines = _source_blocks(market_data, headlines)

    session_label = (
        f"the {session_date_str} session (the most recently completed one, "
        f"heading into today)"
        if run_type == "morning"
        else f"today's ({session_date_str}) trading session"
    )

    system_prompt = f"""You are writing a short daily markets brief for a college finance \
student who is recruiting for investment banking, private equity, and wealth management \
internships. They are specifically targeting: {recruiting_context}.

The single most common interview question they need to be ready for is some version of \
"walk me through the markets" or "what's going on in markets right now" — this brief exists \
to make them sound sharp and specific when asked that question, not to recap headlines like \
a generic financial newsletter (Morning Brew, Market Brew, etc.). Assume the reader already \
knows basic finance but wants jargon explained the moment it's used, and wants to know WHY \
things moved, not just that they moved.

The headlines below each carry a UTC publish timestamp and are sorted newest first. RSS \
feeds often keep older speculative headlines (e.g. "Fed expected to hike," "markets pricing \
in a possible hike") sitting alongside newer ones reporting the confirmed outcome (e.g. "Fed \
hikes rates," "Fed's rate-hike lead"). When headlines conflict like this, the newer, \
outcome-confirming headline is ground truth — never describe something as still pending, \
possible, or "priced in" if a more recent headline reports it has actually happened. This \
applies everywhere in the brief, not just the headline section: if a Fed decision, earnings \
report, or other event has already occurred per the newest headlines, the talking point and \
market-snapshot interpretation must treat it as fact, not speculation.

Write clean HTML for an email — a self-contained fragment, no <html>/<head>/<body> tags — \
using ONLY inline styles (email clients strip <style> blocks). Cover, in this order:

1. A 2-3 sentence "if asked about markets today" talking point, written the way they'd \
   actually say it out loud in an interview: confident, specific, plain-English.
2. A compact market snapshot table or list using the data below, but interpreted — don't \
   just restate the numbers, say what the move means and, where the headlines support it, \
   why it happened. If the headlines don't explain a move, say the move looks technical or \
   unclear rather than inventing a reason. If you color-code the % change figures, the color \
   must reflect ONLY the number's arithmetic sign — green for positive, red for negative — \
   never whether the move is "good" or "bad" news for markets. A rising VIX or rising yield \
   is still a positive percentage and must be green; do not recolor it red because rising \
   volatility or rates reads as bad news. Quote Treasury yield moves in basis points (bps) \
   exactly as given in the data, never as a percentage change of the yield (e.g. "10-year \
   down 2 bps", not "-0.4%"); the same sign-based green/red rule applies to the bps figure. \
   The market data below is as of the close of the \
   {session_date_str} session — label the snapshot section with that date explicitly (e.g. \
   "Snapshot — {session_date_str} close") so it's never mistaken for live, same-moment data. \
   {"This is a morning run sent before today's open, so this is yesterday's/the last completed session's numbers, not anything that's happened yet today." if run_type == "morning" else "This is an evening run sent after today's close, so this is today's full-session move."}
3. 3-5 stories from the headlines below that actually matter for {session_label}, grouped \
   by theme. For each: what happened, why it matters, and one line tying it to a specific \
   sector or to deal activity (M&A, IPOs, credit markets, buybacks, financing) relevant to \
   the firms this reader is targeting. Skip filler stories.
4. A "Jargon of the day" callout box: pick ONE term that appears naturally in today's news \
   (e.g. basis points, yield curve inversion, spread, duration, dry powder, mark-to-market, \
   repo market) and explain it in 2-3 plain-English sentences with a concrete example drawn \
   from today's actual data.

Facts you may state are limited to what the data below explicitly says. In particular: only \
say what a central bank decided (hiked, cut, held) if a source line states that outcome; if a \
source only says a statement or decision was issued with no content, say the decision text \
wasn't available instead of guessing, and never infer a rate move from market-pricing \
headlines or from earlier meetings. Only attribute a market move to a cause that a headline \
actually supports, and when several drivers appear in the headlines, lead with the biggest \
one (e.g. a mega-cap falling double digits) rather than a smaller one. Economic-data claims \
(GDP, inflation, jobs) must match the figures and direction in the headlines: never say \
"accelerated" or "cooled" unless a source says so.

Keep the whole thing skimmable in under 3 minutes — noticeably shorter and more pointed than \
a general-audience newsletter. Use inline CSS for a clean, readable look: system font stack, \
generous line-height, subtle section dividers, a distinct background color for the jargon \
callout. Do not fabricate facts not supported by the data provided."""

    user_prompt = f"""Date: {date_str}
Run: {run_type}

MARKET DATA:
{market_lines}

HEADLINES:
{headline_lines}
"""

    draft, stop_reason = _call_claude(system_prompt, user_prompt)
    if stop_reason == "max_tokens":
        print("brief_writer: WARNING writer hit max_tokens; draft may be truncated")
    return draft


AUDIT_SYSTEM = """You are the fact-checking editor for a daily markets brief that a finance \
student reads to prepare for interviews. A wrong claim repeated in an interview costs them \
credibility, so accuracy matters more than polish.

You get (1) a DRAFT brief in HTML and (2) the ONLY source material the writer had: market data \
and timestamped headlines (some carrying official text). Check every factual claim in the \
draft against that source material: who did what (including central-bank decisions: hike, \
cut, hold, and vote outcomes), earnings and M&A facts, economic-data figures and their \
direction, every number, dates, and every stated cause for a market move.

A claim passes only if the sources directly support it. It is a problem if it is contradicted \
by a source; absent from the sources (including claims that sound plausible or that you \
believe are true from memory: the sources are the standard, not your memory); overstated \
beyond what a source says; or attributes a move to a cause the sources do not support. Also \
flag it when a bigger driver named in the headlines is omitted and a smaller one is presented \
as the cause.

Strict rules:
- Central-bank rate decisions and vote outcomes must be explicitly stated in a source line. \
If a source only says a statement was issued, the draft may not say what was decided.
- Snapshot figures must match the MARKET DATA exactly. If a MECHANICAL CHECK note lists a \
mismatch, correct the draft to the data value.
- If a ticker is marked DATA UNAVAILABLE, the draft must not state numbers for it.
- Direction words must match the numbers (up/down, higher/lower), and green/red coloring must \
follow the number's sign only.

Fix each problem with the minimal edit that makes the sentence true and supported: correct it, \
soften it to what the sources actually say, or remove it, and rewrite any sentence that \
depended on it. Keep the original structure, voice, styling and length. Do not add new facts \
or opinions. If nothing is wrong, return the draft unchanged.

Output format, exactly:
ISSUES:
- <what the draft claimed -> what the sources say / why unsupported -> what you changed>
(or the single line "ISSUES: none")
===HTML===
<the full corrected HTML fragment>"""


def _parse_audit(text: str) -> tuple[list[str], str] | None:
    if "===HTML===" not in text:
        return None
    head, corrected = text.split("===HTML===", 1)
    issues = []
    for line in head.splitlines():
        line = line.strip()
        if line.upper().startswith("ISSUES:"):
            line = line.split(":", 1)[1].strip()
        line = line.lstrip("-* ").strip()
        if line and line.lower().rstrip(".") != "none":
            issues.append(line)
    return issues, _strip_code_fence(corrected)


def _with_footer(draft: str, issues: list[str], unresolved: list[str]) -> str:
    if not issues and not unresolved:
        return draft
    items = [html_lib.escape(i[:220]) for i in issues[:5]]
    items += [html_lib.escape(f"Figure could not be matched to the data: {u}") for u in unresolved]
    lis = "".join(f"<li>{i}</li>" for i in items)
    return draft + (
        '<div style="margin-top:24px;padding:10px 14px;border-left:3px solid #8b94a3;'
        'font-size:12px;line-height:1.5;color:#8b94a3;">'
        f"Fact-check: {len(issues)} claim(s) corrected before sending."
        f'<ul style="margin:6px 0 0 18px;padding:0;">{lis}</ul></div>'
    )


def _unverified_banner(reason: str, mismatches: list[str]) -> str:
    extra = ""
    if mismatches:
        extra = " Snapshot figures that did not match the data: " + html_lib.escape("; ".join(mismatches)) + "."
    return (
        '<div style="margin-bottom:16px;padding:10px 14px;border:1px solid #e0b13b;'
        'border-radius:6px;font-size:13px;line-height:1.5;color:#e0b13b;">'
        "Warning: this brief was NOT fact-checked this run (the audit step failed: "
        f"{html_lib.escape(reason[:160])}). Verify specific claims, especially central-bank "
        f"decisions and earnings results, before repeating them.{extra}</div>"
    )


def audit_brief_html(
    draft: str,
    run_type: str,
    session_date_str: str,
    market_data: list[dict],
    headlines: list[dict],
) -> tuple[str, list[str]]:
    """Second-pass fact-check of the draft against only the sources the
    writer had. Returns (html_to_send, issues). Never raises: if the audit
    can't complete, the draft is sent with a visible "not fact-checked"
    warning rather than silently passing as verified.
    """
    market_lines, headline_lines = _source_blocks(market_data, headlines)
    mismatches = _mechanical_mismatches(draft, market_data)
    mech = (
        "Mismatches found:\n" + "\n".join(f"- {m}" for m in mismatches)
        if mismatches
        else "All snapshot figures matched the data."
    )
    user_prompt = f"""Run: {run_type}; market data is as of the close of {session_date_str}.

MARKET DATA:
{market_lines}

HEADLINES:
{headline_lines}

MECHANICAL CHECK (deterministic comparison of the draft's figures against MARKET DATA):
{mech}

DRAFT:
{draft}
"""
    last_err = "unknown error"
    for attempt in (1, 2):
        try:
            text, stop_reason = _call_claude(AUDIT_SYSTEM, user_prompt)
            if stop_reason == "max_tokens":
                raise RuntimeError("audit output truncated (max_tokens)")
            parsed = _parse_audit(text)
            if parsed is None:
                raise RuntimeError("audit output missing the ===HTML=== section")
            issues, fixed = parsed
            if "<" not in fixed or len(fixed) < 0.5 * len(draft):
                raise RuntimeError("audit returned implausibly short HTML")
            unresolved = _mechanical_mismatches(fixed, market_data)
            return _with_footer(fixed, issues, unresolved), issues + [
                f"UNRESOLVED figure mismatch: {u}" for u in unresolved
            ]
        except Exception as e:
            last_err = str(e)
            print(f"brief_writer: audit attempt {attempt} failed: {last_err}")
    return _unverified_banner(last_err, mismatches) + draft, [f"AUDIT FAILED: {last_err}"]


def coverage_footer(problems: list[str]) -> str:
    """Tell the reader when a news source was down, so a thin brief isn't
    mistaken for a quiet news day.
    """
    if not problems:
        return ""
    listed = html_lib.escape("; ".join(problems))
    return (
        '<div style="margin-top:16px;padding:8px 14px;border-left:3px solid #e0b13b;'
        'font-size:12px;line-height:1.5;color:#8b94a3;">'
        f"Source coverage was reduced this run ({listed}); this brief may be missing news "
        "those sources would have carried.</div>"
    )

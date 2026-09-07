"""Turn raw market data + headlines into an interview-ready HTML brief via Claude."""
import os
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
    line = f"- {m['label']}: {m['price']:.2f}"
    if m["pct_change"] is not None:
        line += f" ({m['pct_change']:+.2f}% vs. previous close)"
    return line


def generate_brief_html(
    run_type: str,
    date_str: str,
    market_data: list[dict],
    headlines: list[dict],
    recruiting_context: str,
) -> str:
    """Calls the Anthropic API and returns an HTML email-body fragment.

    Raises on API failure so the workflow run shows as failed rather than
    silently sending nothing.
    """
    api_key = os.environ["ANTHROPIC_API_KEY"]

    market_lines = "\n".join(_format_market_line(m) for m in market_data) or (
        "(no market data available this run)"
    )
    headline_lines = "\n".join(
        f"- [{h['source']}] {h['title']} — {h['summary']}" for h in headlines
    ) or "(no headlines available this run)"

    session_label = (
        "overnight/pre-market moves heading into today's session"
        if run_type == "morning"
        else "today's trading session"
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

Write clean HTML for an email — a self-contained fragment, no <html>/<head>/<body> tags — \
using ONLY inline styles (email clients strip <style> blocks). Cover, in this order:

1. A 2-3 sentence "if asked about markets today" talking point, written the way they'd \
   actually say it out loud in an interview: confident, specific, plain-English.
2. A compact market snapshot table or list using the data below, but interpreted — don't \
   just restate the numbers, say what the move means and, where the headlines support it, \
   why it happened. If the headlines don't explain a move, say the move looks technical or \
   unclear rather than inventing a reason.
3. 3-5 stories from the headlines below that actually matter for {session_label}, grouped \
   by theme. For each: what happened, why it matters, and one line tying it to a specific \
   sector or to deal activity (M&A, IPOs, credit markets, buybacks, financing) relevant to \
   the firms this reader is targeting. Skip filler stories.
4. A "Jargon of the day" callout box: pick ONE term that appears naturally in today's news \
   (e.g. basis points, yield curve inversion, spread, duration, dry powder, mark-to-market, \
   repo market) and explain it in 2-3 plain-English sentences with a concrete example drawn \
   from today's actual data.

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

    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 8000,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        },
        timeout=180,
    )
    if not resp.ok:
        print(f"Anthropic API error {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    data = resp.json()
    for block in data["content"]:
        if block.get("type") == "text":
            return _strip_code_fence(block["text"])
    raise RuntimeError(f"No text content block in Anthropic response: {data}")

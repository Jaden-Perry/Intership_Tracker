"""Send new-posting alert emails via the Resend HTTP API."""
import os
import requests

RESEND_API_URL = "https://api.resend.com/emails"


def send_alerts(new_postings: list[dict]) -> None:
    """Send one email summarizing all newly detected postings.

    Expects env vars RESEND_API_KEY and ALERT_EMAIL. Silently no-ops if there's
    nothing new. Raises on API failure so the workflow run shows as failed
    (rather than silently swallowing a broken alert path).
    """
    if not new_postings:
        return

    api_key = os.environ["RESEND_API_KEY"]
    to_email = os.environ["ALERT_EMAIL"]
    from_email = os.environ.get("ALERT_FROM_EMAIL", "onboarding@resend.dev")

    subject = f"{len(new_postings)} new internship posting" + (
        "s" if len(new_postings) != 1 else ""
    )

    rows = "\n".join(
        f'<tr><td style="padding:8px;border-bottom:1px solid #eee">{p["firm"]}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #eee">{p["title"]}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #eee">{p["status_label"]}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #eee">'
        f'<a href="{p["url"]}">Open</a></td></tr>'
        for p in new_postings
    )
    html = f"""
    <h2>{subject}</h2>
    <table style="border-collapse:collapse;width:100%;font-family:sans-serif;font-size:14px">
      <tr style="text-align:left;background:#f5f5f5">
        <th style="padding:8px">Firm</th><th style="padding:8px">Program</th>
        <th style="padding:8px">Status</th><th style="padding:8px">Link</th>
      </tr>
      {rows}
    </table>
    """

    resp = requests.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": html,
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"Resend API error {resp.status_code}: {resp.text}")
    resp.raise_for_status()

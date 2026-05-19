"""
LogIQ — Notification skeleton (email + webhook).

Sends alerts when anomalies are detected. Off by default — set env vars to
enable.

Env vars:
  LOGIQ_SMTP_HOST       e.g. smtp.gmail.com
  LOGIQ_SMTP_PORT       e.g. 587
  LOGIQ_SMTP_USER       sender email
  LOGIQ_SMTP_PASS       app password
  LOGIQ_ALERT_TO        comma-separated recipient list
  LOGIQ_SLACK_WEBHOOK   incoming-webhook URL (optional)
"""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional


def _enabled() -> bool:
    return bool(os.getenv("LOGIQ_SMTP_HOST") and os.getenv("LOGIQ_SMTP_USER"))


def send_email_alert(subject: str, body_html: str, body_text: str, to: Optional[str] = None) -> bool:
    """Send an HTML email. Returns True if sent, False if not configured."""
    host = os.getenv("LOGIQ_SMTP_HOST")
    if not host:
        print(f"[notify] SMTP not configured — would have sent: {subject}")
        return False

    port = int(os.getenv("LOGIQ_SMTP_PORT", "587"))
    user = os.getenv("LOGIQ_SMTP_USER", "")
    pw = os.getenv("LOGIQ_SMTP_PASS", "")
    to_list = (to or os.getenv("LOGIQ_ALERT_TO", "")).split(",")
    to_list = [t.strip() for t in to_list if t.strip()]
    if not to_list:
        print(f"[notify] no recipients — set LOGIQ_ALERT_TO")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(to_list)
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.starttls()
            s.login(user, pw)
            s.sendmail(user, to_list, msg.as_string())
        print(f"[notify] sent email to {to_list}: {subject}")
        return True
    except Exception as e:
        print(f"[notify] email send failed: {e}")
        return False


def send_slack_alert(text: str) -> bool:
    url = os.getenv("LOGIQ_SLACK_WEBHOOK")
    if not url:
        print(f"[notify] no slack webhook — would have sent: {text[:80]}")
        return False
    try:
        import urllib.request, json
        data = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"[notify] slack send failed: {e}")
        return False


def format_verdict_email(verdict: dict) -> tuple[str, str, str]:
    """Build subject, html, text for a verdict-based alert."""
    flight = verdict.get("flight", {})
    score = verdict.get("overall_score", 0)
    status = verdict.get("overall_status", "fair").upper()
    summary = verdict.get("summary_en", "")
    subject = f"[LogIQ] {status} — {flight.get('file_name', 'flight')} scored {score}/100"

    rows_html = ""
    for c in verdict.get("categories", []):
        rows_html += f"<tr><td>{c['icon']} {c['name_en']}</td><td>{c['score']}/100 ({c['status']})</td></tr>"

    actions_html = ""
    for i, a in enumerate(verdict.get("actions", [])[:6], 1):
        actions_html += f"<li><b>{a.get('category')}:</b> {a.get('en')}</li>"

    html = f"""
    <html><body style='font-family:system-ui,sans-serif'>
    <h2 style='color:#0a3'>LogIQ Alert: {status}</h2>
    <p><b>{score}/100</b> — {summary}</p>
    <p><b>Flight:</b> {flight.get('file_name')}<br>
       <b>Date:</b> {flight.get('flown_at')}<br>
       <b>Class:</b> {flight.get('bucket')}</p>
    <table border='1' cellpadding='5'>{rows_html}</table>
    <h3>Recommended actions</h3>
    <ol>{actions_html}</ol>
    </body></html>
    """
    text = (
        f"LogIQ Alert: {status}\n"
        f"{score}/100 - {summary}\n\n"
        f"Flight: {flight.get('file_name')}\n"
        f"Date: {flight.get('flown_at')}\n\n"
        + "\n".join(f"- {a.get('en')}" for a in verdict.get("actions", [])[:6])
    )
    return subject, html, text


def alert_if_anomaly(verdict: dict, threshold: int = 50) -> bool:
    if verdict.get("overall_score", 100) >= threshold:
        return False
    if not _enabled():
        print(f"[notify] anomaly score={verdict.get('overall_score')} — alerting disabled (set SMTP env vars)")
        return False
    subject, html, text = format_verdict_email(verdict)
    return send_email_alert(subject, html, text)


if __name__ == "__main__":
    print(f"Notification enabled: {_enabled()}")
    if _enabled():
        send_email_alert("[LogIQ] Test", "<p>Hello from LogIQ</p>", "Hello from LogIQ")

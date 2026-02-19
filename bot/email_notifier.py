"""
Email notification system — sends a summary after each run via Gmail SMTP.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from bot.config import SMTP_EMAIL, SMTP_PASSWORD, NOTIFY_EMAIL
from bot.logger import get_run_stats

log = logging.getLogger(__name__)


def send_run_summary():
    """Send an email summarising this run's application results."""
    if not all([SMTP_EMAIL, SMTP_PASSWORD, NOTIFY_EMAIL]):
        log.warning("Email credentials not configured — skipping notification.")
        return

    stats = get_run_stats()
    if stats["applied"] == 0 and stats["failed"] == 0:
        log.info("Nothing to report — skipping email.")
        return

    subject = (
        f"Job Bot Report — {stats['date']} | "
        f"{stats['applied']} applied, {stats['failed']} failed"
    )

    # Build plain-text body
    lines = [
        f"Job Application Bot — Nightly Run Summary",
        f"{'='*50}",
        f"Date:        {stats['date']}",
        f"Applied:     {stats['applied']}",
        f"Skipped:     {stats['skipped']}  (duplicate / already applied)",
        f"Failed:      {stats['failed']}",
        "",
        "Applications submitted:",
        "-" * 40,
    ]
    for i, company_info in enumerate(stats["companies"], 1):
        lines.append(f"  {i}. {company_info}")
    if not stats["companies"]:
        lines.append("  (none)")
    lines += ["", "— Job Application Bot (automated)"]
    body = "\n".join(lines)

    # Build HTML body
    rows_html = ""
    for i, company_info in enumerate(stats["companies"], 1):
        rows_html += f"<tr><td>{i}</td><td>{company_info}</td></tr>\n"
    html = f"""
    <html><body>
    <h2>Job Application Bot — Run Summary</h2>
    <table border="0" cellpadding="4">
      <tr><td><b>Date</b></td><td>{stats['date']}</td></tr>
      <tr><td><b>Applied</b></td><td>{stats['applied']}</td></tr>
      <tr><td><b>Skipped</b></td><td>{stats['skipped']}</td></tr>
      <tr><td><b>Failed</b></td><td>{stats['failed']}</td></tr>
    </table>
    <h3>Applications Submitted</h3>
    <table border="1" cellpadding="4" cellspacing="0">
      <tr><th>#</th><th>Company — Role</th></tr>
      {rows_html}
    </table>
    <br><p><i>— Job Application Bot (automated)</i></p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_EMAIL
    msg["To"] = NOTIFY_EMAIL
    msg.attach(MIMEText(body, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, NOTIFY_EMAIL, msg.as_string())
        log.info(f"Summary email sent to {NOTIFY_EMAIL}")
    except Exception as e:
        log.error(f"Failed to send email: {e}")


def send_single_application_email(
    platform: str, company: str, job_title: str, job_url: str
):
    """Send an immediate confirmation email for a single application."""
    if not all([SMTP_EMAIL, SMTP_PASSWORD, NOTIFY_EMAIL]):
        return

    subject = f"Applied: {job_title} @ {company} ({platform})"
    body = (
        f"Your bot just submitted an application!\n\n"
        f"Platform:  {platform}\n"
        f"Company:   {company}\n"
        f"Role:      {job_title}\n"
        f"Link:      {job_url}\n\n"
        f"— Job Application Bot"
    )

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = SMTP_EMAIL
    msg["To"] = NOTIFY_EMAIL
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, NOTIFY_EMAIL, msg.as_string())
    except Exception:
        pass  # Non-critical — the run summary will still be sent

"""
Application logger — writes every application to a persistent CSV file
so Sahil can track all submissions.
"""

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from bot.config import APPLICATIONS_CSV

log = logging.getLogger(__name__)

CSV_HEADERS = [
    "timestamp",
    "platform",
    "job_title",
    "company",
    "location",
    "job_url",
    "status",          # applied | skipped | failed
    "failure_reason",
    "easy_apply",
]


def _ensure_csv():
    """Create the CSV with headers if it doesn't exist yet."""
    if not APPLICATIONS_CSV.exists():
        APPLICATIONS_CSV.parent.mkdir(parents=True, exist_ok=True)
        with open(APPLICATIONS_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)


def log_application(
    platform: str,
    job_title: str,
    company: str,
    location: str,
    job_url: str,
    status: str = "applied",
    failure_reason: str = "",
    easy_apply: bool = True,
):
    """Append one row to the applications CSV."""
    _ensure_csv()
    row = [
        datetime.now(timezone.utc).isoformat(),
        platform,
        job_title,
        company,
        location,
        job_url,
        status,
        failure_reason,
        str(easy_apply),
    ]
    with open(APPLICATIONS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(row)
    log.info(f"[{status.upper()}] {platform} | {company} — {job_title}")


def get_applied_urls() -> set[str]:
    """Return the set of job URLs already applied to (to avoid duplicates)."""
    _ensure_csv()
    urls: set[str] = set()
    with open(APPLICATIONS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("status") == "applied":
                urls.add(row.get("job_url", ""))
    return urls


def get_run_stats() -> dict:
    """Return a summary dict for the most recent run (same UTC date)."""
    _ensure_csv()
    today = datetime.now(timezone.utc).date().isoformat()
    applied = 0
    skipped = 0
    failed = 0
    companies: list[str] = []
    with open(APPLICATIONS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row.get("timestamp", "")
            if not ts.startswith(today):
                continue
            status = row.get("status", "")
            if status == "applied":
                applied += 1
                companies.append(f"{row.get('company','')} — {row.get('job_title','')}")
            elif status == "skipped":
                skipped += 1
            elif status == "failed":
                failed += 1
    return {
        "date": today,
        "applied": applied,
        "skipped": skipped,
        "failed": failed,
        "companies": companies,
    }

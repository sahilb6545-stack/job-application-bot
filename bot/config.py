"""
Centralized configuration loaded from environment variables.
Works with both .env files (local) and GitHub Actions secrets.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if it exists (local development)
load_dotenv()

# ── Paths ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESUME_PATH = PROJECT_ROOT / "Sahil_Bhatt_Resume.pdf"
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
APPLICATIONS_CSV = DATA_DIR / "applications.csv"

# ── LinkedIn ─────────────────────────────────────────────────
LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")
LINKEDIN_COOKIE = os.getenv("LINKEDIN_COOKIE", "")  # li_at session cookie (preferred)

# ── Indeed ───────────────────────────────────────────────────
INDEED_EMAIL = os.getenv("INDEED_EMAIL", "")
INDEED_PASSWORD = os.getenv("INDEED_PASSWORD", "")

# ── Email / SMTP ─────────────────────────────────────────────
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "")

# ── Bot Behaviour ────────────────────────────────────────────
MAX_APPLICATIONS_PER_RUN = int(os.getenv("MAX_APPLICATIONS_PER_RUN", "50"))
ACTION_DELAY_SECONDS = float(os.getenv("ACTION_DELAY_SECONDS", "3"))
PREFERRED_LOCATION = os.getenv("PREFERRED_LOCATION", "Toronto, ON, Canada")
PREFER_REMOTE = os.getenv("PREFER_REMOTE", "true").lower() == "true"

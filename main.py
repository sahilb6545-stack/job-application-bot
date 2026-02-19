#!/usr/bin/env python3
"""
Job Application Bot — Persistent Always-On Service
=====================================================
Runs continuously on Fly.io, executing a full application
cycle (LinkedIn + Indeed) every 10 minutes around the clock.

A lightweight HTTP health-check server runs on port 8080 so
Fly.io can monitor the process and restart it if it dies.

Usage:
    python main.py                      # run the persistent service
    python main.py --once               # run one cycle and exit
    python main.py --linkedin-only      # only LinkedIn (persistent)
    python main.py --indeed-only        # only Indeed   (persistent)
"""

import argparse
import logging
import signal
import sys
import os
import time
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.linkedin_bot import run_linkedin_bot
from bot.indeed_bot import run_indeed_bot
from bot.email_notifier import send_run_summary

# ── Configuration ────────────────────────────────────────────
CYCLE_INTERVAL_SECONDS = int(os.getenv("CYCLE_INTERVAL_SECONDS", "600"))  # 10 min
HEALTH_PORT = int(os.getenv("PORT", "8080"))

# ── Logging setup ────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("job_bot")

# ── Shared state for health check ────────────────────────────
_service_state = {
    "started_at": None,
    "last_cycle": None,
    "total_applied": 0,
    "cycles": 0,
    "status": "starting",
}

# ── Graceful shutdown ────────────────────────────────────────
_shutdown = threading.Event()


def _handle_signal(signum, frame):
    log.info(f"Received signal {signum} — shutting down gracefully...")
    _shutdown.set()


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ── Health check HTTP server ─────────────────────────────────
class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler so Fly.io knows the process is alive."""

    def do_GET(self):
        body = (
            f'{{"status":"{_service_state["status"]}",'
            f'"started_at":"{_service_state["started_at"]}",'
            f'"last_cycle":"{_service_state["last_cycle"]}",'
            f'"total_applied":{_service_state["total_applied"]},'
            f'"cycles":{_service_state["cycles"]}}}'
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, fmt, *args):
        pass  # Suppress per-request log noise


def _start_health_server():
    server = HTTPServer(("0.0.0.0", HEALTH_PORT), _HealthHandler)
    server.timeout = 1
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info(f"Health-check server listening on :{HEALTH_PORT}")
    return server


# ── Single application cycle ─────────────────────────────────
def run_cycle(run_linkedin: bool = True, run_indeed: bool = True) -> int:
    """Execute one full application cycle. Returns total applied."""
    log.info("=" * 60)
    log.info("  CYCLE START — %s", datetime.now(timezone.utc).isoformat())
    log.info("=" * 60)

    total_applied = 0

    if run_linkedin:
        log.info("─── LinkedIn Easy Apply ───")
        try:
            count = run_linkedin_bot()
            total_applied += count
            log.info(f"LinkedIn: {count} applications submitted.")
        except Exception as e:
            log.error(f"LinkedIn bot crashed: {e}", exc_info=True)

    if run_indeed:
        log.info("─── Indeed Apply ───")
        try:
            count = run_indeed_bot()
            total_applied += count
            log.info(f"Indeed: {count} applications submitted.")
        except Exception as e:
            log.error(f"Indeed bot crashed: {e}", exc_info=True)

    # Send summary email (only if something happened this UTC day)
    try:
        send_run_summary()
    except Exception as e:
        log.error(f"Failed to send summary email: {e}")

    log.info("=" * 60)
    log.info(f"  CYCLE COMPLETE — {total_applied} applications this cycle")
    log.info("=" * 60)
    return total_applied


# ── Main entry point ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Automated Job Application Bot")
    parser.add_argument("--once", action="store_true", help="Run one cycle then exit")
    parser.add_argument("--linkedin-only", action="store_true", help="LinkedIn only")
    parser.add_argument("--indeed-only", action="store_true", help="Indeed only")
    args = parser.parse_args()

    do_linkedin = not args.indeed_only
    do_indeed = not args.linkedin_only

    # ── Single-run mode (for testing / CI) ───────────────────
    if args.once:
        applied = run_cycle(do_linkedin, do_indeed)
        return 0 if applied >= 0 else 1

    # ── Persistent service mode ──────────────────────────────
    _service_state["started_at"] = datetime.now(timezone.utc).isoformat()
    _service_state["status"] = "running"
    _start_health_server()

    log.info("╔════════════════════════════════════════════════════════╗")
    log.info("║  JOB APPLICATION BOT — Persistent Service Started     ║")
    log.info(f"║  Cycle interval: {CYCLE_INTERVAL_SECONDS}s ({CYCLE_INTERVAL_SECONDS // 60} min)  "
             f"                          ║")
    log.info("╚════════════════════════════════════════════════════════╝")

    while not _shutdown.is_set():
        _service_state["status"] = "applying"
        try:
            applied = run_cycle(do_linkedin, do_indeed)
            _service_state["total_applied"] += applied
            _service_state["cycles"] += 1
            _service_state["last_cycle"] = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            log.error(f"Cycle crashed unexpectedly: {e}", exc_info=True)

        _service_state["status"] = "sleeping"
        log.info(f"Sleeping {CYCLE_INTERVAL_SECONDS}s until next cycle...")

        # Sleep in small increments so we can respond to SIGTERM quickly
        remaining = CYCLE_INTERVAL_SECONDS
        while remaining > 0 and not _shutdown.is_set():
            chunk = min(remaining, 5)
            time.sleep(chunk)
            remaining -= chunk

    _service_state["status"] = "stopped"
    log.info("Service stopped gracefully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

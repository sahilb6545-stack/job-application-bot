"""
Shared utility helpers for the bot — delays, retries, text matching.
"""

import logging
import random
import time
from bot.config import ACTION_DELAY_SECONDS

log = logging.getLogger(__name__)


def human_delay(multiplier: float = 1.0):
    """Sleep for a randomized human-like duration."""
    base = ACTION_DELAY_SECONDS * multiplier
    jitter = base * 0.3
    delay = base + random.uniform(-jitter, jitter)
    delay = max(0.5, delay)
    time.sleep(delay)


def random_delay(min_sec: float = 1.0, max_sec: float = 3.0):
    """Sleep for a random interval between min and max seconds."""
    time.sleep(random.uniform(min_sec, max_sec))


def safe_click(page, selector: str, timeout: int = 5000) -> bool:
    """Click an element if it exists; return True on success."""
    try:
        el = page.locator(selector).first
        el.wait_for(state="visible", timeout=timeout)
        el.click()
        return True
    except Exception:
        return False


def safe_fill(page, selector: str, value: str, timeout: int = 5000) -> bool:
    """Fill an input if it exists; return True on success."""
    try:
        el = page.locator(selector).first
        el.wait_for(state="visible", timeout=timeout)
        el.fill(value)
        return True
    except Exception:
        return False


def safe_select(page, selector: str, value: str, timeout: int = 5000) -> bool:
    """Select an option in a <select> dropdown if it exists."""
    try:
        el = page.locator(selector).first
        el.wait_for(state="visible", timeout=timeout)
        el.select_option(value=value)
        return True
    except Exception:
        # Try selecting by label instead
        try:
            el = page.locator(selector).first
            el.select_option(label=value)
            return True
        except Exception:
            return False


def safe_upload(page, selector: str, file_path: str, timeout: int = 5000) -> bool:
    """Upload a file to a file input if it exists."""
    try:
        el = page.locator(selector).first
        el.wait_for(state="attached", timeout=timeout)
        el.set_input_files(file_path)
        return True
    except Exception:
        return False


def text_contains_any(text: str, keywords: list[str]) -> bool:
    """Check if text contains any of the given keywords (case-insensitive)."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def truncate(text: str, max_len: int = 100) -> str:
    """Truncate text for logging."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."

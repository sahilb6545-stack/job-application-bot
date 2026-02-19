"""
Indeed Apply Bot
=================
Uses Playwright to:
  1. Log in to Indeed
  2. Search for jobs matching target titles & locations
  3. Identify "Apply now" / "Indeed Apply" listings
  4. Walk through application forms, fill fields, upload resume, submit
  5. Log each application and send confirmation email
"""

import logging
import os
import re
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext

from bot.config import (
    INDEED_EMAIL,
    INDEED_PASSWORD,
    RESUME_PATH,
    MAX_APPLICATIONS_PER_RUN,
)
from bot.profile import (
    FIRST_NAME,
    LAST_NAME,
    FULL_NAME,
    PHONE,
    CITY,
    STATE_PROVINCE,
    COUNTRY,
    YEARS_OF_EXPERIENCE,
    get_answer_for_question,
    TARGET_JOB_TITLES,
    SEARCH_LOCATIONS,
)
from bot.logger import log_application, get_applied_urls
from bot.email_notifier import send_single_application_email
from bot.utils import human_delay, random_delay, safe_click, safe_fill, safe_upload

log = logging.getLogger(__name__)

INDEED_LOGIN_URL = "https://secure.indeed.com/auth"
INDEED_BASE_URL = "https://www.indeed.com"
INDEED_CA_BASE_URL = "https://ca.indeed.com"


# ── Helpers ──────────────────────────────────────────────────

def _build_search_url(keywords: str, location: str) -> str:
    """Build an Indeed job search URL."""
    base = INDEED_CA_BASE_URL if "canada" in location.lower() or "on" in location.lower() else INDEED_BASE_URL
    return f"{base}/jobs?q={quote_plus(keywords)}&l={quote_plus(location)}&sort=date&fromage=7"


def _login(page: Page):
    """Log in to Indeed."""
    log.info("Logging in to Indeed...")
    page.goto(INDEED_LOGIN_URL, wait_until="domcontentloaded")
    human_delay(1.0)

    # Indeed login flow — enter email first
    email_input = page.locator(
        'input[type="email"], input[name="__email"], input#ifl-InputFormField-3'
    ).first
    try:
        email_input.wait_for(state="visible", timeout=10000)
        email_input.fill(INDEED_EMAIL)
        human_delay(0.5)
    except Exception:
        log.warning("Could not find email input; trying alternative selectors.")
        safe_fill(page, 'input[name="email"]', INDEED_EMAIL)
        human_delay(0.5)

    # Click continue / submit email
    safe_click(page, 'button[type="submit"], button:has-text("Continue"), button:has-text("Log in")')
    human_delay(2.0)

    # Password page
    password_input = page.locator(
        'input[type="password"], input[name="__password"]'
    ).first
    try:
        password_input.wait_for(state="visible", timeout=10000)
        password_input.fill(INDEED_PASSWORD)
        human_delay(0.5)
    except Exception:
        log.warning("Password field not found — Indeed may use email-only auth or CAPTCHA.")
        return

    safe_click(page, 'button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")')
    human_delay(3.0)

    # Verify login
    try:
        page.wait_for_url("**/*", timeout=15000)
        log.info("Indeed login complete.")
    except Exception:
        log.warning("Indeed login may not have succeeded — continuing anyway.")


def _get_job_listings(page: Page) -> list[dict]:
    """Extract job listings from an Indeed search results page."""
    jobs = []
    try:
        page.wait_for_selector(
            '.job_seen_beacon, .jobsearch-ResultsList > li, .resultContent',
            timeout=10000,
        )
    except Exception:
        log.warning("No job listings found on Indeed page.")
        return jobs

    cards = page.locator('.job_seen_beacon, .resultContent').all()
    for card in cards:
        try:
            # Title
            title_el = card.locator('h2.jobTitle a, h2.jobTitle span, .jcs-JobTitle')
            title = title_el.first.inner_text(timeout=3000).strip()

            # Company
            company_el = card.locator('[data-testid="company-name"], .companyName, .company')
            company = company_el.first.inner_text(timeout=3000).strip()

            # Location
            loc_el = card.locator('[data-testid="text-location"], .companyLocation, .location')
            location = loc_el.first.inner_text(timeout=3000).strip()

            # Link
            link_el = card.locator('a[href*="/viewjob"], a[href*="jk="], h2.jobTitle a').first
            href = link_el.get_attribute('href') or ""
            if href and not href.startswith("http"):
                href = f"https://www.indeed.com{href}"

            # Check if it says "Easily apply" (Indeed's easy apply indicator)
            easily_apply = False
            try:
                badge = card.locator(
                    '.ialbl, span:has-text("Easily apply"), '
                    'span:has-text("Responded to"), '
                    '.indeed-apply-widget'
                )
                easily_apply = badge.count() > 0
            except Exception:
                pass

            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "url": href,
                "easily_apply": easily_apply,
                "element": card,
            })
        except Exception as e:
            log.debug(f"Failed to parse Indeed card: {e}")
            continue

    return jobs


def _apply_to_job(page: Page, job: dict) -> bool:
    """
    Navigate to a job page and complete the Indeed application flow.
    Returns True on successful submission.
    """
    log.info(f"Attempting to apply: {job['company']} — {job['title']}")

    try:
        page.goto(job["url"], wait_until="domcontentloaded", timeout=15000)
        human_delay(1.5)
    except Exception:
        log.warning(f"Could not load job page: {job['url']}")
        return False

    # Click the Apply button
    apply_btn = page.locator(
        '#indeedApplyButton, '
        'button:has-text("Apply now"), '
        'button:has-text("Apply on company site"), '
        '.indeed-apply-button, '
        'button[id*="apply"], '
        'a:has-text("Apply now")'
    ).first

    try:
        apply_btn.wait_for(state="visible", timeout=5000)
    except Exception:
        log.warning("Apply button not found.")
        return False

    # Check if this opens an external site (we only want Indeed Apply)
    btn_text = apply_btn.inner_text(timeout=2000).lower()
    if "company site" in btn_text:
        log.info("External application — skipping (Indeed Apply only).")
        return False

    apply_btn.click()
    human_delay(2.0)

    # Indeed may open the application in a new tab or an iframe
    # Handle popup if it opened in a new page
    if len(page.context.pages) > 1:
        page = page.context.pages[-1]   # Switch to the new tab
        human_delay(1.0)

    # Walk through application pages (up to 12 steps)
    max_steps = 12
    for step in range(max_steps):
        human_delay(1.0)

        # ── Check for confirmation / success ──
        success_indicators = [
            'h1:has-text("Application submitted")',
            'h1:has-text("application has been submitted")',
            'h1:has-text("You applied")',
            ':text("Your application has been submitted")',
            ':text("Application sent")',
        ]
        for indicator in success_indicators:
            try:
                if page.locator(indicator).is_visible(timeout=1500):
                    log.info(f"✓ Successfully applied: {job['company']} — {job['title']}")
                    return True
            except Exception:
                continue

        # ── Fill form fields on current page ──
        _fill_indeed_fields(page)

        # ── Upload resume if the file input is present ──
        file_input = page.locator('input[type="file"]').first
        if file_input.count() > 0:
            try:
                file_input.set_input_files(str(RESUME_PATH))
                log.info("Resume uploaded on Indeed.")
                human_delay(1.0)
            except Exception:
                pass

        # ── Click "Continue" / "Submit" / "Apply" ──
        submit_btn = page.locator(
            'button:has-text("Submit your application"), '
            'button:has-text("Submit application"), '
            'button:has-text("Submit"), '
            'button[type="submit"]:has-text("Apply")'
        ).first
        if submit_btn.is_visible(timeout=1500):
            submit_btn.click()
            human_delay(2.0)
            # Check for success after submit
            for indicator in success_indicators:
                try:
                    if page.locator(indicator).is_visible(timeout=3000):
                        log.info(f"✓ Successfully applied: {job['company']} — {job['title']}")
                        return True
                except Exception:
                    continue
            # Might have submitted successfully even without indicator
            return True

        continue_btn = page.locator(
            'button:has-text("Continue"), '
            'button:has-text("Next"), '
            'button[type="button"]:has-text("Continue")'
        ).first
        if continue_btn.is_visible(timeout=2000):
            continue_btn.click()
            human_delay(1.0)
            continue

        # Nothing to click — might be stuck
        log.warning(f"No actionable button at step {step}.")
        break

    log.warning(f"Could not complete Indeed application for: {job['title']}")
    return False


def _fill_indeed_fields(page: Page):
    """Fill all visible form fields on an Indeed application page."""
    # ── Text inputs ──
    inputs = page.locator(
        'input[type="text"], input[type="tel"], input[type="email"], '
        'input[type="number"], textarea'
    ).all()

    for inp in inputs:
        try:
            current_val = inp.input_value(timeout=1000)
            if current_val and current_val.strip():
                continue

            label = _get_field_label(page, inp)
            if not label:
                continue

            answer = _match_field_answer(label)
            if answer:
                inp.fill(answer)
                human_delay(0.2)
        except Exception:
            continue

    # ── Select dropdowns ──
    selects = page.locator('select').all()
    for sel in selects:
        try:
            label = _get_field_label(page, sel)
            if not label:
                continue

            answer = _match_field_answer(label)
            if answer:
                try:
                    sel.select_option(label=answer, timeout=1000)
                except Exception:
                    try:
                        sel.select_option(value=answer, timeout=1000)
                    except Exception:
                        pass
                human_delay(0.2)
        except Exception:
            continue

    # ── Radio buttons ──
    fieldsets = page.locator('fieldset, [role="radiogroup"], [role="group"]').all()
    for fs in fieldsets:
        try:
            legend = ""
            legend_el = fs.locator('legend, label.ia-BaseLabelWrapper, span')
            if legend_el.count() > 0:
                legend = legend_el.first.inner_text(timeout=1000)
            if not legend:
                continue

            answer = _match_field_answer(legend)
            if answer:
                labels = fs.locator('label').all()
                for lbl in labels:
                    try:
                        lbl_text = lbl.inner_text(timeout=500).lower()
                        if answer.lower() in lbl_text:
                            lbl.click()
                            human_delay(0.2)
                            break
                    except Exception:
                        continue
        except Exception:
            continue


def _get_field_label(page: Page, element) -> str:
    """Try to find the label text for a form element."""
    try:
        el_id = element.get_attribute("id") or ""
        if el_id:
            label = page.locator(f'label[for="{el_id}"]')
            if label.count() > 0:
                return label.first.inner_text(timeout=1000)
    except Exception:
        pass

    try:
        return element.get_attribute("aria-label") or ""
    except Exception:
        pass

    try:
        return element.get_attribute("placeholder") or ""
    except Exception:
        pass

    return ""


def _match_field_answer(label: str) -> str | None:
    """Match a form field label to a known answer."""
    label_lower = label.lower().strip()

    if any(k in label_lower for k in ["first name"]):
        return FIRST_NAME
    if any(k in label_lower for k in ["last name", "surname", "family name"]):
        return LAST_NAME
    if any(k in label_lower for k in ["full name"]):
        return FULL_NAME
    if any(k in label_lower for k in ["email"]):
        return INDEED_EMAIL
    if any(k in label_lower for k in ["phone", "mobile", "telephone", "cell"]):
        return PHONE or os.getenv("APPLICANT_PHONE", "")
    if any(k in label_lower for k in ["city"]):
        return CITY
    if any(k in label_lower for k in ["state", "province"]):
        return STATE_PROVINCE
    if any(k in label_lower for k in ["country"]):
        return COUNTRY
    if any(k in label_lower for k in ["years of experience", "how many years"]):
        return YEARS_OF_EXPERIENCE

    return get_answer_for_question(label)


# ── Main Entry Point ─────────────────────────────────────────
def run_indeed_bot() -> int:
    """
    Run the full Indeed Apply flow.
    Returns the number of successful applications.
    """
    if not INDEED_EMAIL or not INDEED_PASSWORD:
        log.error("Indeed credentials not configured. Skipping Indeed.")
        return 0

    applied_count = 0
    already_applied = get_applied_urls()

    with sync_playwright() as p:
        browser: Browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context: BrowserContext = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page: Page = context.new_page()

        try:
            _login(page)
        except Exception as e:
            log.error(f"Indeed login failed: {e}")
            browser.close()
            return 0

        for job_title in TARGET_JOB_TITLES:
            if applied_count >= MAX_APPLICATIONS_PER_RUN:
                break

            for location in SEARCH_LOCATIONS:
                if applied_count >= MAX_APPLICATIONS_PER_RUN:
                    break

                search_url = _build_search_url(job_title, location)
                log.info(f"Searching Indeed: '{job_title}' in '{location}'")

                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
                    human_delay(1.5)
                except Exception as e:
                    log.warning(f"Failed to load Indeed search: {e}")
                    continue

                # Process up to 3 pages of results
                for page_num in range(3):
                    if applied_count >= MAX_APPLICATIONS_PER_RUN:
                        break

                    listings = _get_job_listings(page)
                    if not listings:
                        break

                    for job in listings:
                        if applied_count >= MAX_APPLICATIONS_PER_RUN:
                            break

                        if job["url"] in already_applied:
                            continue

                        try:
                            success = _apply_to_job(page, job)

                            if success:
                                applied_count += 1
                                already_applied.add(job["url"])
                                log_application(
                                    platform="Indeed",
                                    job_title=job["title"],
                                    company=job["company"],
                                    location=job["location"],
                                    job_url=job["url"],
                                    status="applied",
                                    easy_apply=job.get("easily_apply", False),
                                )
                                send_single_application_email(
                                    platform="Indeed",
                                    company=job["company"],
                                    job_title=job["title"],
                                    job_url=job["url"],
                                )
                            else:
                                log_application(
                                    platform="Indeed",
                                    job_title=job["title"],
                                    company=job["company"],
                                    location=job["location"],
                                    job_url=job["url"],
                                    status="failed",
                                    failure_reason="Application flow did not complete",
                                    easy_apply=job.get("easily_apply", False),
                                )
                        except Exception as e:
                            log.error(f"Error applying to {job.get('title','?')}: {e}")
                            log_application(
                                platform="Indeed",
                                job_title=job.get("title", "Unknown"),
                                company=job.get("company", "Unknown"),
                                location=job.get("location", ""),
                                job_url=job.get("url", ""),
                                status="failed",
                                failure_reason=str(e)[:200],
                            )
                            continue

                        # Navigate back to search results
                        try:
                            page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
                            human_delay(1.0)
                        except Exception:
                            break

                    # Go to next page
                    next_btn = page.locator(
                        'a[data-testid="pagination-page-next"], '
                        'a[aria-label="Next Page"], '
                        'a:has-text("Next")'
                    ).first
                    if next_btn.is_visible(timeout=3000):
                        next_btn.click()
                        human_delay(2.0)
                    else:
                        break

        browser.close()

    log.info(f"Indeed run complete. Applied to {applied_count} jobs.")
    return applied_count

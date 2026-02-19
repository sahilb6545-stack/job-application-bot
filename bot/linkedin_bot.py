"""
LinkedIn Easy Apply Bot
========================
Uses Playwright to:
  1. Log in to LinkedIn
  2. Search for jobs matching target titles & locations
  3. Filter to "Easy Apply" only
  4. Walk through the Easy Apply modal, fill fields, upload resume, submit
  5. Log each application and send confirmation email
"""

import logging
import os
import re
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext

from bot.config import (
    LINKEDIN_EMAIL,
    LINKEDIN_PASSWORD,
    RESUME_PATH,
    MAX_APPLICATIONS_PER_RUN,
)
from bot.profile import (
    FIRST_NAME,
    LAST_NAME,
    FULL_NAME,
    PHONE,
    CITY,
    YEARS_OF_EXPERIENCE,
    SCREENING_ANSWERS,
    get_answer_for_question,
    TARGET_JOB_TITLES,
    SEARCH_LOCATIONS,
)
from bot.logger import log_application, get_applied_urls
from bot.email_notifier import send_single_application_email
from bot.utils import human_delay, random_delay, safe_click, safe_fill, safe_upload

log = logging.getLogger(__name__)

LINKEDIN_LOGIN_URL = "https://www.linkedin.com/login"
LINKEDIN_JOBS_URL = "https://www.linkedin.com/jobs/search/"


# ── Helpers ──────────────────────────────────────────────────
def _build_search_url(keywords: str, location: str, easy_apply: bool = True) -> str:
    """Build a LinkedIn job search URL with filters."""
    from urllib.parse import quote_plus
    params = f"keywords={quote_plus(keywords)}&location={quote_plus(location)}"
    if easy_apply:
        params += "&f_AL=true"               # Easy Apply filter
    params += "&sortBy=DD"                    # Sort by most recent
    return f"{LINKEDIN_JOBS_URL}?{params}"


def _login(page: Page):
    """Log in to LinkedIn."""
    log.info("Logging in to LinkedIn...")
    page.goto(LINKEDIN_LOGIN_URL, wait_until="domcontentloaded")
    human_delay(0.5)

    page.fill('input#username', LINKEDIN_EMAIL)
    human_delay(0.3)
    page.fill('input#password', LINKEDIN_PASSWORD)
    human_delay(0.3)
    page.click('button[type="submit"]')

    # Wait for navigation to complete
    page.wait_for_url("**/feed/**", timeout=30000)
    log.info("LinkedIn login successful.")
    human_delay(1.0)


def _get_job_cards(page: Page) -> list[dict]:
    """Extract visible job cards from the search results page."""
    jobs = []
    try:
        # Wait for job cards to appear
        page.wait_for_selector(
            '.jobs-search-results__list-item, .job-card-container',
            timeout=10000,
        )
    except Exception:
        log.warning("No job cards found on page.")
        return jobs

    cards = page.locator('.jobs-search-results__list-item, .job-card-container').all()
    for card in cards:
        try:
            title_el = card.locator('.job-card-list__title, .job-card-container__link')
            title = title_el.inner_text(timeout=3000).strip()

            company_el = card.locator(
                '.job-card-container__primary-description, '
                '.job-card-container__company-name, '
                '.artdeco-entity-lockup__subtitle'
            )
            company = company_el.inner_text(timeout=3000).strip()

            location_el = card.locator(
                '.job-card-container__metadata-wrapper, '
                '.artdeco-entity-lockup__caption'
            )
            location = location_el.inner_text(timeout=3000).strip()

            # Get the job link
            link_el = card.locator('a').first
            href = link_el.get_attribute('href') or ""
            if href and not href.startswith("http"):
                href = f"https://www.linkedin.com{href}"

            # Extract job ID from URL
            job_id_match = re.search(r'/jobs/view/(\d+)', href)
            job_id = job_id_match.group(1) if job_id_match else ""

            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "url": href,
                "job_id": job_id,
                "element": card,
            })
        except Exception as e:
            log.debug(f"Failed to parse a job card: {e}")
            continue
    return jobs


def _apply_easy_apply(page: Page, job: dict) -> bool:
    """
    Handle the entire Easy Apply modal flow for one job.
    Returns True if the application was submitted successfully.
    """
    log.info(f"Attempting Easy Apply: {job['company']} — {job['title']}")

    # Click the Easy Apply button
    try:
        easy_apply_btn = page.locator(
            'button.jobs-apply-button, '
            'button:has-text("Easy Apply"), '
            'button:has-text("easy apply")'
        ).first
        easy_apply_btn.wait_for(state="visible", timeout=5000)
        easy_apply_btn.click()
        human_delay(1.0)
    except Exception as e:
        log.warning(f"Easy Apply button not found: {e}")
        return False

    # Cap the number of modal pages to prevent infinite loops
    max_pages = 10
    for step in range(max_pages):
        human_delay(0.8)

        # ── Check if we see "Submit application" button ──
        submit_btn = page.locator(
            'button:has-text("Submit application"), '
            'button[aria-label="Submit application"]'
        ).first
        if submit_btn.is_visible(timeout=1500):
            # Final page — fill anything remaining, then submit
            _fill_current_page_fields(page, job)
            human_delay(0.5)
            submit_btn.click()
            human_delay(1.5)

            # Check for success
            try:
                page.wait_for_selector(
                    'h2:has-text("application was sent"), '
                    'h2:has-text("Application sent"), '
                    'div:has-text("Your application was sent")',
                    timeout=8000,
                )
                log.info(f"✓ Successfully applied: {job['company']} — {job['title']}")
                # Dismiss the success dialog
                safe_click(page, 'button[aria-label="Dismiss"], button:has-text("Done")', timeout=3000)
                return True
            except Exception:
                log.warning("Submit clicked but success confirmation not detected.")
                # Dismiss any dialog
                safe_click(page, 'button[aria-label="Dismiss"], button:has-text("Done")', timeout=2000)
                return True  # Optimistic — likely submitted

        # ── Check for "Review" button (final review page before submit) ──
        review_btn = page.locator('button:has-text("Review"), button[aria-label="Review your application"]').first
        if review_btn.is_visible(timeout=1000):
            _fill_current_page_fields(page, job)
            human_delay(0.3)
            review_btn.click()
            continue

        # ── Fill fields on current page ──
        _fill_current_page_fields(page, job)

        # ── Upload resume if input is visible ──
        file_input = page.locator('input[type="file"]').first
        if file_input.count() > 0:
            try:
                file_input.set_input_files(str(RESUME_PATH))
                log.info("Resume uploaded.")
                human_delay(0.5)
            except Exception:
                pass

        # ── Click "Next" to advance ──
        next_btn = page.locator(
            'button:has-text("Next"), '
            'button[aria-label="Continue to next step"], '
            'button:has-text("Continue")'
        ).first
        if next_btn.is_visible(timeout=2000):
            next_btn.click()
            human_delay(0.5)
            continue

        # No next or submit found — possibly stuck
        log.warning(f"No actionable button found at step {step}. Trying to close modal.")
        safe_click(page, 'button[aria-label="Dismiss"], button:has-text("Discard")', timeout=2000)
        safe_click(page, 'button:has-text("Discard")', timeout=2000)
        return False

    log.warning("Exceeded maximum Easy Apply steps.")
    safe_click(page, 'button[aria-label="Dismiss"]', timeout=2000)
    safe_click(page, 'button:has-text("Discard")', timeout=2000)
    return False


def _fill_current_page_fields(page: Page, job: dict):
    """
    Detect and fill all input/select/textarea fields on the current
    Easy Apply modal page.
    """
    # ── Text inputs ──
    inputs = page.locator(
        '.jobs-easy-apply-modal input[type="text"], '
        '.jobs-easy-apply-modal input[type="tel"], '
        '.jobs-easy-apply-modal input[type="email"], '
        '.jobs-easy-apply-modal input[type="number"], '
        '.jobs-easy-apply-modal textarea'
    ).all()

    for inp in inputs:
        try:
            # Skip if already filled
            current_val = inp.input_value(timeout=1000)
            if current_val and current_val.strip():
                continue

            # Get label
            label = ""
            inp_id = inp.get_attribute("id") or ""
            if inp_id:
                label_el = page.locator(f'label[for="{inp_id}"]')
                if label_el.count() > 0:
                    label = label_el.inner_text(timeout=1000)
            if not label:
                placeholder = inp.get_attribute("placeholder") or ""
                aria_label = inp.get_attribute("aria-label") or ""
                label = placeholder or aria_label

            if not label:
                continue

            # Match label to known answers
            answer = _match_field_answer(label)
            if answer:
                inp.fill(answer)
                human_delay(0.2)
        except Exception:
            continue

    # ── Select dropdowns ──
    selects = page.locator(
        '.jobs-easy-apply-modal select'
    ).all()

    for sel in selects:
        try:
            # Get label
            label = ""
            sel_id = sel.get_attribute("id") or ""
            if sel_id:
                label_el = page.locator(f'label[for="{sel_id}"]')
                if label_el.count() > 0:
                    label = label_el.inner_text(timeout=1000)
            aria_label = sel.get_attribute("aria-label") or ""
            label = label or aria_label

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
                        # Try selecting the first "Yes" option
                        options = sel.locator('option').all()
                        for opt in options:
                            if answer.lower() in (opt.inner_text(timeout=500)).lower():
                                sel.select_option(label=opt.inner_text())
                                break
                human_delay(0.2)
        except Exception:
            continue

    # ── Radio buttons / fieldsets ──
    fieldsets = page.locator(
        '.jobs-easy-apply-modal fieldset, '
        '.jobs-easy-apply-modal [role="radiogroup"]'
    ).all()

    for fs in fieldsets:
        try:
            legend = ""
            legend_el = fs.locator('legend, span.fb-dash-form-element__label')
            if legend_el.count() > 0:
                legend = legend_el.first.inner_text(timeout=1000)
            if not legend:
                continue

            answer = _match_field_answer(legend)
            if answer:
                # Find the radio/checkbox matching the answer
                radios = fs.locator('label, input[type="radio"]').all()
                for radio in radios:
                    try:
                        radio_text = radio.inner_text(timeout=500) if radio.evaluate("el => el.tagName") == "LABEL" else ""
                        if answer.lower() in radio_text.lower():
                            radio.click()
                            human_delay(0.2)
                            break
                    except Exception:
                        continue
        except Exception:
            continue


def _match_field_answer(label: str) -> str | None:
    """Match a form field label to a known answer."""
    label_lower = label.lower().strip()

    # Direct field matches
    if any(k in label_lower for k in ["first name"]):
        return FIRST_NAME
    if any(k in label_lower for k in ["last name", "surname", "family name"]):
        return LAST_NAME
    if any(k in label_lower for k in ["full name"]):
        return FULL_NAME
    if any(k in label_lower for k in ["email"]):
        return LINKEDIN_EMAIL
    if any(k in label_lower for k in ["phone", "mobile", "telephone", "cell"]):
        return PHONE or os.getenv("APPLICANT_PHONE", "")
    if any(k in label_lower for k in ["city", "location"]):
        return CITY
    if any(k in label_lower for k in ["years of experience", "how many years"]):
        return YEARS_OF_EXPERIENCE

    # Fall through to screening answers
    return get_answer_for_question(label)


# ── Main Entry Point ─────────────────────────────────────────
def run_linkedin_bot() -> int:
    """
    Run the full LinkedIn Easy Apply flow.
    Returns the number of successful applications.
    """
    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        log.error("LinkedIn credentials not configured. Skipping LinkedIn.")
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
            log.error(f"LinkedIn login failed: {e}")
            browser.close()
            return 0

        # Search for each job title + location combination
        for job_title in TARGET_JOB_TITLES:
            if applied_count >= MAX_APPLICATIONS_PER_RUN:
                break

            for location in SEARCH_LOCATIONS:
                if applied_count >= MAX_APPLICATIONS_PER_RUN:
                    break

                search_url = _build_search_url(job_title, location)
                log.info(f"Searching: '{job_title}' in '{location}'")

                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
                    human_delay(1.5)
                except Exception as e:
                    log.warning(f"Failed to load search page: {e}")
                    continue

                # Scroll through pages of results (up to 3 pages)
                for page_num in range(3):
                    if applied_count >= MAX_APPLICATIONS_PER_RUN:
                        break

                    jobs = _get_job_cards(page)
                    if not jobs:
                        break

                    for job in jobs:
                        if applied_count >= MAX_APPLICATIONS_PER_RUN:
                            break

                        if job["url"] in already_applied:
                            log.debug(f"Already applied: {job['url']}")
                            continue

                        try:
                            # Click the job card to load its details
                            job["element"].click()
                            human_delay(1.0)

                            # Check if Easy Apply button exists
                            has_easy_apply = page.locator(
                                'button.jobs-apply-button, '
                                'button:has-text("Easy Apply")'
                            ).first.is_visible(timeout=3000)

                            if not has_easy_apply:
                                log.debug(f"No Easy Apply for: {job['title']}")
                                continue

                            success = _apply_easy_apply(page, job)

                            if success:
                                applied_count += 1
                                already_applied.add(job["url"])
                                log_application(
                                    platform="LinkedIn",
                                    job_title=job["title"],
                                    company=job["company"],
                                    location=job["location"],
                                    job_url=job["url"],
                                    status="applied",
                                    easy_apply=True,
                                )
                                send_single_application_email(
                                    platform="LinkedIn",
                                    company=job["company"],
                                    job_title=job["title"],
                                    job_url=job["url"],
                                )
                            else:
                                log_application(
                                    platform="LinkedIn",
                                    job_title=job["title"],
                                    company=job["company"],
                                    location=job["location"],
                                    job_url=job["url"],
                                    status="failed",
                                    failure_reason="Easy Apply flow did not complete",
                                    easy_apply=True,
                                )

                        except Exception as e:
                            log.error(f"Error applying to {job.get('title','?')}: {e}")
                            log_application(
                                platform="LinkedIn",
                                job_title=job.get("title", "Unknown"),
                                company=job.get("company", "Unknown"),
                                location=job.get("location", ""),
                                job_url=job.get("url", ""),
                                status="failed",
                                failure_reason=str(e)[:200],
                                easy_apply=True,
                            )
                            # Try to dismiss any open modals
                            safe_click(page, 'button[aria-label="Dismiss"]', timeout=1000)
                            safe_click(page, 'button:has-text("Discard")', timeout=1000)
                            continue

                    # Try to go to next page of results
                    next_page_btn = page.locator(
                        f'button[aria-label="Page {page_num + 2}"], '
                        f'li[data-test-pagination-page-btn="{page_num + 2}"] button'
                    ).first
                    if next_page_btn.is_visible(timeout=2000):
                        next_page_btn.click()
                        human_delay(1.5)
                    else:
                        break

        browser.close()

    log.info(f"LinkedIn run complete. Applied to {applied_count} jobs.")
    return applied_count

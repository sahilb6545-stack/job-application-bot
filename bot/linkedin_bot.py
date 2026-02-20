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
import tempfile
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext

from bot.config import (
    LINKEDIN_EMAIL,
    LINKEDIN_PASSWORD,
    LINKEDIN_COOKIE,
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

# ── Resume Download ──────────────────────────────────────────
RESUME_DOWNLOAD_URL = (
    "https://drive.google.com/uc?export=download&id=1fAyQoXCcSguS2ye1PDGQ_bjNp9EEM7_a"
)

def _ensure_resume() -> str:
    """Return path to a local resume PDF, downloading from Google Drive if needed."""
    if RESUME_PATH.exists():
        log.info(f"Resume found locally: {RESUME_PATH}")
        return str(RESUME_PATH)
    # Download to a temp file that persists for this process
    dest = Path(tempfile.gettempdir()) / "Sahil_Bhatt_Resume.pdf"
    if dest.exists() and dest.stat().st_size > 1000:
        log.info(f"Resume already downloaded: {dest}")
        return str(dest)
    log.info(f"Downloading resume from Google Drive...")
    try:
        urllib.request.urlretrieve(RESUME_DOWNLOAD_URL, str(dest))
        log.info(f"Resume downloaded: {dest} ({dest.stat().st_size} bytes)")
        return str(dest)
    except Exception as e:
        log.error(f"Failed to download resume: {e}")
        return str(RESUME_PATH)  # fallback

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


def _login(page: Page, context: BrowserContext):
    """Log in to LinkedIn using cookie (preferred) or username/password."""

    # ── Method 1: Cookie-based auth (bypasses all challenges) ──
    if LINKEDIN_COOKIE:
        log.info("Logging in to LinkedIn via li_at cookie...")
        # Set cookie on .linkedin.com (covers www.linkedin.com and all subdomains)
        context.add_cookies([
            {
                "name": "li_at",
                "value": LINKEDIN_COOKIE,
                "domain": ".linkedin.com",
                "path": "/",
            },
        ])
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
        human_delay(2.0)

        url = page.url
        if any(path in url for path in ["/feed", "/jobs", "/mynetwork", "/messaging", "/in/"]):
            log.info("LinkedIn cookie login successful.")
            return
        else:
            log.warning(f"Cookie login redirected to {url} — cookie may be expired.")
            if LINKEDIN_EMAIL and LINKEDIN_PASSWORD:
                log.info("Falling back to username/password login...")
            else:
                raise Exception("LinkedIn cookie expired and no username/password configured.")

    # ── Method 2: Username/password (fallback) ────────────────
    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        raise Exception("No LinkedIn credentials configured (need LINKEDIN_COOKIE or EMAIL+PASSWORD).")

    log.info("Logging in to LinkedIn via username/password...")
    page.goto(LINKEDIN_LOGIN_URL, wait_until="domcontentloaded")
    human_delay(1.0)

    page.fill('input#username', LINKEDIN_EMAIL)
    human_delay(0.5)
    page.fill('input#password', LINKEDIN_PASSWORD)
    human_delay(0.5)
    page.click('button[type="submit"]')

    # Wait for navigation — LinkedIn may redirect to /feed/, /jobs/, /check/, etc.
    for _ in range(60):  # poll for up to 60 seconds
        human_delay(0.5)
        url = page.url
        log.info(f"Post-login URL: {url}")

        # Success — we're past the login page
        if any(path in url for path in ["/feed", "/jobs", "/mynetwork", "/messaging", "/in/"]):
            log.info("LinkedIn login successful.")
            human_delay(1.0)
            return

        # Security checkpoint
        if any(path in url for path in ["/checkpoint", "/challenge", "/authwall"]):
            log.warning(f"LinkedIn security challenge detected: {url}")
            log.warning("Set LINKEDIN_COOKIE instead. See logs for instructions.")
            raise Exception(f"LinkedIn security challenge at: {url}")

        # Still on login page
        if "/login" in url or "/uas/login" in url:
            error_el = page.locator('#error-for-password, .form__label--error, [data-error]').first
            if error_el.is_visible(timeout=1000):
                error_text = error_el.inner_text(timeout=1000)
                raise Exception(f"LinkedIn login failed — bad credentials: {error_text}")
            continue

    raise Exception("LinkedIn login timed out — never reached a logged-in page.")


def _get_job_cards(page: Page) -> list[dict]:
    """Extract visible job cards from the search results page.
    Uses multiple fallback strategies including a JS-based generic extractor."""
    jobs = []

    log.info(f"Search results URL: {page.url}")

    # ── Scroll the results pane aggressively to trigger lazy loading ──
    for scroll_pass in range(3):
        try:
            page.evaluate("""
                (() => {
                    const containers = document.querySelectorAll(
                        '.jobs-search-results-list, .scaffold-layout__list, ' +
                        '.scaffold-layout__list-container, [role="list"], ' +
                        '.jobs-search-results, .scaffold-layout__list-detail-inner'
                    );
                    for (const c of containers) { c.scrollTop += 800; }
                    window.scrollBy(0, 600);
                })()
            """)
            human_delay(0.8)
        except Exception:
            pass

    # ── Strategy 1: CSS selector-based card extraction ──
    CARD_SELECTORS = [
        # 2025-2026 LinkedIn selectors (most current first)
        'li.scaffold-layout__list-item',
        'li[data-occludable-job-id]',
        'div[data-job-id]',
        'li.ember-view.occludable-update',
        'div.job-card-container',
        'div.job-card-container--clickable',
        '.jobs-search-results__list-item',
        '.job-card-list',
        'ul.scaffold-layout__list-container > li',
        '.jobs-search-two-pane__results-list > li',
        'li.jobs-search-results__list-item',
        # Generic fallbacks
        'main ul > li[class*="job"]',
        'main ul > li[class*="card"]',
        'div[class*="job-card"]',
        'div[class*="jobCard"]',
        'li[class*="result"]',
        '[data-view-name="job-card"]',
        'main ul[role="list"] > li',
        'main div[role="list"] > div',
    ]

    cards = []
    winning_selector = ""
    for selector in CARD_SELECTORS:
        try:
            page.wait_for_selector(selector, timeout=3000)
            found = page.locator(selector).all()
            if found and len(found) >= 1:
                log.info(f"Found {len(found)} cards via selector: {selector}")
                cards = found
                winning_selector = selector
                break
        except Exception:
            continue

    # ── Strategy 2: JavaScript-based generic extraction ──
    if not cards:
        log.info("CSS selectors failed. Trying JS-based job card extraction...")
        try:
            js_jobs = page.evaluate("""
                (() => {
                    const results = [];
                    // Find all links to /jobs/view/
                    const links = document.querySelectorAll('a[href*="/jobs/view/"]');
                    const seen = new Set();
                    for (const link of links) {
                        const href = link.href || link.getAttribute('href') || '';
                        const m = href.match(/\/jobs\/view\/(\d+)/);
                        if (!m) continue;
                        const jobId = m[1];
                        if (seen.has(jobId)) continue;
                        seen.add(jobId);
                        // Walk up to find the card container (li or div parent)
                        let card = link.closest('li') || link.closest('div[class*="card"]') || link.parentElement;
                        const title = link.innerText.trim() || '';
                        // Try to get company and location from siblings/nearby text
                        let company = '';
                        let location = '';
                        if (card) {
                            const spans = card.querySelectorAll('span, div.artdeco-entity-lockup__subtitle, div[class*="company"], div[class*="primary-description"]');
                            for (const span of spans) {
                                const t = span.innerText.trim();
                                if (!t || t === title) continue;
                                if (!company && t.length > 1 && t.length < 100 && !t.includes('Easy Apply') && !t.includes('Promoted')) {
                                    company = t;
                                } else if (!location && company && t.length > 1 && t.length < 100) {
                                    location = t;
                                }
                            }
                        }
                        results.push({
                            title: title,
                            company: company,
                            location: location,
                            url: href.startsWith('http') ? href : 'https://www.linkedin.com' + href,
                            job_id: jobId
                        });
                    }
                    return results;
                })()
            """)
            if js_jobs:
                log.info(f"JS extraction found {len(js_jobs)} job listings.")
                # We still need element handles for clicking, so locate them
                for jj in js_jobs:
                    try:
                        # Find the clickable link element for this job
                        link_selector = f'a[href*="/jobs/view/{jj["job_id"]}"]'
                        el = page.locator(link_selector).first
                        card_el = el.locator('xpath=ancestor::li').first
                        if card_el.count() == 0:
                            card_el = el  # fallback to the link itself
                        jobs.append({
                            "title": jj["title"],
                            "company": jj.get("company", "Unknown") or "Unknown",
                            "location": jj.get("location", ""),
                            "url": jj["url"],
                            "job_id": jj["job_id"],
                            "element": card_el,
                        })
                    except Exception as e:
                        log.debug(f"Couldn't locate element for job {jj['job_id']}: {e}")
                        continue
                if jobs:
                    log.info(f"Parsed {len(jobs)} jobs via JS extraction.")
                    return jobs
        except Exception as e:
            log.warning(f"JS extraction failed: {e}")

    if not cards:
        # ── Debug: log what's actually on the page ──
        try:
            body_text = page.inner_text("body", timeout=5000)[:800]
            log.warning(f"No job cards found. Page text preview:\n{body_text}")
        except Exception:
            pass
        try:
            snippet = page.evaluate("""
                (() => {
                    const el = document.querySelector(
                        '.scaffold-layout__list-container, ' +
                        '.jobs-search-results-list, ' +
                        'main, [role="main"]'
                    );
                    return el ? el.innerHTML.substring(0, 1500) : 'NO_MAIN_ELEMENT';
                })()
            """)
            log.warning(f"Results container HTML:\n{snippet}")
        except Exception:
            pass
        # ── Strategy 3: find ALL <li> under main that contain a /jobs/view link ──
        try:
            fallback_cards = page.locator('main li:has(a[href*="/jobs/view/"])').all()
            if fallback_cards:
                log.info(f"Fallback: found {len(fallback_cards)} <li> with job links.")
                cards = fallback_cards
                winning_selector = 'main li:has(a[href*="/jobs/view/"])'
            else:
                log.warning("No job cards found on page after all strategies.")
                return jobs
        except Exception:
            log.warning("No job cards found on page after all strategies.")
            return jobs

    # ── Parse each card ──
    TITLE_SELECTORS = [
        'a.job-card-container__link strong',
        '.job-card-list__title',
        '.job-card-container__link',
        'a[data-control-name="job_card_title"] strong',
        'a[href*="/jobs/view/"] strong',
        'a[href*="/jobs/view/"] span',
        'a[href*="/jobs/view/"]',
        'a strong',
        'a span',
    ]
    COMPANY_SELECTORS = [
        '.job-card-container__primary-description',
        '.job-card-container__company-name',
        '.artdeco-entity-lockup__subtitle',
        'span.job-card-container__primary-description',
        '.artdeco-entity-lockup__subtitle span',
        'div[class*="company"]',
        'span[class*="company"]',
    ]
    LOCATION_SELECTORS = [
        '.job-card-container__metadata-wrapper',
        '.artdeco-entity-lockup__caption',
        '.job-card-container__metadata-item',
        'li.job-card-container__metadata-item',
        'div[class*="metadata"]',
        'span[class*="location"]',
        'div[class*="location"]',
    ]

    for card in cards:
        try:
            # ── Title ──
            title = ""
            for s in TITLE_SELECTORS:
                try:
                    el = card.locator(s).first
                    if el.count() > 0:
                        title = el.inner_text(timeout=2000).strip()
                        if title:
                            break
                except Exception:
                    continue
            if not title:
                try:
                    title = card.locator("a").first.inner_text(timeout=2000).strip()
                except Exception:
                    continue

            # ── Company ──
            company = ""
            for s in COMPANY_SELECTORS:
                try:
                    el = card.locator(s).first
                    if el.count() > 0:
                        company = el.inner_text(timeout=2000).strip()
                        if company:
                            break
                except Exception:
                    continue

            # ── Location ──
            location = ""
            for s in LOCATION_SELECTORS:
                try:
                    el = card.locator(s).first
                    if el.count() > 0:
                        location = el.inner_text(timeout=2000).strip()
                        if location:
                            break
                except Exception:
                    continue

            # ── Link / job ID ──
            href = ""
            try:
                link_el = card.locator('a[href*="/jobs/view/"]').first
                if link_el.count() > 0:
                    href = link_el.get_attribute("href") or ""
            except Exception:
                pass
            if not href:
                try:
                    href = card.locator("a").first.get_attribute("href") or ""
                except Exception:
                    pass
            if href and not href.startswith("http"):
                href = f"https://www.linkedin.com{href}"

            job_id = card.get_attribute("data-occludable-job-id") or ""
            if not job_id:
                job_id = card.get_attribute("data-job-id") or ""
            if not job_id:
                m = re.search(r"/jobs/view/(\d+)", href)
                job_id = m.group(1) if m else ""

            jobs.append({
                "title": title,
                "company": company or "Unknown",
                "location": location or "",
                "url": href,
                "job_id": job_id,
                "element": card,
            })
        except Exception as e:
            log.debug(f"Failed to parse a job card: {e}")
            continue

    log.info(f"Parsed {len(jobs)} job listings from page.")
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

    # Ensure resume is available
    resume_path = _ensure_resume()

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
                log.info(f"Applied successfully: {job['company']} — {job['title']}")
                # Dismiss the success dialog
                safe_click(page, 'button[aria-label="Dismiss"], button:has-text("Done")', timeout=3000)
                return True
            except Exception:
                log.warning("Submit clicked but success confirmation not detected.")
                safe_click(page, 'button[aria-label="Dismiss"], button:has-text("Done")', timeout=2000)
                log.info(f"Applied successfully (optimistic): {job['company']} — {job['title']}")
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
                file_input.set_input_files(resume_path)
                log.info(f"Resume uploaded from: {resume_path}")
                human_delay(0.5)
            except Exception as e:
                log.warning(f"Resume upload failed: {e}")

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
    if not LINKEDIN_COOKIE and not LINKEDIN_EMAIL:
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
                "--disable-infobars",
                "--window-size=1280,900",
            ],
        )
        context: BrowserContext = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/Toronto",
        )
        # Remove the webdriver flag so LinkedIn doesn't detect automation
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page: Page = context.new_page()

        try:
            _login(page, context)
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

                # Retry logic: up to 3 attempts with 60s timeout
                search_loaded = False
                for attempt in range(1, 4):
                    try:
                        log.info(f"Loading search page (attempt {attempt}/3)...")
                        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                        human_delay(2.5)
                        # Wait for results to appear
                        try:
                            page.wait_for_selector(
                                'a[href*="/jobs/view/"], .jobs-search-results-list, '
                                '.scaffold-layout__list-container, main ul',
                                timeout=15000,
                            )
                        except Exception:
                            pass  # proceed anyway — JS extraction may still work
                        # Scroll to trigger lazy loading
                        page.evaluate("window.scrollBy(0, 300)")
                        human_delay(1.0)
                        search_loaded = True
                        break
                    except Exception as e:
                        log.warning(f"Search page load attempt {attempt}/3 failed: {e}")
                        if attempt < 3:
                            human_delay(3.0)
                        continue

                if not search_loaded:
                    log.error(f"Failed to load search after 3 attempts: '{job_title}' in '{location}'")
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

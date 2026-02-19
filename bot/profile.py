"""
Applicant profile — pre-filled answers for common application fields.
Derived from Sahil Bhatt's resume and research background.
All values are used to auto-fill forms during the application process.
"""

# ── Personal Information ─────────────────────────────────────
FIRST_NAME = "Sahil"
LAST_NAME = "Bhatt"
FULL_NAME = f"{FIRST_NAME} {LAST_NAME}"
EMAIL = ""          # Filled at runtime from config
PHONE = ""          # Set via env var APPLICANT_PHONE

# ── Location & Work Authorization ────────────────────────────
CITY = "Toronto"
STATE_PROVINCE = "Ontario"
COUNTRY = "Canada"
CITIZENSHIP = "Canadian Citizen"
WORK_AUTHORIZATION = "Yes"          # Authorized to work in Canada
SPONSORSHIP_REQUIRED = "No"         # Does not require sponsorship
OCI_HOLDER = True                   # Overseas Citizen of India — can work in India

# ── Education ────────────────────────────────────────────────
HIGHEST_DEGREE = "Master's"
DEGREE_TITLE = "Master of Applied Science (MASc) in Mechanical and Industrial Engineering"
UNIVERSITY = "Toronto Metropolitan University"
GRADUATION_YEAR = "2024"

# ── Experience ───────────────────────────────────────────────
YEARS_OF_EXPERIENCE = "3"           # Approx. total professional + research
CURRENT_TITLE = "Research Scientist"

# ── Skills & Keywords ────────────────────────────────────────
PRIMARY_SKILLS = [
    "Operations Research",
    "Mathematical Optimization",
    "Reinforcement Learning",
    "Mixed-Integer Programming",
    "Linear Programming",
    "Python",
    "Gurobi",
    "Machine Learning",
    "Data Science",
    "Stochastic Optimization",
]

# ── Target Job Titles (used for search queries) ─────────────
TARGET_JOB_TITLES = [
    "Optimization Engineer",
    "Operations Research Scientist",
    "Applied Scientist",
    "Research Scientist Machine Learning",
    "Data Scientist Optimization",
    "Data Scientist Logistics",
    "Data Scientist Supply Chain",
    "Data Scientist Routing",
    "Operations Research Analyst",
    "Mathematical Optimization Engineer",
    "Supply Chain Data Scientist",
    "Quantitative Research Scientist",
    "Decision Scientist",
]

# ── Locations to Search ─────────────────────────────────────
SEARCH_LOCATIONS = [
    "Toronto, ON",
    "Canada",
    "Remote",
    "United States",         # many OR roles are US-remote friendly
    "India",                 # OCI eligible
]

# ── Screening Question Auto-Answers ─────────────────────────
# Maps common question keywords → answers.  The bot fuzzy-matches
# the question text against these keys (case-insensitive).
SCREENING_ANSWERS = {
    # Work authorization
    "authorized to work": "Yes",
    "legally authorized": "Yes",
    "work authorization": "Yes",
    "eligible to work": "Yes",
    "require sponsorship": "No",
    "need sponsorship": "No",
    "visa sponsorship": "No",
    "immigration sponsorship": "No",

    # Relocation
    "willing to relocate": "Yes",
    "open to relocation": "Yes",
    "relocate": "Yes",

    # Remote
    "remote work": "Yes",
    "work remotely": "Yes",
    "comfortable working remotely": "Yes",

    # Education
    "highest level of education": "Master's Degree",
    "degree": "Master's Degree",
    "education level": "Master's Degree",
    "bachelor": "Yes",
    "master": "Yes",
    "phd": "No",

    # Experience
    "years of experience": YEARS_OF_EXPERIENCE,
    "years of relevant experience": YEARS_OF_EXPERIENCE,
    "how many years": YEARS_OF_EXPERIENCE,

    # Skills
    "python": "Yes",
    "machine learning": "Yes",
    "optimization": "Yes",
    "gurobi": "Yes",
    "sql": "Yes",
    "data analysis": "Yes",
    "r programming": "No",

    # Availability
    "start date": "Immediately",
    "earliest start": "Immediately",
    "available to start": "Immediately",
    "notice period": "Immediately",

    # Salary (flexible per user instruction)
    "salary expectation": "Open to discussion",
    "expected salary": "Open to discussion",
    "desired salary": "Open to discussion",
    "compensation": "Open to discussion",

    # Gender / demographics (optional, decline)
    "gender": "Prefer not to say",
    "race": "Prefer not to say",
    "ethnicity": "Prefer not to say",
    "veteran": "No",
    "disability": "Prefer not to say",

    # Misc
    "cover letter": "",
    "linkedin": "https://www.linkedin.com/",
    "website": "",
    "portfolio": "",
    "referred by": "",
    "how did you hear": "LinkedIn",
}


def get_answer_for_question(question_text: str) -> str | None:
    """Return the best pre-configured answer for a screening question,
    or None if no match is found (the bot will skip that field)."""
    q = question_text.lower().strip()
    for keyword, answer in SCREENING_ANSWERS.items():
        if keyword.lower() in q:
            return answer
    return None

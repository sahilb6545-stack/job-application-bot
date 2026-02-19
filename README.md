# Job Application Automation Bot

Fully automated bot that applies to jobs on **LinkedIn** (Easy Apply) and **Indeed** continuously — checking for new jobs and applying **every 10 minutes, 24/7**. Runs as a persistent always-on service on **Fly.io** (free tier) while your computer is off.

---

## What It Does

| Feature | Details |
|---|---|
| **Always-On** | Runs 24/7 as a persistent container on Fly.io — never stops |
| **10-Min Cycles** | Checks for and applies to new jobs every 10 minutes |
| **Job Search** | Searches 13 target role titles across 5 locations on both platforms |
| **Auto-Apply** | Fills every form field, uploads your resume PDF, clicks Submit |
| **Email Alerts** | Sends you a confirmation email per application + a summary |
| **Application Log** | Tracks every submission in `data/applications.csv` |
| **Duplicate Check** | Never applies to the same job URL twice |
| **Health Check** | HTTP endpoint on port 8080 — Fly.io auto-restarts if it dies |
| **Auto-Deploy** | Push to GitHub → GitHub Actions auto-deploys to Fly.io |
| **Zero Maintenance** | Once deployed, it runs indefinitely with no interaction |

---

## Quick Setup (≈ 15 minutes)

### 1. Create a **private** GitHub repository

```bash
cd job_application_automation
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/job-application-bot.git
git push -u origin main
```

> **Important:** Use a **private** repo — your credentials will be stored as encrypted secrets, but the code and application log should stay private.

### 2. Set up Fly.io (free account)

1. **Sign up** at [fly.io](https://fly.io) (free tier — no credit card required for small apps)
2. **Install flyctl:**
   ```bash
   # Windows (PowerShell)
   powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"
   
   # macOS / Linux
   curl -L https://fly.io/install.sh | sh
   ```
3. **Log in:**
   ```bash
   fly auth login
   ```
4. **Launch the app** (from your repo folder):
   ```bash
   fly launch --name job-application-bot --region yyz --no-deploy
   ```
   When prompted, accept the defaults. Choose **no** for databases.

5. **Set your secrets** on Fly.io:
   ```bash
   fly secrets set \
     LINKEDIN_EMAIL="your_linkedin@email.com" \
     LINKEDIN_PASSWORD="your_linkedin_password" \
     INDEED_EMAIL="your_indeed@email.com" \
     INDEED_PASSWORD="your_indeed_password" \
     SMTP_EMAIL="your_gmail@gmail.com" \
     SMTP_PASSWORD="your_gmail_app_password" \
     NOTIFY_EMAIL="your_email@example.com" \
     APPLICANT_PHONE="your_phone_number"
   ```

6. **Deploy:**
   ```bash
   fly deploy
   ```

That's it. The bot is now running 24/7.

### 3. Enable auto-deploy from GitHub (optional but recommended)

This lets you push code changes and have them deploy automatically:

1. Generate a Fly.io deploy token:
   ```bash
   fly tokens create deploy
   ```
2. Copy the token.
3. In your GitHub repo, go to **Settings → Secrets and variables → Actions → New repository secret**
4. Add a secret named `FLY_API_TOKEN` with the token as the value.
5. Now every push to `main` auto-deploys to Fly.io.

### Getting a Gmail App Password

1. Go to [myaccount.google.com](https://myaccount.google.com)
2. Enable **2-Step Verification** if not already on
3. Go to **Security → App passwords** (or [direct link](https://myaccount.google.com/apppasswords))
4. Generate a new app password for "Mail"
5. Use that 16-character password as `SMTP_PASSWORD`

---

## How It Works

```
┌──────────────────────────────────────────────────┐
│          Fly.io (always-on container)             │
│                                                   │
│  main.py  ──  persistent loop (every 10 min)      │
│   │                                               │
│   ├── LinkedIn Bot (Playwright + Chromium)        │
│   │    ├── Login                                  │
│   │    ├── Search 13 job titles × 5 locations     │
│   │    ├── Filter → Easy Apply only               │
│   │    ├── Fill forms + upload resume              │
│   │    └── Submit + log + email                   │
│   │                                               │
│   ├── Indeed Bot (Playwright + Chromium)          │
│   │    ├── Login                                  │
│   │    ├── Search 13 job titles × 5 locations     │
│   │    ├── Filter → Indeed Apply only             │
│   │    ├── Fill forms + upload resume              │
│   │    └── Submit + log + email                   │
│   │                                               │
│   ├── Summary email                               │
│   └── Sleep 10 min → repeat                       │
│                                                   │
│  :8080  ←  health check endpoint                  │
│  data/applications.csv  ←  persistent log         │
└──────────────────────────────────────────────────┘
         ↑ auto-deployed via GitHub Actions
```

### Target Job Titles Searched

- Optimization Engineer
- Operations Research Scientist
- Applied Scientist
- Research Scientist Machine Learning
- Data Scientist Optimization
- Data Scientist Logistics
- Data Scientist Supply Chain
- Data Scientist Routing
- Operations Research Analyst
- Mathematical Optimization Engineer
- Supply Chain Data Scientist
- Quantitative Research Scientist
- Decision Scientist

### Locations Searched

- Toronto, ON
- Canada
- Remote
- United States
- India (OCI eligible)

---

## Configuration

All settings are controlled via environment variables (set via `fly secrets set` or in `.env` locally):

| Variable | Default | Description |
|---|---|---|
| `CYCLE_INTERVAL_SECONDS` | `600` | Time between cycles (600 = 10 min) |
| `MAX_APPLICATIONS_PER_RUN` | `50` | Cap per cycle |
| `ACTION_DELAY_SECONDS` | `3` | Base delay between actions (±30% jitter) |
| `PREFERRED_LOCATION` | `Toronto, ON, Canada` | Primary location preference |
| `PREFER_REMOTE` | `true` | Prioritize remote roles |

To change the cycle interval:
```bash
fly secrets set CYCLE_INTERVAL_SECONDS=300   # every 5 min
```

---

## Screening Question Handling

The bot auto-answers common screening questions:

- **Work authorization** → Yes (Canadian citizen)
- **Sponsorship required** → No
- **Willing to relocate** → Yes
- **Remote work** → Yes
- **Education** → Master's Degree
- **Years of experience** → 3
- **Start date** → Immediately
- **Salary expectations** → Open to discussion

See `bot/profile.py` to customize any of these defaults.

---

## Tracking Applications

Every application is logged to `data/applications.csv` with:

- Timestamp, Platform, Job Title, Company, Location, URL, Status

The CSV lives inside the Fly.io container. To download it:
```bash
fly ssh console -C "cat /app/data/applications.csv" > applications.csv
```

## Monitoring

The bot exposes a health check at `https://job-application-bot.fly.dev/`:
```json
{"status":"sleeping","started_at":"2026-02-19T...","last_cycle":"...","total_applied":42,"cycles":15}
```

View live logs:
```bash
fly logs
```

---

## Running Locally (Optional)

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env    # edit with your credentials
python main.py          # persistent mode (runs forever)
python main.py --once   # single cycle then exit
```

---

## Managing the Service

```bash
# View live logs
fly logs

# SSH into the container
fly ssh console

# Restart the service
fly apps restart

# Scale down (pause)
fly scale count 0

# Scale back up (resume)
fly scale count 1

# Update secrets
fly secrets set KEY=NEW_VALUE

# Redeploy after code changes
fly deploy        # or just push to main (auto-deploys)
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| LinkedIn blocks login | LinkedIn may require CAPTCHA or email verification. Log in manually once from a browser first, then retry. |
| Indeed CAPTCHA | Indeed rate-limits bots. Reduce `MAX_APPLICATIONS_PER_RUN` or increase `ACTION_DELAY_SECONDS` via `fly secrets set`. |
| Gmail won't send | Make sure you're using an **App Password**, not your regular Gmail password. |
| No applications submitted | Check `fly logs` for error details. The bot logs every step. |
| Container keeps crashing | Likely out of memory. Confirm VM is set to 512MB in `fly.toml`. |
| Service stopped | Run `fly status` to check. Restart with `fly apps restart`. |
| Auto-deploy not working | Ensure `FLY_API_TOKEN` secret is set in your GitHub repo. |

---

## File Structure

```
job_application_automation/
├── .github/workflows/apply_jobs.yml   ← Auto-deploy to Fly.io on push
├── bot/
│   ├── __init__.py
│   ├── config.py          ← Environment variable loader
│   ├── profile.py         ← Your profile, skills, screening answers
│   ├── linkedin_bot.py    ← LinkedIn Easy Apply automation
│   ├── indeed_bot.py      ← Indeed Apply automation
│   ├── email_notifier.py  ← Gmail SMTP notifications
│   ├── logger.py          ← CSV application tracker
│   └── utils.py           ← Shared helpers (delays, safe clicks)
├── data/
│   └── applications.csv   ← Application log (inside container)
├── Dockerfile             ← Container image (Python + Chromium)
├── fly.toml               ← Fly.io deployment config
├── main.py                ← Persistent service (loop + health check)
├── requirements.txt
├── .env.example           ← Template for local runs
├── .gitignore
├── Sahil_Bhatt_Resume.pdf
└── README.md
```

# Deploying InsightAgent (free tier)

Stack: **Neon** (hosted PostgreSQL) + **Streamlit Community Cloud** (app hosting).
Both have free tiers. Nothing here needs your local machine to stay on.

## 1. Create the database (Neon)

1. Sign up at neon.tech and create a project (PostgreSQL 16).
2. Copy the connection string (owner role). It looks like
   `postgresql://user:password@host/dbname?sslmode=require`.

## 2. Load the data (once, from your computer)

Put the Olist CSVs in `data/raw/`, then run in PowerShell:

```powershell
$env:DATABASE_URL="postgresql://user:password@host/dbname?sslmode=require"
python app/db/load_data.py
```

## 3. Create the read-only role (recommended)

AI-generated SQL then runs with a role that physically cannot write.

```powershell
psql "$env:DATABASE_URL" -v ro_password=YourStrongPassword123 -f app/db/create_readonly_role.sql
```

Build the read-only URL by replacing the user and password in the connection
string with `insightagent_ro` and the password you chose.

## 4. Deploy the app (Streamlit Community Cloud)

1. Push the repo to GitHub (`.env` must NOT be committed).
2. share.streamlit.io -> New app -> pick the repo, branch `main`,
   main file `app/ui/dashboard.py`.
3. Advanced settings -> Secrets (TOML). Secrets are exposed as environment
   variables, which is what the app reads:

```toml
GEMINI_API_KEY = "..."
DATABASE_URL = "postgresql://owner:password@host/dbname?sslmode=require"
READONLY_DATABASE_URL = "postgresql://insightagent_ro:password@host/dbname?sslmode=require"
APP_PASSWORD = "choose-a-password"
MAX_QUESTIONS_PER_SESSION = "30"
# PRIVACY_MODE = "strict"
# TELEGRAM_BOT_TOKEN = "..."
# TELEGRAM_CHAT_ID = "..."
```

## 5. Before you share the link publicly

- Set `APP_PASSWORD` (or share the link only with people you trust). Without
  it anyone can spend your Gemini quota.
- Keep `MAX_QUESTIONS_PER_SESSION` low. It is per browser session, not a
  global budget; set a quota/billing cap on your Gemini key as the real limit.
- The sample dataset is public Olist data. Do not point a public deployment at
  private company data: SQL generation sends the schema and the question to
  Gemini, and narration (if enabled) sends result rows. Use
  `PRIVACY_MODE=strict` to disable narration.
- The Live monitor uses a simulated stream in its own `live` schema; it
  never touches the real tables.

## Run with Docker instead

```powershell
docker compose up -d db                      # database only
docker compose --profile app up --build      # database + app on :8501
```

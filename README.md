# InsightAgent: AI Data Analyst

Ask business questions in plain English and get safe, read-only SQL, results,
charts and explanations. Beyond Q&A it tracks KPIs, explains *why* revenue
changed, flags anomalies, forecasts, and monitors a live order stream with
alerts.

Built on the public [Olist Brazilian E-commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
(about 100k orders, 8 relational tables).

## Features

| Tab | What it does |
|---|---|
| **Ask** | Text-to-SQL with Gemini, grounded in the live schema and explicit business definitions. Follow-up questions ("now by state") use your last 3 questions as context. Optional AI summary of the result. |
| **KPI dashboard** | Revenue, orders, AOV, delivery time, on-time rate, cancel rate with date / category / state filters and deltas vs the previous period. |
| **Root cause** | Pick a month; compares it with the previous month and attributes the change to categories, states and operations (volume vs value effect). Findings are computed deterministically; AI narration is optional. |
| **Forecast & anomalies** | Robust (median/MAD) anomaly detection with adjustable sensitivity; Holt-trend revenue forecast that is **backtested against a naive baseline** and warns when it does not beat it. |
| **Live monitor** | A simulated order stream (separate `live` schema) with threshold alerts, cooldown, and Telegram or console delivery. Trigger cancel spikes, delivery delays or traffic drops to watch alerts fire. |
| **Usage** | Questions asked, answered rate, self-corrections, latency (avg / p95), recent alerts, from the audit log. |

### Safety and reliability

- **SQL guardrails** (sqlglot AST): one statement, `SELECT` / read-only `WITH`
  only, no DDL/DML, no system catalogs, no non-public schemas, a table
  allow-list read from the database, a block list of dangerous functions.
- **Defence in depth:** read-only transaction, 10 s statement timeout, 1,000 row
  cap, optional dedicated read-only database role.
- **Self-correction:** rejected or failing SQL is sent back to the model with the
  error (up to 3 attempts).
- **Audit log** of every question in `app_meta.query_audit`.
- **Deployment controls:** optional shared password (`APP_PASSWORD`) and a
  per-session question cap (`MAX_QUESTIONS_PER_SESSION`).
- **Privacy:** SQL generation sends the schema and your question to Gemini.
  Result rows or analysis facts are sent **only** if you click an AI summary /
  narration button, and never when `PRIVACY_MODE=strict`.

## Architecture

```
Question (+ last 3 turns)
   |
   v
Schema context + business definitions  ->  Gemini  ->  SQL
   |
   v
Validator (sqlglot) --rejected--> error back to Gemini (max 3 attempts)
   |
   v
Read-only execution (timeout, row cap) --DB error--> error back to Gemini
   |
   v
Results, chart, optional summary          Audit log
```

```
app/
  llm/        sql_generator (prompts, Gemini), narrator (opt-in summaries)
  sql/        validator (guardrails), executor (read-only)
  analytics/  kpi, anomaly, forecast, rca
  db/         connection, schema introspection, loaders, schema.sql, runner
  ui/         dashboard (tabbed shell) + one module per tab, access control
  live.py     simulator, windows, alert rules, dispatch
  alerts.py   Telegram / console delivery
  pipeline.py generate -> validate -> execute -> repair loop
  audit.py, usage.py, memory.py, metrics.py
evaluation/   50-question benchmark and runner
scripts/      order_simulator.py (live stream from the terminal)
tests/        unit + DB tests on deterministic synthetic data
docs/         DEPLOYMENT.md
```

## Setup (Windows PowerShell)

Prerequisites: Python 3.10+, Docker Desktop, a Gemini API key.

```powershell
git clone https://github.com/bandarusiva955/insight-agent.git
cd insight-agent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env     # edit .env with your values
docker compose up -d db    # starts PostgreSQL
```

Download the Olist CSVs from Kaggle into `data/raw/` (not in this repo), then:

```powershell
python app/db/load_data.py
```

Recommended read-only role (letters and digits only in the password):

```powershell
Get-Content app/db/create_readonly_role.sql | docker exec -i insightagent-db psql -U <POSTGRES_USER> -d <POSTGRES_DB> -v ro_password=YourStrongPassword123
```

Then set `POSTGRES_READONLY_USER` / `POSTGRES_READONLY_PASSWORD` in `.env`.

## Run

```powershell
python -m streamlit run app/ui/dashboard.py
```

Optional: drive the live monitor from a terminal instead of the buttons:

```powershell
python scripts/order_simulator.py --rate 3 --interval 2
python scripts/order_simulator.py --incident cancel_spike --duration 60
```

Deploy for free (Neon + Streamlit Cloud): see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Tests

```powershell
$env:GEMINI_API_KEY="test-key"
python -m pytest                       # unit tests; DB tests skip without a test DB
```

Database tests use deterministic synthetic Olist-shaped data with planted
events (a category collapse, an order spike) so analytics are checked against
known ground truth. They need a **separate** database whose name contains
`test` (it is wiped on each run):

```powershell
$env:TEST_DATABASE_URL="postgresql://user:pass@127.0.0.1:5432/insightagent_test"
python -m pytest
```

## Evaluation

A 50-question benchmark (aggregation, filtering, joins, time, ranking, ratios,
multi-step) compares the **results** of Gemini's SQL with reference SQL.

```powershell
python -m evaluation.run_eval --dry-run     # checks reference queries only, no API calls
python -m evaluation.run_eval --limit 10    # real run on a few questions
python -m evaluation.run_eval               # full run, writes evaluation/results/latest.md
```

**No accuracy number is claimed here.** The benchmark has not been run
against the real data and a live Gemini key in this repository's history; the
figure goes in this section only after you run it and commit `latest.md`.

## Known limitations

- Single dataset; no CSV/Excel upload yet.
- No user accounts or per-user data separation; the password gate is a shared
  secret, not authentication.
- The live stream is simulated, not connected to a real order system.
- Forecasts use a simple Holt trend model and are only as good as the backtest
  says; the app shows that comparison.
- Cost per query is not measured.

## Roadmap

- [x] Text-to-SQL, guardrails, read-only execution, self-correction, audit log
- [x] KPI dashboard, follow-up memory, root-cause analysis, anomalies, forecast
- [x] Live monitor with alerts, usage tab, 50-question benchmark, Docker, CI
- [ ] Publish measured benchmark results
- [ ] CSV/Excel upload with per-workspace data
- [ ] Authentication and roles
- [ ] Editable metric dictionary

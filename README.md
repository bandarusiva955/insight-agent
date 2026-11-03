# InsightAgent: AI Data Analyst

Ask business questions in plain English. InsightAgent turns them into safe,
read-only PostgreSQL queries, runs them, and returns the SQL, a results table,
an automatic chart and business insights.

Built on the public [Olist Brazilian E-commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
(about 100k orders across 8 relational tables).

> Status: working prototype, under active development. See the roadmap below
> for what is and is not built yet.

## What it does today

- **Text-to-SQL** with Gemini, grounded in the live database schema and explicit
  business definitions (for example: sales = item price of delivered orders,
  freight excluded).
- **SQL guardrails** (sqlglot AST validation): one statement only, `SELECT`
  and read-only `WITH` queries only, no DDL/DML, no system catalogs, no
  non-public schemas, a table allow-list taken from the database, and a block
  list of dangerous functions (`pg_sleep`, `pg_read_file`, `set_config`, ...).
- **Defence in depth at execution time:** read-only transaction, 10 s statement
  timeout, 3 s lock timeout, 1,000 row cap, and optional dedicated read-only
  database role.
- **Self-correction:** if the SQL is rejected or fails in PostgreSQL, the error
  is sent back to the model to repair it (up to 3 attempts).
- **Audit log:** every question, SQL, status, attempt count and latency is
  stored in `app_meta.query_audit`.
- **Streamlit UI:** generated SQL, formatted results (R$), automatic chart
  selection and summary insights computed from the returned rows.

## Architecture

```
Question
   |
   v
Schema context (cached)  +  business definitions (app/metrics.py)
   |
   v
Gemini  ->  SQL
   |
   v
Validator (sqlglot)  --rejected-->  error fed back to Gemini (max 3 attempts)
   |
   v
Read-only execution (timeout, row cap)  --DB error-->  error fed back to Gemini
   |
   v
Results + chart + insights        Audit log (app_meta.query_audit)
```

```
app/
  llm/sql_generator.py   prompt building, Gemini calls, SQL repair
  sql/validator.py       AST-based guardrails
  sql/executor.py        read-only execution
  db/                    connection, schema introspection, loaders, schema.sql
  pipeline.py            generate -> validate -> execute -> repair loop
  audit.py               audit log
  metrics.py             business definitions shared by prompt and UI
  ui/                    Streamlit dashboard and display helpers
tests/                   unit tests (no DB/API key) and integration tests
```

## Setup (Windows PowerShell)

Prerequisites: Python 3.10+, Docker Desktop, a Gemini API key.

```powershell
git clone https://github.com/bandarusiva955/insight-agent.git
cd insight-agent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env     # then edit .env with your values
docker compose up -d       # starts PostgreSQL
```

Download the Olist CSV files from Kaggle into `data/raw/` (they are not
included in this repository), then load them:

```powershell
python app/db/load_data.py
```

### Recommended: read-only database role

```powershell
# letters and digits only; the password is passed in, never stored in the file
Get-Content app/db/create_readonly_role.sql | docker exec -i insightagent-db psql -U <POSTGRES_USER> -d <POSTGRES_DB> -v ro_password=YourStrongPassword123
```

Then set `POSTGRES_READONLY_USER` and `POSTGRES_READONLY_PASSWORD` in `.env`.
Without them the app still works, using the owner connection inside a
read-only transaction.

## Run

```powershell
python -m streamlit run app/ui/dashboard.py
```

Example questions:

- Show me the top 10 product categories by delivered sales.
- What is the monthly order trend?
- Which payment method is used most frequently?
- What is the average delivery time?

## Tests

```powershell
# Unit tests: no database or API key required
$env:GEMINI_API_KEY="test-key"
python -m pytest tests/test_validator_unit.py tests/test_pipeline_retry.py

# Integration tests: need the running database and a real Gemini key
python -m pytest tests/test_pipeline.py tests/test_sql_accuracy.py
```

## Security notes

- Secrets live in `.env` (git-ignored). Never commit it.
- Only the database schema and business definitions are sent to the LLM, not
  table rows.
- Generated SQL can read only the public business tables.

## Roadmap

- [x] Text-to-SQL, guardrails, read-only execution, charts, insights
- [x] Self-correction loop, audit log, read-only role support
- [ ] KPI dashboard with filters
- [ ] Follow-up question memory
- [ ] CSV/Excel upload and per-workspace data
- [ ] Metric dictionary editable in the UI
- [ ] Root-cause analysis agent, anomaly detection, forecasting
- [ ] Authentication, roles, usage limits
- [ ] Evaluation benchmark (execution accuracy, latency, cost per query)
- [ ] Public deployment

## Evaluation

A benchmark has not been run yet. Accuracy figures will be added here only
after they are measured.

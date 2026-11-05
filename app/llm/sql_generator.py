import os
import re

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.db.schema_context import get_schema_context
from app.memory import build_history_block
from app.metrics import BUSINESS_DEFINITIONS

load_dotenv(override=True)

API_KEY = os.getenv("GEMINI_API_KEY")
PRIMARY_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
FALLBACK_MODEL = "gemini-3.8-flash"

if not API_KEY:
    raise ValueError("GEMINI_API_KEY is missing from .env")

client = genai.Client(
    api_key=API_KEY,
    http_options=types.HttpOptions(timeout=120000)
)


STRICT_SQL_RULES = """STRICT SQL RULES:
- PostgreSQL syntax only.
- Generate only one SELECT or read-only WITH query.
- Never generate data modification or schema modification statements.
- Never invent tables or columns.
- Query only the tables listed in the schema above.
- Return SQL only, without Markdown fences or explanations."""


def clean_sql(raw_text: str) -> str:
    """Remove Markdown fences the model sometimes adds despite instructions."""

    text = (raw_text or "").strip()

    fenced = re.match(
        r"^```(?:sql|postgresql|postgres)?\s*(.*?)\s*```$",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if fenced:
        text = fenced.group(1).strip()

    return text


FOLLOW_UP_RULES = """CONVERSATION CONTEXT (earlier questions in this session):
{history}

FOLLOW-UP RULES:
- If the new question refers to earlier results (for example "that", "those",
  "now by state", "same but for 2018"), build on the most relevant earlier SQL
  and change only what the new question asks for.
- If the new question is independent, ignore the conversation context.
- The earlier SQL is context only. The STRICT SQL RULES still apply."""


def _history_section(history_block: str) -> str:
    if not history_block:
        return ""

    return FOLLOW_UP_RULES.format(history=history_block) + "\n\n"


def build_prompt(question: str, schema: str, history_block: str = "") -> str:
    return f"""
You are a senior PostgreSQL developer building an AI data analyst.

Convert the user's business question into one accurate PostgreSQL query.

DATABASE SCHEMA:
{schema}

{BUSINESS_DEFINITIONS}

{STRICT_SQL_RULES}

{_history_section(history_block)}USER QUESTION:
{question}
"""


def build_repair_prompt(
    question: str,
    schema: str,
    failed_sql: str,
    error_message: str,
    history_block: str = "",
) -> str:
    return f"""
You are a senior PostgreSQL developer building an AI data analyst.

A query you wrote for the question below failed. Fix it and return a
corrected PostgreSQL query that still answers the question.

DATABASE SCHEMA:
{schema}

{BUSINESS_DEFINITIONS}

{STRICT_SQL_RULES}

{_history_section(history_block)}USER QUESTION:
{question}

FAILED SQL:
{failed_sql}

ERROR MESSAGE:
{error_message}

Return only the corrected SQL.
"""


def _call_model(prompt: str) -> str:
    """Send a prompt to Gemini, falling back to a second model on API errors."""

    models_to_try = list(dict.fromkeys([
        PRIMARY_MODEL,
        FALLBACK_MODEL
    ]))

    errors = []

    for model in models_to_try:
        try:
            print(f"Generating SQL with {model}...", flush=True)

            response = client.models.generate_content(
                model=model,
                contents=prompt
            )

            sql = clean_sql(response.text)

            if not sql:
                raise ValueError(
                    f"{model} returned an empty response."
                )

            print(
                f"SQL generated successfully using {model}.",
                flush=True
            )

            return sql

        except APIError as error:
            errors.append(f"{model}: {error}")
            print(
                f"{model} unavailable. Trying fallback...",
                flush=True
            )

    raise RuntimeError(
        "Gemini models are currently unavailable. "
        "Please try again later.\n" + "\n".join(errors)
    )


def generate_sql(question: str, history: list | None = None) -> str:
    """
    Convert a business question into PostgreSQL SQL.

    history: optional earlier turns ({"question", "sql"} dicts) so follow-up
    questions can build on previous queries.
    """

    if not question or not question.strip():
        raise ValueError("Please provide a business question.")

    print("Loading database schema...", flush=True)
    schema = get_schema_context()

    return _call_model(
        build_prompt(question, schema, build_history_block(history or []))
    )


def repair_sql(
    question: str,
    failed_sql: str,
    error_message: str,
    history: list | None = None,
) -> str:
    """Ask the model to fix a query that was rejected or failed to run."""

    schema = get_schema_context()

    return _call_model(
        build_repair_prompt(
            question,
            schema,
            failed_sql,
            error_message,
            build_history_block(history or []),
        )
    )


if __name__ == "__main__":
    question = "Show me the top 10 product categories by sales."

    try:
        sql = generate_sql(question)
        print("\nGENERATED SQL:\n")
        print(sql)

    except Exception as error:
        print(f"\nSQL generation failed: {error}")

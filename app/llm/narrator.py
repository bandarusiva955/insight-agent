"""Optional plain-English narration of results already computed in SQL/pandas.

Narration is opt-in and grounded: the model is given a fact sheet and told to
use nothing else. If narration is disabled (PRIVACY_MODE=strict), or the model
is unavailable, callers get the deterministic text back instead.
"""

import os

from google.genai.errors import APIError

from app.llm.sql_generator import FALLBACK_MODEL, PRIMARY_MODEL, client

MAX_ROWS_SENT = 30

GROUNDING_RULES = """RULES:
- Use ONLY the facts below. Do not add numbers, causes, events or context
  that are not in them.
- Amounts are Brazilian Real (R$).
- Describe where the data changed; do not claim to know why. Use wording such
  as "the data shows" and "is associated with".
- 4 to 7 sentences, plain English for a business owner, no jargon, no markdown
  headings.
- Finish with two short suggestions for what to check next, based only on the
  facts."""


def narration_allowed() -> bool:
    """False when the deployment forbids sending results to an LLM."""

    return os.getenv("PRIVACY_MODE", "").strip().lower() != "strict"


def _generate(prompt: str) -> str:
    errors = []

    for model in dict.fromkeys([PRIMARY_MODEL, FALLBACK_MODEL]):
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            text = (response.text or "").strip()

            if text:
                return text

            errors.append(f"{model}: empty response")

        except APIError as error:
            errors.append(f"{model}: {error}")

    raise RuntimeError("; ".join(errors))


def _narrate(prompt: str, fallback: str) -> tuple:
    """Return (text, used_llm). Never raises."""

    if not narration_allowed():
        return fallback, False

    try:
        return _generate(prompt), True

    except Exception as error:
        print(f"Narration unavailable, using plain findings: {error}", flush=True)

        return fallback, False


def narrate_rca(report) -> tuple:
    """Explain a root-cause report. Falls back to the deterministic findings."""

    fallback = "\n".join(f"- {line}" for line in report.findings)

    prompt = f"""You are a business analyst explaining a change in sales to a
non-technical owner.

{GROUNDING_RULES}

FACTS:
{report.to_context()}
"""

    return _narrate(prompt, fallback)


def summarize_results(question: str, dataframe) -> tuple:
    """Summarise a query result. Falls back to a one-line description."""

    shown = dataframe.head(MAX_ROWS_SENT)
    fallback = (
        f"The query returned {len(dataframe):,} row(s) with columns: "
        f"{', '.join(map(str, dataframe.columns))}."
    )

    prompt = f"""You are a business analyst summarising query results for a
non-technical owner.

{GROUNDING_RULES}

QUESTION: {question}

RESULT ({len(dataframe):,} rows in total, first {len(shown)} shown):
{shown.to_csv(index=False)}
"""

    return _narrate(prompt, fallback)

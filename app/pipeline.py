import time
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy.exc import DBAPIError

from app.audit import log_query
from app.llm.sql_generator import generate_sql, repair_sql
from app.sql.executor import execute_sql

MAX_ATTEMPTS = 3


@dataclass
class PipelineResult:
    sql: str
    dataframe: pd.DataFrame
    attempts: int = 1
    latency_ms: int = 0
    # One entry per failed attempt: {"sql": ..., "error": ...}
    corrections: list = field(default_factory=list)


def _examples_allowed() -> bool:
    """Sample category values go to the LLM unless PRIVACY_MODE=strict."""

    import os

    return os.getenv("PRIVACY_MODE", "").strip().lower() != "strict"


def _error_text(error: Exception) -> str:
    """Short, model-friendly description of why a query failed."""

    if isinstance(error, DBAPIError) and getattr(error, "orig", None):
        message = str(error.orig)
    else:
        message = str(error)

    return message.strip()[:600]


def _is_retryable(error: Exception) -> bool:
    """Rejected SQL and database-side SQL errors can be repaired by the LLM."""

    if isinstance(error, ValueError) and "SQL rejected" in str(error):
        return True

    if isinstance(error, DBAPIError):
        return not error.connection_invalidated

    return False


def run_pipeline_detailed(
    question: str,
    max_attempts: int = MAX_ATTEMPTS,
    history: list | None = None,
    audit: bool = True,
    workspace=None,
) -> PipelineResult:
    """
    Natural language -> SQL -> validated, read-only execution.

    If the SQL is rejected by the validator or fails in PostgreSQL, the error
    is sent back to the model to repair, up to max_attempts total attempts.
    Every question is written to the audit log.

    history: earlier turns ({"question", "sql"} dicts) for follow-up questions.
    audit: set False for evaluation runs so they do not fill the audit log.
    workspace: an uploaded-data Workspace; queries then run only inside it.
    """

    if not question or not question.strip():
        raise ValueError("Please enter a business question.")

    started = time.perf_counter()
    corrections = []
    sql = None

    def elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    try:
        print("\n1. Generating SQL with Gemini...", flush=True)
        extra = {}

        if workspace is not None:
            from app.llm.sql_generator import WORKSPACE_DEFINITIONS
            from app.workspace.store import execute_workspace_sql

            extra = {
                "schema": workspace.schema_context(include_examples=_examples_allowed()),
                "definitions": WORKSPACE_DEFINITIONS,
            }

            def run(statement):
                return execute_workspace_sql(workspace, statement)
        else:
            run = execute_sql

        if history:
            extra["history"] = history

        sql = generate_sql(question, **extra)

        for attempt in range(1, max_attempts + 1):
            print(f"\n2. Generated SQL (attempt {attempt}):")
            print(sql)

            try:
                print("\n3. Validating and executing SQL...", flush=True)
                dataframe = run(sql)

            except Exception as error:
                if not _is_retryable(error) or attempt == max_attempts:
                    raise

                reason = _error_text(error)
                corrections.append({"sql": sql, "error": reason})

                print(
                    f"\nAttempt {attempt} failed: {reason}\n"
                    "Asking the model to correct the SQL...",
                    flush=True,
                )
                sql = repair_sql(question, sql, reason, **extra)
                continue

            print("\n4. Pipeline completed successfully.", flush=True)

            result = PipelineResult(
                sql=sql,
                dataframe=dataframe,
                attempts=attempt,
                latency_ms=elapsed_ms(),
                corrections=corrections,
            )

            if audit:
                log_query(
                    question=question,
                    generated_sql=sql,
                    status="success" if attempt == 1 else "corrected",
                    attempts=attempt,
                    latency_ms=result.latency_ms,
                    row_count=len(dataframe),
                )

            return result

    except Exception as error:
        if audit:
            log_query(
                question=question,
                generated_sql=sql,
                status="failed",
                attempts=len(corrections) + 1,
                latency_ms=elapsed_ms(),
                error=_error_text(error),
            )
        raise


def run_pipeline(question: str):
    """
    Backwards-compatible wrapper: returns (generated_sql, dataframe).
    """

    result = run_pipeline_detailed(question)

    return result.sql, result.dataframe


if __name__ == "__main__":

    question = "Show me the top 10 product categories by sales."

    try:
        sql, dataframe = run_pipeline(question)

        print("\nFINAL RESULTS:")
        print(dataframe.to_string(index=False))

    except Exception as error:
        print(f"\nPipeline failed: {error}")

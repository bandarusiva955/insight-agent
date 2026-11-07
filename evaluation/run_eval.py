"""
Run the benchmark against the live pipeline and write an honest report.

    python -m evaluation.run_eval --dry-run          # check reference SQL only
    python -m evaluation.run_eval --limit 5          # quick smoke run
    python -m evaluation.run_eval                    # all 50 questions

Needs the real database and a Gemini API key. Free-tier Gemini keys are rate
limited, so a pause is added between questions (--delay).

A question is only "evaluated" if Gemini actually answered it. Quota (429),
overload (503) and network errors are NOT counted as wrong SQL: they are
reported as "not evaluated" and excluded from the accuracy rates. Results of
evaluated questions are kept in evaluation/results/state.json, so a run that
hit the daily quota can be continued later with --resume.

Reported numbers (all measured, none estimated; rates are over evaluated
questions only):
  executed        pipeline returned a result
  correct         result matches the reference (after any self-correction)
  first_try       correct on the first attempt, no repair needed
  repaired        correct only because the self-correction loop fixed it
"""

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from evaluation.benchmark import QUESTIONS
from evaluation.compare import results_match

RESULTS_DIR = Path(__file__).resolve().parent / "results"
STATE_FILE = RESULTS_DIR / "state.json"

INFRA_MARKERS = (
    "resource_exhausted", "429", "503", "unavailable", "getaddrinfo",
    "currently unavailable", "timed out", "timeout", "connecterror",
    "connection reset", "temporary failure", "deadline",
)
QUOTA_MARKERS = ("resource_exhausted", "429", "quota")
RETRY_PAUSE_SECONDS = 20
MAX_TRANSIENT_RETRIES = 2
STOP_AFTER_QUOTA_ERRORS = 3


def is_infrastructure_error(message: str | None) -> bool:
    """True for API/network trouble, which says nothing about the SQL quality."""

    text = (message or "").lower()

    return any(marker in text for marker in INFRA_MARKERS)


def is_quota_error(message: str | None) -> bool:
    text = (message or "").lower()

    return any(marker in text for marker in QUOTA_MARKERS)


def status_of(record: dict) -> str:
    """correct | wrong | failed | not_evaluated"""

    if "status" in record:
        return record["status"]

    if record.get("executed"):
        return "correct" if record.get("correct") else "wrong"

    return "not_evaluated" if is_infrastructure_error(record.get("error")) else "failed"


def run_reference(sql: str) -> pd.DataFrame:
    from app.db.runner import run_query

    return run_query(sql)


def dry_run(questions) -> int:
    """Validate every reference query: passes guardrails, runs, returns rows."""

    from app.db.schema_context import get_allowed_tables
    from app.sql.validator import validate_sql

    allowed = get_allowed_tables()
    problems = 0

    for item in questions:
        valid, message = validate_sql(item.sql, allowed_tables=allowed)

        if not valid:
            print(f"{item.id}: REJECTED by validator: {message}")
            problems += 1
            continue

        try:
            rows = len(run_reference(item.sql))
        except Exception as error:
            print(f"{item.id}: reference SQL failed: {error}")
            problems += 1
            continue

        print(f"{item.id}: ok ({rows} row{'s' if rows != 1 else ''})")

    print(f"\n{len(questions) - problems}/{len(questions)} reference queries OK.")

    return problems


def evaluate_one(item, pipeline_run) -> dict:
    record = {
        "id": item.id,
        "category": item.category,
        "question": item.question,
        "status": "failed",
        "executed": False,
        "correct": False,
        "attempts": 0,
        "latency_ms": None,
        "sql": None,
        "error": None,
    }

    started = time.perf_counter()

    try:
        result = pipeline_run(item.question)
    except Exception as error:
        record["latency_ms"] = int((time.perf_counter() - started) * 1000)
        record["error"] = str(error)[:300]
        record["status"] = status_of({"error": record["error"]})
        return record

    record.update(
        executed=True,
        attempts=result.attempts,
        latency_ms=result.latency_ms,
        sql=result.sql,
    )

    expected = run_reference(item.sql)
    record["correct"] = results_match(expected, result.dataframe, item.ordered)
    record["status"] = "correct" if record["correct"] else "wrong"

    return record


def evaluate_with_retry(item, pipeline_run, sleep=time.sleep) -> dict:
    """Retry short Gemini overloads (503); never retry a quota error."""

    record = evaluate_one(item, pipeline_run)

    for attempt in range(1, MAX_TRANSIENT_RETRIES + 1):
        if record["status"] != "not_evaluated" or is_quota_error(record["error"]):
            break

        sleep(RETRY_PAUSE_SECONDS * attempt)
        record = evaluate_one(item, pipeline_run)

    return record


def summarise(records: list) -> dict:
    """Rates are over EVALUATED questions; API/network errors are excluded."""

    evaluated = [r for r in records if status_of(r) != "not_evaluated"]
    total = len(evaluated)

    def rate(count):
        return count / total if total else 0.0

    correct = [r for r in evaluated if status_of(r) == "correct"]
    latencies = [r["latency_ms"] for r in evaluated if r["latency_ms"] is not None]

    by_category = {}

    for record in evaluated:
        bucket = by_category.setdefault(record["category"], [0, 0])
        bucket[0] += 1
        bucket[1] += int(status_of(record) == "correct")

    return {
        "questions": len(records),
        "evaluated": total,
        "not_evaluated": len(records) - total,
        "executed": rate(sum(bool(r["executed"]) for r in evaluated)),
        "correct": rate(len(correct)),
        "first_try": rate(sum(1 for r in correct if r["attempts"] == 1)),
        "repaired": rate(sum(1 for r in correct if r["attempts"] > 1)),
        "avg_attempts": (
            statistics.mean(r["attempts"] for r in evaluated if r["executed"])
            if any(r["executed"] for r in evaluated)
            else None
        ),
        "median_latency_ms": statistics.median(latencies) if latencies else None,
        "p95_latency_ms": (
            sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]
            if latencies
            else None
        ),
        "by_category": {
            name: {"questions": n, "correct": ok, "rate": ok / n}
            for name, (n, ok) in by_category.items()
        },
    }


def markdown_report(summary: dict, records: list, meta: dict) -> str:
    lines = [
        "# Benchmark results",
        "",
        f"- Run at: {meta['run_at']}",
        f"- Model: {meta['model']} (fallback {meta['fallback_model']})",
        f"- Questions in benchmark: {summary['questions']}",
        f"- Evaluated (Gemini actually answered): {summary['evaluated']}",
        f"- Not evaluated (API quota / overload / network): {summary['not_evaluated']}",
        "- Reference: hand-written SQL in `evaluation/benchmark.py`",
        "",
        *(
            [
                f"> **Partial result.** Only {summary['evaluated']} of "
                f"{summary['questions']} questions were evaluated, so the rates below "
                "do not describe the whole benchmark. Do not quote them as overall "
                "accuracy. Re-run with `--resume` when the API quota allows.",
                "",
            ]
            if summary["not_evaluated"]
            else []
        ),
        "| Metric | Value |",
        "|---|---|",
        f"| Executed without error | {summary['executed']:.1%} |",
        f"| Correct (matches reference) | {summary['correct']:.1%} |",
        f"| Correct on first attempt | {summary['first_try']:.1%} |",
        f"| Correct only after self-correction | {summary['repaired']:.1%} |",
        f"| Avg attempts per question | {summary['avg_attempts']:.2f} |"
        if summary["avg_attempts"] is not None
        else "| Avg attempts per question | n/a |",
        f"| Median latency | {summary['median_latency_ms'] / 1000:.1f} s |"
        if summary["median_latency_ms"] is not None
        else "| Median latency | n/a |",
        f"| p95 latency | {summary['p95_latency_ms'] / 1000:.1f} s |"
        if summary["p95_latency_ms"] is not None
        else "| p95 latency | n/a |",
        "",
        "## By category",
        "",
        "| Category | Correct | Questions | Rate |",
        "|---|---|---|---|",
    ]

    for name, row in sorted(summary["by_category"].items()):
        lines.append(
            f"| {name} | {row['correct']} | {row['questions']} | {row['rate']:.0%} |"
        )

    failures = [r for r in records if status_of(r) in ("wrong", "failed")]
    skipped = [r for r in records if status_of(r) == "not_evaluated"]

    lines += ["", f"## Failures ({len(failures)})", ""]

    for record in failures:
        reason = record["error"] or "result differs from reference"
        lines.append(f"- **{record['id']}** {record['question']} ({reason[:200]})")

    if skipped:
        lines += ["", f"## Not evaluated ({len(skipped)})", "",
                  "Gemini API quota, overload or network errors. These say nothing "
                  "about SQL quality: " + ", ".join(r["id"] for r in skipped) + "."]

    lines += [
        "",
        "Cost per query is not measured. Token usage is not recorded yet.",
        "",
    ]

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="only check that reference queries pass and run")
    parser.add_argument("--limit", type=int, default=0, help="first N questions")
    parser.add_argument("--ids", nargs="*", help="run only these ids, e.g. Q01 Q07")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="seconds to wait between questions (API rate limits)")
    parser.add_argument("--resume", action="store_true",
                        help="skip questions already evaluated in earlier runs")
    args = parser.parse_args()

    questions = QUESTIONS

    if args.ids:
        questions = [q for q in questions if q.id in set(args.ids)]
    if args.limit:
        questions = questions[: args.limit]

    if args.dry_run:
        raise SystemExit(1 if dry_run(questions) else 0)

    from app.llm.sql_generator import FALLBACK_MODEL, PRIMARY_MODEL
    from app.pipeline import run_pipeline_detailed

    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    fresh = {}
    quota_streak = 0
    todo = [q for q in questions if not (args.resume and q.id in state)]

    if args.resume:
        print(f"Resuming: {len(questions) - len(todo)} already evaluated, "
              f"{len(todo)} to run.")

    for index, item in enumerate(todo, start=1):
        record = evaluate_with_retry(
            item, lambda q: run_pipeline_detailed(q, audit=False)
        )
        fresh[item.id] = record

        label = {"correct": "OK  ", "wrong": "WRONG", "failed": "FAIL ",
                 "not_evaluated": "SKIP "}[record["status"]]
        print(f"[{index:>2}/{len(todo)}] {label} {item.id} {item.question}")

        quota_streak = quota_streak + 1 if is_quota_error(record["error"]) else 0

        if quota_streak >= STOP_AFTER_QUOTA_ERRORS:
            print("\nStopping: the Gemini API quota is exhausted. Wait for the quota "
                  "to reset (free tier: daily), then run again with --resume.")
            break

        if index < len(todo):
            time.sleep(args.delay)

    # Only evaluated answers are kept as state; skipped ones are retried next time.
    for qid, record in fresh.items():
        if record["status"] != "not_evaluated":
            state[qid] = record

    RESULTS_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

    records = []

    for item in questions:
        if item.id in fresh and fresh[item.id]["status"] == "not_evaluated":
            records.append(fresh[item.id])
        elif item.id in state:
            records.append(state[item.id])
        elif item.id in fresh:
            records.append(fresh[item.id])
        else:
            records.append({
                "id": item.id, "category": item.category, "question": item.question,
                "status": "not_evaluated", "executed": False, "correct": False,
                "attempts": 0, "latency_ms": None, "sql": None,
                "error": "not run (quota exhausted earlier)",
            })

    summary = summarise(records)
    meta = {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "model": PRIMARY_MODEL,
        "fallback_model": FALLBACK_MODEL,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    (RESULTS_DIR / f"{stamp}.json").write_text(
        json.dumps({"meta": meta, "summary": summary, "records": records}, indent=2)
    )
    report = markdown_report(summary, records, meta)
    (RESULTS_DIR / "latest.md").write_text(report)

    print("\n" + report)


if __name__ == "__main__":
    main()

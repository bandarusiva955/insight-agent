"""
Run the benchmark against the live pipeline and write an honest report.

    python -m evaluation.run_eval --dry-run          # check reference SQL only
    python -m evaluation.run_eval --limit 5          # quick smoke run
    python -m evaluation.run_eval                    # all 50 questions

Needs the real database and a Gemini API key. Free-tier Gemini keys are rate
limited, so a pause is added between questions (--delay).

Reported numbers (all measured, none estimated):
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
        return record

    record.update(
        executed=True,
        attempts=result.attempts,
        latency_ms=result.latency_ms,
        sql=result.sql,
    )

    expected = run_reference(item.sql)
    record["correct"] = results_match(expected, result.dataframe, item.ordered)

    return record


def summarise(records: list) -> dict:
    total = len(records)

    def rate(count):
        return count / total if total else 0.0

    correct = [r for r in records if r["correct"]]
    latencies = [r["latency_ms"] for r in records if r["latency_ms"] is not None]

    by_category = {}

    for record in records:
        bucket = by_category.setdefault(record["category"], [0, 0])
        bucket[0] += 1
        bucket[1] += int(record["correct"])

    return {
        "questions": total,
        "executed": rate(sum(r["executed"] for r in records)),
        "correct": rate(len(correct)),
        "first_try": rate(sum(1 for r in correct if r["attempts"] == 1)),
        "repaired": rate(sum(1 for r in correct if r["attempts"] > 1)),
        "avg_attempts": (
            statistics.mean(r["attempts"] for r in records if r["executed"])
            if any(r["executed"] for r in records)
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
        f"- Questions: {summary['questions']}",
        "- Reference: hand-written SQL in `evaluation/benchmark.py`",
        "",
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

    failures = [r for r in records if not r["correct"]]

    lines += ["", f"## Failures ({len(failures)})", ""]

    for record in failures:
        reason = record["error"] or "result differs from reference"
        lines.append(f"- **{record['id']}** {record['question']} ({reason})")

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

    records = []

    for index, item in enumerate(questions, start=1):
        record = evaluate_one(
            item, lambda q: run_pipeline_detailed(q, audit=False)
        )
        records.append(record)

        status = "OK  " if record["correct"] else "FAIL"
        print(f"[{index:>2}/{len(questions)}] {status} {item.id} {item.question}")

        if index < len(questions):
            time.sleep(args.delay)

    summary = summarise(records)
    meta = {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "model": PRIMARY_MODEL,
        "fallback_model": FALLBACK_MODEL,
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    (RESULTS_DIR / f"{stamp}.json").write_text(
        json.dumps({"meta": meta, "summary": summary, "records": records}, indent=2)
    )
    report = markdown_report(summary, records, meta)
    (RESULTS_DIR / "latest.md").write_text(report)

    print("\n" + report)


if __name__ == "__main__":
    main()

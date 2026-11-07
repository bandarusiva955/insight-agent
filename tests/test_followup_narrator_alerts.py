"""Follow-up memory, narration and alert delivery. No database needed."""

import os

os.environ.setdefault("GEMINI_API_KEY", "test-key")

import pandas as pd
import pytest

from app import alerts, memory
from app.llm import narrator, sql_generator


# ---- follow-up memory ----------------------------------------------------

def test_empty_history_gives_no_block():
    assert memory.build_history_block([]) == ""
    assert memory.build_history_block([{"question": "q"}]) == ""


def test_history_block_keeps_only_the_last_turns():
    turns = [{"question": f"q{i}", "sql": f"SELECT {i}"} for i in range(6)]

    block = memory.build_history_block(turns, max_turns=2)

    assert "q4" in block and "q5" in block
    assert "q3" not in block
    assert "SELECT 5" in block


def test_long_sql_is_truncated():
    block = memory.build_history_block(
        [{"question": "q", "sql": "SELECT " + "x" * 5000}]
    )

    assert len(block) < memory.MAX_SQL_CHARS + 200
    assert block.endswith("...")


def test_prompt_includes_context_only_when_history_exists():
    plain = sql_generator.build_prompt("top categories", "SCHEMA")
    with_history = sql_generator.build_prompt(
        "now by state",
        "SCHEMA",
        memory.build_history_block(
            [{"question": "top categories", "sql": "SELECT 1"}]
        ),
    )

    assert "CONVERSATION CONTEXT" not in plain
    assert "CONVERSATION CONTEXT" in with_history
    assert "Q1: top categories" in with_history
    assert with_history.index("CONVERSATION CONTEXT") < with_history.index(
        "USER QUESTION"
    )
    # The safety rules must still be present.
    assert "STRICT SQL RULES" in with_history


def test_repair_prompt_carries_error_and_history():
    prompt = sql_generator.build_repair_prompt(
        "now by state",
        "SCHEMA",
        "SELECT bad",
        'column "bad" does not exist',
        memory.build_history_block([{"question": "q1", "sql": "SELECT 1"}]),
    )

    assert "SELECT bad" in prompt
    assert 'column "bad" does not exist' in prompt
    assert "CONVERSATION CONTEXT" in prompt


def test_pipeline_passes_history_to_the_model(monkeypatch):
    from app import pipeline

    seen = {}

    def fake_generate(question, history=None):
        seen["history"] = history
        return "SELECT 1"

    monkeypatch.setattr(pipeline, "generate_sql", fake_generate)
    monkeypatch.setattr(
        pipeline, "execute_sql", lambda sql: pd.DataFrame({"a": [1]})
    )
    monkeypatch.setattr(pipeline, "log_query", lambda **kwargs: None)

    history = [{"question": "q1", "sql": "SELECT 0"}]
    pipeline.run_pipeline_detailed("now by state", history=history)

    assert seen["history"] == history


# ---- narration -----------------------------------------------------------

class FakeReport:
    findings = ["Revenue fell 10%.", "Biggest category decreases: toys."]

    def to_context(self):
        return "Metric: revenue\n- Revenue fell 10%."


def test_narration_uses_the_model_when_available(monkeypatch):
    prompts = []
    monkeypatch.setattr(
        narrator, "_generate", lambda prompt: prompts.append(prompt) or "Plain story."
    )

    text, used_llm = narrator.narrate_rca(FakeReport())

    assert (text, used_llm) == ("Plain story.", True)
    assert "Revenue fell 10%." in prompts[0]
    assert "Use ONLY the facts below" in prompts[0]


def test_narration_falls_back_to_findings_on_error(monkeypatch):
    def boom(prompt):
        raise RuntimeError("quota")

    monkeypatch.setattr(narrator, "_generate", boom)

    text, used_llm = narrator.narrate_rca(FakeReport())

    assert used_llm is False
    assert "- Revenue fell 10%." in text


def test_strict_privacy_mode_never_calls_the_model(monkeypatch):
    monkeypatch.setenv("PRIVACY_MODE", "strict")
    monkeypatch.setattr(
        narrator,
        "_generate",
        lambda prompt: pytest.fail("model must not be called in strict mode"),
    )

    text, used_llm = narrator.summarize_results(
        "top categories", pd.DataFrame({"a": [1, 2]})
    )

    assert used_llm is False
    assert "2 row(s)" in text
    assert narrator.narration_allowed() is False


def test_result_summary_sends_at_most_the_row_limit(monkeypatch):
    monkeypatch.delenv("PRIVACY_MODE", raising=False)
    prompts = []
    monkeypatch.setattr(
        narrator, "_generate", lambda prompt: prompts.append(prompt) or "ok"
    )

    narrator.summarize_results("q", pd.DataFrame({"n": range(500)}))

    assert "500 rows in total" in prompts[0]
    assert prompts[0].count("\n") < 80


# ---- alerts --------------------------------------------------------------

def test_alert_goes_to_console_without_telegram(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    assert alerts.send_alert("cancel spike") == "console"
    assert "ALERT: cancel spike" in capsys.readouterr().out


def test_alert_uses_telegram_when_configured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, request.data))
        return FakeResponse()

    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)

    assert alerts.send_alert("hello") == "telegram"
    assert calls[0][0] == "https://api.telegram.org/bot123:abc/sendMessage"
    assert b'"chat_id": "42"' in calls[0][1]


def test_telegram_failure_falls_back_and_never_raises(monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")

    def boom(request, timeout):
        raise OSError("network down")

    monkeypatch.setattr(alerts.urllib.request, "urlopen", boom)

    assert alerts.send_alert("hello") == "console"

    output = capsys.readouterr().out
    assert "Telegram alert failed" in output
    assert "secret-token" not in output  # the bot token must never be logged

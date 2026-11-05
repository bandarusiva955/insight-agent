"""Conversation memory for follow-up questions.

The dashboard keeps the last few (question, SQL) pairs. They are added to the
prompt so a question like "now break that down by state" can be answered by
extending the previous query.
"""

MAX_TURNS = 3
MAX_SQL_CHARS = 1500


def build_history_block(turns: list, max_turns: int = MAX_TURNS) -> str:
    """
    Format recent turns for the prompt.

    Each turn is a dict with "question" and "sql". Empty history gives "".
    """

    recent = [t for t in turns if t.get("question") and t.get("sql")][-max_turns:]

    if not recent:
        return ""

    lines = []

    for number, turn in enumerate(recent, start=1):
        sql = turn["sql"].strip()

        if len(sql) > MAX_SQL_CHARS:
            sql = sql[:MAX_SQL_CHARS] + " ..."

        lines.append(f"Q{number}: {turn['question'].strip()}")
        lines.append(f"SQL{number}:\n{sql}")

    return "\n".join(lines)

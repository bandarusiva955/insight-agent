"""
Light access control for a public deployment.

APP_PASSWORD (optional) puts a shared-password gate in front of the app, so
strangers cannot spend your Gemini quota. MAX_QUESTIONS_PER_SESSION caps how
many questions one browser session can ask.

This is NOT user authentication: there are no accounts, roles or per-user
data separation. Real multi-user auth is on the roadmap.
"""

import hmac
import os
import time

import streamlit as st

DEFAULT_QUESTION_LIMIT = 50
WRONG_PASSWORD_DELAY_SECONDS = 1.0


def verify_password(entered: str, expected: str) -> bool:
    """Constant-time comparison."""

    return hmac.compare_digest(entered.encode(), expected.encode())


class QuestionBudget:
    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    def allow(self) -> bool:
        if self.used >= self.limit:
            return False

        self.used += 1

        return True


def question_limit() -> int:
    try:
        return max(1, int(os.getenv("MAX_QUESTIONS_PER_SESSION", "")))
    except ValueError:
        return DEFAULT_QUESTION_LIMIT


def budget_for_session() -> QuestionBudget:
    if "question_budget" not in st.session_state:
        st.session_state["question_budget"] = QuestionBudget(question_limit())

    return st.session_state["question_budget"]


def require_access() -> None:
    """Stop the script until the correct password is entered (if one is set)."""

    expected = os.getenv("APP_PASSWORD")

    if not expected or st.session_state.get("authenticated"):
        return

    st.title("📊 InsightAgent")
    st.caption("This deployment is password protected.")

    entered = st.text_input("Password", type="password")

    if st.button("Enter", type="primary"):
        if verify_password(entered, expected):
            st.session_state["authenticated"] = True
            st.rerun()

        time.sleep(WRONG_PASSWORD_DELAY_SECONDS)
        st.error("Incorrect password.")

    st.stop()

"""Turn raw exceptions into messages a user can act on."""

import re


def friendly_error(error: Exception) -> str:
    text = str(error)
    lower = text.lower()

    if "resource_exhausted" in lower or "429" in lower or "quota" in lower:
        wait = re.search(r"retry in (\d+h)?\s*(\d+m)?", text, flags=re.IGNORECASE)
        hint = ""

        if wait and (wait.group(1) or wait.group(2)):
            hint = f" It should reset in about {' '.join(g for g in wait.groups() if g)}."

        return (
            "The AI service's request quota has been used up for now, so the "
            "question could not be answered." + hint + " The other tabs "
            "(KPI dashboard, My data, Root cause, Forecast, Live monitor) "
            "still work. Try again later, or use an API key with billing enabled."
        )

    if "503" in lower or "unavailable" in lower or "high demand" in lower:
        return (
            "The AI service is busy right now. Please try again in a minute."
        )

    if "getaddrinfo" in lower or "connecterror" in lower or "timed out" in lower:
        return "Could not reach the AI service. Check your internet connection and try again."

    if "sql rejected" in lower:
        return (
            "The generated query was blocked by the safety checks, and the "
            "automatic corrections did not fix it. Try rephrasing the question. "
            f"Details: {text[:300]}"
        )

    return f"Analysis failed: {text[:500]}"

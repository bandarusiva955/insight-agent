"""Self-contained HTML analyst report (open in any browser, print to PDF)."""

from datetime import datetime
from html import escape

import pandas as pd

from app.workspace.cleaning import CleanResult
from app.workspace.dashboard import Dashboard

STYLE = """
body{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:960px;margin:32px auto;padding:0 20px;color:#0f172a;line-height:1.5}
h1{margin-bottom:0}h2{margin-top:36px;border-bottom:2px solid #e2e8f0;padding-bottom:6px}
.sub{color:#64748b}.kpis{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}
.kpi{border:1px solid #e2e8f0;border-radius:10px;padding:12px 16px;min-width:140px}
.kpi b{display:block;font-size:1.4rem}.kpi span{color:#64748b;font-size:.85rem}
table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{border:1px solid #e2e8f0;padding:6px 10px;text-align:left}
th{background:#f1f5f9}.note{color:#64748b;font-size:.85rem;margin-top:30px}
@media print{.chart{break-inside:avoid}}
"""


def build_report(
    title: str,
    source_name: str,
    cleaning: CleanResult,
    board: Dashboard,
    profiles: list,
) -> str:
    parts = [
        f"<h1>{escape(title)}</h1>",
        f"<p class='sub'>Source file: {escape(source_name)} · Generated "
        f"{datetime.now():%Y-%m-%d %H:%M} · InsightAgent</p>",
        "<h2>Key numbers</h2><div class='kpis'>"
        + "".join(f"<div class='kpi'><b>{escape(v)}</b><span>{escape(k)}</span></div>"
                  for k, v in board.kpis)
        + "</div>",
    ]

    if board.findings:
        parts.append("<h2>Key findings</h2><ul>"
                     + "".join(f"<li>{escape(f)}</li>" for f in board.findings) + "</ul>")

    charts = "".join(
        f"<div class='chart'>{fig.to_html(full_html=False, include_plotlyjs='cdn' if i == 0 else False)}</div>"
        for i, (_, fig) in enumerate(board.charts)
    )
    if charts:
        parts.append("<h2>Charts</h2>" + charts)

    parts.append(
        f"<h2>Data cleaning log</h2><p>{cleaning.rows_before:,} rows in, "
        f"{cleaning.rows_after:,} rows out.</p><table><tr><th>Column</th><th>What changed</th></tr>"
        + "".join(f"<tr><td>{escape(s.column or 'whole table')}</td><td>{escape(s.detail)}</td></tr>"
                  for s in cleaning.steps)
        + "</table>"
    )

    parts.append(
        "<h2>Columns</h2><table><tr><th>Column</th><th>Type</th><th>Distinct</th>"
        "<th>Missing</th><th>Examples</th></tr>"
        + "".join(
            f"<tr><td>{escape(p.name)}</td><td>{escape(p.role)}</td><td>{p.nunique:,}</td>"
            f"<td>{p.missing_share:.0%}</td><td>{escape(', '.join(p.examples[:3]))}</td></tr>"
            for p in profiles
        ) + "</table>"
    )

    parts.append(
        "<p class='note'>Figures are computed directly from the cleaned data. "
        "Findings describe associations in this file, not proven causes. Cleaning rules "
        "never delete outliers or fill in missing values; they are only flagged.</p>"
    )

    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{escape(title)}</title>"
        f"<style>{STYLE}</style></head><body>{''.join(parts)}</body></html>"
    )

"""A deliberately messy sales file, with known ground truth."""

import io
import random

import pandas as pd


def messy_sales_frame(seed: int = 5) -> pd.DataFrame:
    rng = random.Random(seed)
    regions = ["North", "South", "East", "West"]
    rows = []

    for i in range(240):
        month = 1 + i % 12
        region = rng.choice(regions)
        amount = round(rng.uniform(20, 500), 2)
        rows.append({
            "Order ID": f"{1000 + i}",
            "Order Date": f"2024-{month:02d}-{1 + i % 27:02d}",
            "Region ": region if i % 7 else region.upper(),
            "Amount ($)": f"${amount:,.2f}",
            "Qty": str(rng.randint(1, 9)),
            "Paid?": rng.choice(["Yes", "No"]),
            "Notes": "N/A" if i % 5 == 0 else "ok",
            "Unused": "",
        })

    frame = pd.DataFrame(rows)
    frame = pd.concat([frame, frame.iloc[:6]], ignore_index=True)  # 6 exact duplicates
    frame.loc[len(frame)] = [""] * frame.shape[1]  # an empty row

    return frame


def messy_sales_csv() -> bytes:
    buffer = io.StringIO()
    messy_sales_frame().to_csv(buffer, index=False)

    return buffer.getvalue().encode("utf-8")

"""Read uploaded CSV / Excel files into DataFrames, with hard limits."""

import io
import re

import pandas as pd

MAX_BYTES = 25 * 1024 * 1024
MAX_ROWS = 200_000
MAX_COLUMNS = 100
MAX_SHEETS = 10

SUPPORTED = (".csv", ".tsv", ".txt", ".xlsx", ".xls")


class UploadError(ValueError):
    """Raised with a message that is safe to show the user."""


def table_name_from(filename: str, sheet: str | None = None) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", filename.rsplit("/", 1)[-1])
    name = f"{stem}_{sheet}" if sheet else stem
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()

    if not name or name[0].isdigit():
        name = f"t_{name}" if name else "data"

    return name[:40]


def _read_csv(data: bytes) -> pd.DataFrame:
    last_error = None

    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return pd.read_csv(
                io.BytesIO(data),
                sep=None,
                engine="python",
                encoding=encoding,
                dtype=str,
                keep_default_na=False,
                nrows=MAX_ROWS + 1,
            )
        except (UnicodeError, UnicodeDecodeError) as error:
            last_error = error
        except pd.errors.EmptyDataError:
            raise UploadError("The file is empty.")
        except pd.errors.ParserError as error:
            raise UploadError(f"Could not parse the file as CSV: {error}")

    raise UploadError(f"Could not read the file encoding: {last_error}")


def read_upload(filename: str, data: bytes) -> dict:
    """Return {table_name: DataFrame of raw strings/objects}."""

    if len(data) > MAX_BYTES:
        raise UploadError(
            f"File is larger than {MAX_BYTES // (1024 * 1024)} MB. "
            "Upload a smaller file or a sample."
        )

    lower = filename.lower()

    if not lower.endswith(SUPPORTED):
        raise UploadError("Unsupported file type. Upload CSV, TSV or Excel (.xlsx).")

    if lower.endswith(".xls"):
        raise UploadError("Old .xls files are not supported. Save it as .xlsx or CSV.")

    if lower.endswith(".xlsx"):
        try:
            sheets = pd.read_excel(
                io.BytesIO(data), sheet_name=None, dtype=object, nrows=MAX_ROWS + 1
            )
        except Exception as error:
            raise UploadError(f"Could not read the Excel file: {error}")

        if len(sheets) > MAX_SHEETS:
            raise UploadError(f"Too many sheets (max {MAX_SHEETS}).")

        frames = {
            table_name_from(filename, sheet if len(sheets) > 1 else None): frame
            for sheet, frame in sheets.items()
        }
    else:
        frames = {table_name_from(filename): _read_csv(data)}

    frames = {name: frame for name, frame in frames.items() if frame.shape[1] > 0}

    if not frames:
        raise UploadError("No data found in the file.")

    for name, frame in frames.items():
        if len(frame) > MAX_ROWS:
            raise UploadError(
                f"'{name}' has more than {MAX_ROWS:,} rows. Upload a sample."
            )

        if frame.shape[1] > MAX_COLUMNS:
            raise UploadError(f"'{name}' has more than {MAX_COLUMNS} columns.")

    return frames

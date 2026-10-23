"""Load Zerodha Console tradebook exports (.xlsx / .csv) from a folder."""

from pathlib import Path

import pandas as pd

REQUIRED = ["Symbol", "ISIN", "Trade Date", "Exchange", "Trade Type", "Quantity", "Price", "Trade ID"]
SUFFIXES = {".xlsx", ".xls", ".csv"}


def _find_header_row(raw: pd.DataFrame) -> int:
    # Console .xlsx exports have ~14 rows of client info above the table.
    for i, row in raw.iterrows():
        values = {str(v).strip() for v in row.values}
        if "Symbol" in values and "Trade Date" in values:
            return i
    raise ValueError("no 'Symbol' / 'Trade Date' header row found")


def read_tradebook(source, name: str = "") -> pd.DataFrame:
    """Read one tradebook. `source` is a path or a file-like object (e.g. a Streamlit upload)."""
    name = name or str(source)
    reader = pd.read_csv if name.lower().endswith(".csv") else pd.read_excel
    raw = reader(source, header=None, dtype=str)
    header = _find_header_row(raw)
    df = raw.iloc[header + 1 :].copy()
    df.columns = [str(c).strip() for c in raw.iloc[header]]
    df = df.loc[:, [c for c in df.columns if c and c != "nan"]].dropna(how="all")
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: missing columns {missing}")
    df["source_file"] = Path(name).name
    return df


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Type the columns, drop duplicate trades across overlapping exports, sort chronologically."""
    df = df.copy()
    df["Symbol"] = df["Symbol"].str.strip()
    df["ISIN"] = df["ISIN"].str.strip().replace("", None)
    df["Exchange"] = df["Exchange"].str.strip().str.upper()
    df["Trade Type"] = df["Trade Type"].str.strip().str.lower()
    df["Trade Date"] = pd.to_datetime(df["Trade Date"]).dt.normalize()
    df["Quantity"] = pd.to_numeric(df["Quantity"])
    df["Price"] = pd.to_numeric(df["Price"])
    if "Order Execution Time" in df.columns:
        df["Order Execution Time"] = pd.to_datetime(df["Order Execution Time"], errors="coerce")
    else:
        df["Order Execution Time"] = df["Trade Date"]
    # Some Console exports leave ISIN blank on a few rows; borrow it from the same symbol's other rows.
    known = df.dropna(subset=["ISIN"]).groupby("Symbol")["ISIN"].last()
    df["ISIN"] = df["ISIN"].fillna(df["Symbol"].map(known)).fillna("SYMBOL:" + df["Symbol"])
    # Trade IDs are unique per exchange + segment, so this removes rows repeated across files.
    keys = [c for c in ["Exchange", "Segment", "Trade ID", "Symbol", "Trade Type"] if c in df.columns]
    df = df.drop_duplicates(subset=keys)
    return df.sort_values(["Trade Date", "Order Execution Time", "Trade ID"]).reset_index(drop=True)


def load_folder(folder) -> tuple[pd.DataFrame, list[str]]:
    """Load every tradebook file in `folder` (recursively). Returns (trades, per-file errors)."""
    frames, errors = [], []
    for path in sorted(Path(folder).expanduser().rglob("*")):
        if path.suffix.lower() not in SUFFIXES or path.name.startswith(("~$", ".")):
            continue
        try:
            frames.append(read_tradebook(path, path.name))
        except Exception as exc:  # keep going; report bad files in the UI
            errors.append(f"{path.name}: {exc}")
    if not frames:
        return pd.DataFrame(columns=REQUIRED), errors
    return normalise(pd.concat(frames, ignore_index=True)), errors

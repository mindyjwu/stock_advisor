"""
Parse Chase J.P. Morgan investment account PDFs to extract holdings.

Chase PDFs come in two main flavours:
  1. Account statement (monthly) — positions table buried mid-document
  2. Portfolio snapshot / confirmation print — single-page holdings table

Strategy:
  - Use pdfplumber to extract all tables from every page
  - Score each table by how many "known good" header keywords it contains
  - Pick the best-scoring table as the positions table
  - Apply the same column normalisation as the CSV importer
"""
import re
import pdfplumber
import pandas as pd
from io import BytesIO


# Header keywords that indicate a holdings/positions table
HEADER_SIGNALS = {
    "symbol", "ticker", "quantity", "shares", "average cost", "avg cost",
    "cost basis", "current value", "market value", "current price",
    "description", "security", "gain", "loss",
}

# Regex that a valid ticker must match
TICKER_RE = re.compile(r"^[A-Z]{1,5}$")

# Rows to skip: totals, cash sweeps, blank descriptions
SKIP_PATTERNS = re.compile(
    r"^(CASH|MONEY MARKET|SWEEP|TOTAL|SUBTOTAL|FDIC|$)", re.IGNORECASE
)


def _score_table(df: pd.DataFrame) -> int:
    """Return how many HEADER_SIGNALS appear in this table's columns."""
    cols = " ".join(str(c).lower() for c in df.columns)
    return sum(1 for sig in HEADER_SIGNALS if sig in cols)


def _clean_number(val):
    """Strip $, commas, parentheses (negative) from a value and return float."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().replace("$", "").replace(",", "").replace(" ", "")
    if not s or s in ("-", "N/A", "--", "n/a"):
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
        return -v if negative else v
    except ValueError:
        return None


def _find_col(df: pd.DataFrame, candidates: list):
    cols_lower = {str(c).strip().lower(): c for c in df.columns}
    for cand in candidates:
        if cand in cols_lower:
            return cols_lower[cand]
    return None


def parse_chase_pdf(file_bytes: bytes) -> dict:
    """
    Returns:
        {
          "positions": [{"symbol": str, "quantity": int, "cost_basis": float}, ...],
          "cash": float | None,
          "warnings": [str],
          "raw_table": pd.DataFrame | None,   # for debugging / preview
        }
    """
    warnings = []
    all_tables = []

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages):
            tables = page.extract_tables()
            for tbl in (tables or []):
                if not tbl or len(tbl) < 2:
                    continue
                # Use first non-empty row as header
                header = [str(c).strip() if c else "" for c in tbl[0]]
                rows   = tbl[1:]
                try:
                    df = pd.DataFrame(rows, columns=header)
                    all_tables.append((page_num, _score_table(df), df))
                except Exception:
                    continue

    if not all_tables:
        return {"positions": [], "cash": None, "warnings": ["No tables found in PDF."], "raw_table": None}

    # Pick the highest-scoring table
    all_tables.sort(key=lambda x: x[1], reverse=True)
    best_score = all_tables[0][1]

    if best_score == 0:
        warnings.append(
            "No clear holdings table detected. Showing the largest table found — "
            "you may need to use the CSV export instead."
        )

    raw = all_tables[0][2].copy()
    raw.columns = [str(c).strip().lower() for c in raw.columns]

    # Locate columns
    sym_col  = _find_col(raw, ["symbol", "ticker", "security symbol", "cusip"])
    qty_col  = _find_col(raw, ["quantity", "shares", "qty", "units"])
    cost_col = _find_col(raw, ["average cost", "avg cost", "cost basis/share",
                                "cost per share", "avg. cost", "average cost per share"])
    tot_col  = _find_col(raw, ["total cost basis", "total cost", "cost basis", "book value"])
    val_col  = _find_col(raw, ["current value", "market value", "value"])

    if not sym_col:
        # Fall back: look for a column where most values look like tickers
        for col in raw.columns:
            vals = raw[col].dropna().astype(str).str.strip().str.upper()
            if vals.str.match(r"^[A-Z]{1,5}$").mean() > 0.5:
                sym_col = col
                warnings.append(f"Auto-detected ticker column: '{col}'")
                break

    if not sym_col:
        return {
            "positions": [], "cash": None,
            "warnings": ["Could not find a ticker/symbol column. Try the CSV export."],
            "raw_table": raw,
        }

    # Clean symbol column
    raw["_sym"] = raw[sym_col].astype(str).str.strip().str.upper()

    # Separate cash rows
    cash_mask = raw["_sym"].str.contains(r"CASH|MONEY MARKET|SWEEP|FDIC", regex=True, na=False)
    cash_val  = None
    if cash_mask.any() and val_col:
        cash_val = _clean_number(raw.loc[cash_mask, val_col].iloc[0])

    # Keep only real tickers
    pos_df = raw[~cash_mask & raw["_sym"].str.match(r"^[A-Z]{1,5}$")].copy()

    # Compute cost_basis per share
    def _cost_per_share(row):
        if cost_col and _clean_number(row.get(cost_col)) is not None:
            return _clean_number(row[cost_col])
        if tot_col and qty_col:
            tot = _clean_number(row.get(tot_col))
            qty = _clean_number(row.get(qty_col))
            if tot and qty and qty != 0:
                return round(tot / qty, 4)
        return None

    positions = []
    skipped   = []
    for _, row in pos_df.iterrows():
        sym = row["_sym"]
        qty = _clean_number(row.get(qty_col)) if qty_col else None
        if not sym or qty is None or qty <= 0:
            skipped.append(sym)
            continue
        cost = _cost_per_share(row)
        positions.append({
            "symbol":     sym,
            "quantity":   int(qty),
            "cost_basis": round(cost, 2) if cost else 0.0,
        })

    if skipped:
        warnings.append(f"Skipped rows (no quantity): {skipped}")

    return {
        "positions": positions,
        "cash":      cash_val,
        "warnings":  warnings,
        "raw_table": pos_df.drop(columns=["_sym"], errors="ignore"),
    }

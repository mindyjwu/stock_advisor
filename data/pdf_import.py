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


# ══════════════════════════════════════════════════════════════════════════════
# J.P. Morgan Self-Directed monthly statement (text layout)
# ══════════════════════════════════════════════════════════════════════════════
# The monthly statement has no ruled tables, so extract_tables() finds nothing
# useful. Its Holdings section is plain text, one block per position:
#
#   APPLE INC 10.08359 344.63 3,475.11 198.03 1,996.88 1,478.23 --      (multi-lot)
#   Symbol: AAPL 10 Apr 2024 3 1,033.89 168 504.00 529.89 LT            (one lot per line)
#   ADVANCED MICRO DEVICES 03 Jul 2025 5 504.8 2,524.00 137.89 689.45 1,834.55 LT --
#   Symbol: AMD                                                        (single lot)
#
# Columns: [date] quantity price market-value unit-cost cost-basis gain/loss.
_NUM = r"\(?[\d,]+\.?\d*\)?"
_STMT_HEADER_RE = re.compile(
    rf"^([A-Z][A-Z0-9 &\.\-'/\(\)]+?) (?:(\d\d \w\w\w \d\d\d\d) )?"
    rf"({_NUM}) ({_NUM}) ({_NUM}) ({_NUM}) (?:A )?({_NUM}) ({_NUM})(?: (LT|ST))? --$"
)
_STMT_LOT_RE = re.compile(
    rf"(\d\d \w\w\w \d\d\d\d) ({_NUM}) ({_NUM}) ({_NUM}) ({_NUM}) ({_NUM}) (LT|ST)"
)
_STMT_SYMBOL_RE = re.compile(r"Symbol: ([A-Z][A-Z\.]{0,6})\b")
_STMT_PERIOD_RE = re.compile(
    r"Statement Period:?\s*([A-Z][a-z]+ \d{1,2})\s*-\s*([A-Z][a-z]+ \d{1,2}),\s*(\d{4})"
)
_CASH_SYMBOLS = {"QACDS"}


def _stmt_num(s: str) -> float:
    neg = s.startswith("(")
    v = float(s.strip("()").replace(",", ""))
    return -v if neg else v


def parse_statement_text(text: str) -> dict:
    """Parse the text of a J.P. Morgan Self-Directed statement.

    Returns {"positions": [...], "cash", "statement": {...}, "warnings": [...]}.
    positions carry fractional quantities and per-share cost; the richer
    per-lot detail (dates, long/short-term) lives under statement["lots"].
    """
    from datetime import datetime

    lines = [l.strip() for l in text.split("\n")]
    warnings, positions, lots_by_symbol, names = [], [], {}, {}
    stmt_prices, cur = {}, None

    for line in lines:
        if line.startswith("TOTAL EQUITY") or line.startswith("TRADE AND INVESTMENT ACTIVITY"):
            break
        m = _STMT_HEADER_RE.match(line)
        if m and not line.startswith("TOTAL"):
            cur = {
                "name": m.group(1).strip(), "symbol": None,
                "quantity": _stmt_num(m.group(3)), "price": _stmt_num(m.group(4)),
                "market_value": _stmt_num(m.group(5)), "unit_cost": _stmt_num(m.group(6)),
                "cost": _stmt_num(m.group(7)), "lots": [],
            }
            if m.group(2):  # single-lot position: the lot is on the header line
                cur["lots"].append({"date": m.group(2), "quantity": cur["quantity"],
                                    "cost": cur["cost"], "term": m.group(9) or ""})
            positions.append(cur)
            continue
        if cur is None:
            continue
        s = _STMT_SYMBOL_RE.search(line)
        if s and cur["symbol"] is None:
            cur["symbol"] = s.group(1)
        lm = _STMT_LOT_RE.search(line)
        if lm:
            cur["lots"].append({"date": lm.group(1), "quantity": _stmt_num(lm.group(2)),
                                "cost": _stmt_num(lm.group(5)), "term": lm.group(7)})

    out_positions = []
    for p in positions:
        sym = p["symbol"]
        if not sym or sym in _CASH_SYMBOLS or p["quantity"] <= 0:
            continue
        per_share = p["cost"] / p["quantity"] if p["quantity"] else p["unit_cost"]
        out_positions.append({"symbol": sym, "quantity": round(p["quantity"], 5),
                              "cost_basis": round(per_share, 4)})
        lots_by_symbol[sym] = p["lots"]
        names[sym] = p["name"].title()
        stmt_prices[sym] = p["price"]

    def _money_after(label):
        for line in lines:
            if line.startswith(label):
                m = re.search(r"\$?\(?([\d,]+\.\d\d)\)?", line[len(label):])
                if m:
                    return float(m.group(1).replace(",", ""))
        return None

    cash = _money_after("TOTAL CASH & MONEY MARKETS")
    total_equity = _money_after("TOTAL EQUITY")
    account_value = _money_after("ENDING ACCOUNT VALUE")

    period_end = None
    pm = _STMT_PERIOD_RE.search(text)
    if pm:
        try:
            period_end = datetime.strptime(f"{pm.group(2)}, {pm.group(3)}", "%B %d, %Y").date().isoformat()
        except ValueError:
            pass

    parsed_mv = round(sum(p["market_value"] for p in positions
                          if p["symbol"] and p["symbol"] not in _CASH_SYMBOLS), 2)
    if total_equity is not None and abs(parsed_mv - total_equity) > max(1.0, 0.001 * total_equity):
        warnings.append(
            f"Parsed positions add up to ${parsed_mv:,.2f} but the statement's equity total is "
            f"${total_equity:,.2f} — a position may have been missed. Check the preview."
        )

    return {
        "positions": out_positions,
        "cash": cash,
        "warnings": warnings,
        "raw_table": None,
        "statement": {
            "period_end": period_end, "account_value": account_value,
            "equity_value": total_equity if total_equity is not None else parsed_mv,
            "cash": cash, "lots": lots_by_symbol, "names": names, "prices": stmt_prices,
        },
    }


def parse_statement_pdf(file_bytes: bytes) -> dict:
    """Text-layout statement parser. Returns positions=[] if this isn't one."""
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    return parse_statement_text(text)


def parse_any_pdf(file_bytes: bytes) -> dict:
    """Try the statement text layout first, then fall back to table detection."""
    try:
        res = parse_statement_pdf(file_bytes)
        if res["positions"]:
            return res
    except Exception:
        pass
    res = parse_chase_pdf(file_bytes)
    res.setdefault("statement", None)
    return res

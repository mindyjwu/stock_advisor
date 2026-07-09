"""App-level configuration: industry labels, model choices, theme mapping, palettes.

Kept out of dashboard.py so users can customize without touching UI code.
A later phase moves these into per-user settings storage.
"""

INDUSTRIES = [
    "Technology", "Financials", "Healthcare", "Energy",
    "Consumer Staples", "Consumer Discretionary", "Industrials",
    "Materials", "Real Estate", "Utilities", "Communication Services", "Misc",
]

AI_MODELS = {
    "Claude Sonnet 4.6 (fast)":   "claude-sonnet-4-6",
    "Claude Opus 4.8 (powerful)":  "claude-opus-4-8",
    "Claude Haiku 4.5 (cheap)":    "claude-haiku-4-5-20251001",
}

# Ticker → thematic industry grouping used by the "Portfolio by Theme" chart.
# Unknown tickers fall back to "Other".
THEME_MAP = {
    # AI & Semiconductors
    "NVDA": "AI & Semiconductors", "AMD": "AI & Semiconductors", "AMAT": "AI & Semiconductors",
    "TSM": "AI & Semiconductors", "QCOM": "AI & Semiconductors", "INTC": "AI & Semiconductors",
    "AKTS": "AI & Semiconductors", "DRAM": "AI & Semiconductors", "NBIS": "AI & Semiconductors",
    # AI Infrastructure & Cloud
    "ANET": "AI Infra & Cloud", "CRWV": "AI Infra & Cloud", "ORCL": "AI Infra & Cloud",
    "MSFT": "AI Infra & Cloud", "PLTR": "AI Infra & Cloud", "VSNT": "AI Infra & Cloud",
    "SRAD": "AI Infra & Cloud",
    # Consumer Tech
    "AAPL": "Consumer Tech", "TSLA": "Consumer Tech", "NFLX": "Consumer Tech",
    "SNAP": "Consumer Tech", "PINS": "Consumer Tech", "UBER": "Consumer Tech", "TTWO": "Consumer Tech",
    # Financials & Fintech
    "GS": "Financials & Fintech", "BAC": "Financials & Fintech", "NU": "Financials & Fintech",
    "SOFI": "Financials & Fintech", "PYPL": "Financials & Fintech", "BAM": "Financials & Fintech",
    "FIG": "Financials & Fintech", "OBDC": "Financials & Fintech", "YRD": "Financials & Fintech",
    "IRM": "Financials & Fintech",
    # Healthcare & Pharma
    "UNH": "Healthcare & Pharma", "NVO": "Healthcare & Pharma",
    "TAK": "Healthcare & Pharma", "ABT": "Healthcare & Pharma",
    # Energy & Nuclear
    "CEG": "Energy & Utilities", "VST": "Energy & Utilities", "SMR": "Energy & Utilities",
    "TE": "Energy & Utilities",
    # Consumer Staples & Retail
    "COST": "Consumer & Retail", "PG": "Consumer & Retail", "KHC": "Consumer & Retail",
    "MGM": "Consumer & Retail", "CCL": "Consumer & Retail", "VAC": "Consumer & Retail",
    # Travel & Transport
    "UAL": "Travel & Transport", "DAL": "Travel & Transport", "CMCSA": "Media & Telecom",
    "DIS": "Media & Telecom",
    # Defense & Space
    "KTOS": "Defense & Space", "RKLB": "Defense & Space",
    # International
    "LVMUY": "International", "TM": "International", "SKM": "International",
    "MUFG": "International", "HNHPF": "International", "FLGB": "International",
    "FLJP": "International", "EWJV": "International", "FLCH": "International",
    "ALMR": "International", "USAR": "International", "FLY": "International",
}

PIE_COLORS = [
    "#6366f1", "#8b5cf6", "#3b82f6", "#10b981", "#f59e0b",
    "#ef4444", "#ec4899", "#14b8a6", "#f97316", "#84cc16",
    "#06b6d4", "#a78bfa", "#fb923c", "#4ade80", "#e879f9",
]

# Text colors for verdict labels rendered on white table cells.
# All chosen to clear WCAG AA (>=4.5:1) as small bold text on #fff.
# Covers the app's real verdicts (Strong Buy/Buy/Watch/Avoid) plus the
# Hold/Sell aliases some views use.
ACTION_COLORS = {
    "Strong Buy":  "#15803d",
    "Buy":         "#047857",
    "Watch":       "#b45309",
    "Avoid":       "#b91c1c",
    "Hold":        "#b45309",
    "Sell":        "#dc2626",
    "Strong Sell": "#b91c1c",
}

# Accessible green/red for gains/losses as small text on white.
POS_COLOR = "#15803d"
NEG_COLOR = "#dc2626"

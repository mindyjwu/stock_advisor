"""
Whale Watch — read-only reference data: what well-known investors' funds
report owning, straight from their SEC Form 13F filings.

13F filings are the real public data source for "what do billionaires own":
any institutional manager with $100M+ in US equities must file one quarterly,
listing every position, with a lag of up to 45 days after quarter-end. This
is informational only — it does not feed into the app's scoring, and stale
holdings (up to a quarter old) are not a signal to copy blindly.

Not covered here: individuals who aren't registered investment managers
(e.g. politicians, the President) don't file 13Fs at all, so there's no
equivalent structured feed for them — see app/dashboard.py's Whale Watch
page for how that's handled.
"""
import json
import os
import pathlib
import re
import shutil
import statistics
import subprocess
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict

ROOT = pathlib.Path(__file__).parent.parent
CACHE_DIR = ROOT / "data" / "cache" / "whale"
CACHE_TTL_SECONDS = 6 * 60 * 60  # 13F updates quarterly; a few hours keeps SEC load light

# SEC EDGAR requires a descriptive User-Agent with a way to reach the requester.
# Override with your own contact info via SEC_EDGAR_CONTACT if you deploy this.
_UA = os.environ.get("SEC_EDGAR_CONTACT", "stock-advisor-app (educational project)")

# Curated list of well-known 13F filers. CIKs verified against SEC EDGAR.
INVESTORS = [
    {"key": "buffett",       "name": "Warren Buffett",       "fund": "Berkshire Hathaway",       "cik": "1067983"},
    {"key": "ackman",        "name": "Bill Ackman",          "fund": "Pershing Square",           "cik": "1336528"},
    {"key": "icahn",         "name": "Carl Icahn",           "fund": "Icahn Enterprises",         "cik": "921669"},
    {"key": "burry",         "name": "Michael Burry",        "fund": "Scion Asset Management",    "cik": "1649339"},
    {"key": "druckenmiller", "name": "Stanley Druckenmiller","fund": "Duquesne Family Office",     "cik": "1536411"},
    {"key": "dalio",         "name": "Ray Dalio",            "fund": "Bridgewater Associates",     "cik": "1350694"},
    {"key": "tepper",        "name": "David Tepper",         "fund": "Appaloosa Management",       "cik": "1656456"},
    {"key": "soros",         "name": "George Soros",         "fund": "Soros Fund Management",      "cik": "1029160"},
]
_BY_KEY = {i["key"]: i for i in INVESTORS}

# Static CUSIP → ticker map, curated from these funds' actual recent holdings.
# 13F filings only report CUSIP + issuer name (no ticker) and there's no free
# official CUSIP→ticker table — unmapped positions still show, just without
# a ticker/live-price cross-reference.
CUSIP_TICKER = {
    "037833100": "AAPL", "025816109": "AXP", "191216100": "KO", "060505104": "BAC",
    "166764100": "CVX", "674599105": "OXY", "02079K305": "GOOG", "02079K107": "GOOGL",
    "H1467J104": "CB", "615369105": "MCO", "500754106": "KHC", "23918K108": "DVA",
    "501044101": "KR",
    "11271J107": "BN", "023135106": "AMZN", "90353T100": "UBER", "594918104": "MSFT",
    "76131D103": "QSR", "30303M102": "META", "44267T102": "HHH", "812215200": "SEG",
    "42806J700": "HTZ",
    "451100101": "IEP", "12662P108": "CVI", "126633205": "UAN", "155923105": "CTRI",
    "459506101": "IFF", "278768106": "SATS", "025537101": "AEP", "477143101": "JBLU",
    "610236101": "MNRO", "80007P869": "SD", "12769G100": "CZR", "071705107": "BLCO",
    "69608A108": "PLTR", "67066G104": "NVDA", "717081103": "PFE", "406216101": "HAL",
    "60855R100": "MOH", "550021109": "LULU", "78442P106": "SLM", "116794207": "BRKR",
    "632307104": "NTRA", "457669307": "INSM", "874039100": "TSM", "984245100": "YPF",
    "013872106": "AA", "N62509109": "NAMS", "81141R100": "SE", "861012102": "STM",
    "980745103": "WWD", "G0896C103": "TBBB",
    "78462F103": "SPY", "11135F101": "AVGO", "595112103": "MU", "36828A101": "GEV",
    "512807306": "LRCX", "007903107": "AMD",
}


def list_investors() -> list:
    return list(INVESTORS)


def _edgar_get(url: str, retries: int = 3) -> bytes:
    """SEC's www.sec.gov/Archives pages are behind bot mitigation that
    occasionally 403s well-formed, User-Agent'd requests — both Python's
    urllib and curl trip it under any nontrivial burst of traffic, and it
    clears on its own after a short wait. Retry a few times with backoff
    before giving up; the disk cache above this means a real deploy only
    pays this cost once every few hours per investor, not per page view."""
    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        try:
            return urllib.request.urlopen(req, timeout=20).read()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code != 403:
                raise
            if shutil.which("curl"):
                try:
                    return subprocess.run(
                        ["curl", "-sf", "-H", f"User-Agent: {_UA}", "--max-time", "20", url],
                        capture_output=True, check=True,
                    ).stdout
                except subprocess.CalledProcessError:
                    pass
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    raise last_err


def _latest_13f_filings(cik: str, n: int = 2) -> list:
    """Returns up to n most recent (filing_date, infotable_url), newest first."""
    subs = json.loads(_edgar_get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"))
    recent = subs["filings"]["recent"]
    out = []
    for i, form in enumerate(recent["form"]):
        if form != "13F-HR":
            continue
        acc = recent["accessionNumber"][i].replace("-", "")
        idx_html = _edgar_get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/").decode(errors="ignore")
        xml_files = re.findall(r'href="([^"]*\.xml)"', idx_html)
        infotable = next((u for u in xml_files if "primary_doc" not in u), None)
        if infotable:
            out.append((recent["filingDate"][i], "https://www.sec.gov" + infotable))
        if len(out) >= n:
            break
    return out


def _parse_infotable(xml_bytes: bytes) -> dict:
    """Aggregates a 13F information table by CUSIP (a filer can list the same
    position multiple times across sub-managers). Returns cusip -> {issuer, value, shares}.
    Normalizes the well-known quirk where some filers still report `value` in
    thousands of dollars instead of whole dollars: if the median implied
    price-per-share across the filing is implausibly low, the values are
    rescaled x1000."""
    root = ET.fromstring(xml_bytes)
    ns = {"n": root.tag.split("}")[0].strip("{")}
    agg = defaultdict(lambda: {"issuer": "", "value": 0, "shares": 0})
    for it in root.findall("n:infoTable", ns):
        cusip = (it.findtext("n:cusip", default="", namespaces=ns) or "").strip()
        issuer = (it.findtext("n:nameOfIssuer", default="", namespaces=ns) or "").strip()
        value = int(it.findtext("n:value", default="0", namespaces=ns) or 0)
        shares = int(it.findtext("n:shrsOrPrnAmt/n:sshPrnamt", default="0", namespaces=ns) or 0)
        if not cusip:
            continue
        agg[cusip]["issuer"] = issuer
        agg[cusip]["value"] += value
        agg[cusip]["shares"] += shares

    implied_prices = [d["value"] / d["shares"] for d in agg.values() if d["shares"] > 0 and d["value"] > 0]
    if implied_prices and statistics.median(implied_prices) < 2.0:
        for d in agg.values():
            d["value"] *= 1000

    return dict(agg)


def _classify(cur_shares: int, prev_shares) -> str:
    if prev_shares is None:
        return "New"
    if cur_shares == 0:
        return "Sold Out"
    if prev_shares == 0:
        return "New"
    chg = (cur_shares - prev_shares) / prev_shares
    if chg > 0.02:
        return "Added"
    if chg < -0.02:
        return "Reduced"
    return "Unchanged"


def get_portfolio(investor_key: str, top_n: int = 20, force_refresh: bool = False) -> dict:
    """Returns {"investor": {...}, "filed": date, "prior_filed": date|None,
    "total_value": int, "positions": [ {cusip, ticker, issuer, value, shares,
    pct, action}, ... ] (sorted by value desc, top_n), "error": msg|None}."""
    investor = _BY_KEY.get(investor_key)
    if not investor:
        return {"error": f"Unknown investor '{investor_key}'"}

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{investor['cik']}.json"
    if not force_refresh and cache_file.exists() and time.time() - cache_file.stat().st_mtime < CACHE_TTL_SECONDS:
        with open(cache_file) as f:
            return json.load(f)

    try:
        filings = _latest_13f_filings(investor["cik"], n=2)
        if not filings:
            result = {"investor": investor, "error": "No 13F-HR filings found for this manager."}
        else:
            filed, url = filings[0]
            current = _parse_infotable(_edgar_get(url))
            prior = None
            prior_filed = None
            if len(filings) > 1:
                prior_filed, prior_url = filings[1]
                prior = _parse_infotable(_edgar_get(prior_url))

            total_value = sum(d["value"] for d in current.values())
            rows = []
            for cusip, d in current.items():
                prev_shares = prior.get(cusip, {}).get("shares") if prior else None
                rows.append({
                    "cusip": cusip,
                    "ticker": CUSIP_TICKER.get(cusip),
                    "issuer": d["issuer"],
                    "value": d["value"],
                    "shares": d["shares"],
                    "pct": round(d["value"] / total_value * 100, 2) if total_value else 0,
                    "action": _classify(d["shares"], prev_shares),
                })
            if prior:
                for cusip, d in prior.items():
                    if cusip not in current:
                        rows.append({
                            "cusip": cusip, "ticker": CUSIP_TICKER.get(cusip),
                            "issuer": d["issuer"], "value": 0, "shares": 0,
                            "pct": 0, "action": "Sold Out",
                        })
            rows.sort(key=lambda r: r["value"], reverse=True)
            result = {
                "investor": investor, "filed": filed, "prior_filed": prior_filed,
                "total_value": total_value, "n_positions": len(current),
                "positions": rows[:top_n], "error": None,
            }
    except Exception as e:
        result = {"investor": investor, "error": f"Couldn't fetch SEC data: {e}"}

    with open(cache_file, "w") as f:
        json.dump(result, f)
    return result

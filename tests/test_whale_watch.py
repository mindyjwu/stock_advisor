"""
Tests for agents.whale_watch — the SEC 13F reader.

The pure parsing/classification logic is tested directly. The end-to-end
get_portfolio path is exercised with the network boundary (_edgar_get)
monkeypatched to serve canned SEC responses, and CACHE_DIR pointed at tmp so
tests never touch the real cache or the network.
"""
import json

import pytest

import agents.whale_watch as ww

_NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"


def _infotable_xml(rows):
    """rows: list of (cusip, issuer, value, shares) -> 13F info-table bytes."""
    body = "".join(
        f"""<infoTable>
              <nameOfIssuer>{issuer}</nameOfIssuer>
              <cusip>{cusip}</cusip>
              <value>{value}</value>
              <shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt></shrsOrPrnAmt>
            </infoTable>"""
        for cusip, issuer, value, shares in rows
    )
    return f'<?xml version="1.0"?><informationTable xmlns="{_NS}">{body}</informationTable>'.encode()


# ── _classify ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cur,prev,expected", [
    (100, None, "New"),        # no prior filing at all
    (100, 0, "New"),           # position didn't exist last quarter
    (0, 100, "Sold Out"),      # fully exited
    (150, 100, "Added"),       # +50%
    (50, 100, "Reduced"),      # -50%
    (100, 100, "Unchanged"),   # flat
    (101, 100, "Unchanged"),   # +1% is inside the ±2% noise band
    (103, 100, "Added"),       # +3% clears the band
])
def test_classify(cur, prev, expected):
    assert ww._classify(cur, prev) == expected


# ── _parse_infotable ─────────────────────────────────────────────────────────

def test_parse_infotable_aggregates_by_cusip():
    xml = _infotable_xml([
        ("037833100", "APPLE INC", 600000, 6000),
        ("037833100", "APPLE INC", 400000, 4000),  # same cusip, sub-manager
        ("025816109", "AMERICAN EXPRESS", 500000, 5000),
    ])
    agg = ww._parse_infotable(xml)
    assert agg["037833100"] == {"issuer": "APPLE INC", "value": 1000000, "shares": 10000}
    assert agg["025816109"]["value"] == 500000


def test_parse_infotable_rescales_thousands():
    # Values reported in $thousands -> implied prices ~0.1, median < 2.0 -> x1000
    xml = _infotable_xml([
        ("037833100", "APPLE INC", 1000, 10000),
        ("025816109", "AMERICAN EXPRESS", 500, 5000),
    ])
    agg = ww._parse_infotable(xml)
    assert agg["037833100"]["value"] == 1_000_000
    assert agg["025816109"]["value"] == 500_000


def test_parse_infotable_leaves_whole_dollars_alone():
    xml = _infotable_xml([
        ("037833100", "APPLE INC", 1_000_000, 10000),   # implied 100
        ("025816109", "AMERICAN EXPRESS", 500_000, 5000),  # implied 100
    ])
    agg = ww._parse_infotable(xml)
    assert agg["037833100"]["value"] == 1_000_000  # unchanged


# ── list_investors ───────────────────────────────────────────────────────────

def test_list_investors_returns_copy():
    a = ww.list_investors()
    a.append({"bogus": True})
    assert len(ww.list_investors()) == len(ww.INVESTORS)  # internal list untouched
    assert all({"key", "name", "fund", "cik"} <= set(i) for i in ww.list_investors())


# ── get_portfolio end-to-end ─────────────────────────────────────────────────

def _fake_edgar(current_rows, prior_rows, cik="1067983"):
    """Build an _edgar_get replacement serving a submissions index + two
    13F filings (current, prior) from the given rows."""
    subs = json.dumps({"filings": {"recent": {
        "form": ["13F-HR", "10-K", "13F-HR"],
        "accessionNumber": ["0000000000-00-000001", "x", "0000000000-00-000002"],
        "filingDate": ["2025-05-15", "2025-04-01", "2025-02-14"],
    }}}).encode()
    cur_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/cur.xml"
    prior_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/prior.xml"

    def _get(url, retries=3):
        if "data.sec.gov/submissions" in url:
            return subs
        if url.endswith("000000000000000001/"):
            return b'<a href="/Archives/edgar/data/%d/cur.xml">t</a>' % int(cik)
        if url.endswith("000000000000000002/"):
            return b'<a href="/Archives/edgar/data/%d/prior.xml">t</a>' % int(cik)
        if url == cur_url:
            return _infotable_xml(current_rows)
        if url == prior_url:
            return _infotable_xml(prior_rows)
        raise AssertionError(f"unexpected url {url}")

    return _get


def test_get_portfolio_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setattr(ww, "CACHE_DIR", tmp_path / "whale")
    monkeypatch.setattr(ww, "_edgar_get", _fake_edgar(
        current_rows=[
            ("037833100", "APPLE INC", 1_000_000, 10_000),          # was 8000 -> Added
            ("025816109", "AMERICAN EXPRESS", 500_000, 5_000),      # flat -> Unchanged
        ],
        prior_rows=[
            ("037833100", "APPLE INC", 800_000, 8_000),
            ("025816109", "AMERICAN EXPRESS", 500_000, 5_000),
            ("191216100", "COCA COLA CO", 200_000, 2_000),          # gone now -> Sold Out
        ],
    ))
    res = ww.get_portfolio("buffett")
    assert res["error"] is None
    assert res["filed"] == "2025-05-15" and res["prior_filed"] == "2025-02-14"
    assert res["total_value"] == 1_500_000
    assert res["n_positions"] == 2

    by = {p["cusip"]: p for p in res["positions"]}
    assert by["037833100"]["ticker"] == "AAPL"
    assert by["037833100"]["action"] == "Added"
    assert by["025816109"]["action"] == "Unchanged"
    assert by["191216100"]["action"] == "Sold Out"     # appended from prior
    assert by["191216100"]["value"] == 0
    # sorted by value desc: Apple (1M) first
    assert res["positions"][0]["cusip"] == "037833100"
    # pct computed off total
    assert abs(by["037833100"]["pct"] - 66.67) < 0.01


def test_get_portfolio_caches_to_disk(monkeypatch, tmp_path):
    monkeypatch.setattr(ww, "CACHE_DIR", tmp_path / "whale")
    calls = {"n": 0}
    inner = _fake_edgar(
        current_rows=[("037833100", "APPLE INC", 1_000_000, 10_000)],
        prior_rows=[("037833100", "APPLE INC", 1_000_000, 10_000)],
    )

    def counting(url, retries=3):
        calls["n"] += 1
        return inner(url, retries)

    monkeypatch.setattr(ww, "_edgar_get", counting)
    ww.get_portfolio("buffett")
    first = calls["n"]
    assert first > 0
    ww.get_portfolio("buffett")          # served from disk cache, no new fetches
    assert calls["n"] == first


def test_get_portfolio_unknown_investor():
    res = ww.get_portfolio("nobody")
    assert res["error"] == "Unknown investor 'nobody'"


def test_get_portfolio_no_filings(monkeypatch, tmp_path):
    monkeypatch.setattr(ww, "CACHE_DIR", tmp_path / "whale")

    def _no_13f(url, retries=3):
        if "data.sec.gov/submissions" in url:
            return json.dumps({"filings": {"recent": {
                "form": ["10-K"], "accessionNumber": ["x"], "filingDate": ["2025-01-01"],
            }}}).encode()
        raise AssertionError("should not fetch filings when none exist")

    monkeypatch.setattr(ww, "_edgar_get", _no_13f)
    res = ww.get_portfolio("buffett")
    assert "No 13F-HR filings" in res["error"]


def test_get_portfolio_network_error_is_caught(monkeypatch, tmp_path):
    monkeypatch.setattr(ww, "CACHE_DIR", tmp_path / "whale")

    def _boom(url, retries=3):
        raise ConnectionError("SEC unreachable")

    monkeypatch.setattr(ww, "_edgar_get", _boom)
    res = ww.get_portfolio("buffett")
    assert "Couldn't fetch SEC data" in res["error"]

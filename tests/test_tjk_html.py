"""Offline tests for TJK HTML parsers, shared fetcher, schema idempotency, and backfill helpers."""
import gzip
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.db import (
    fetched_ok,
    init_db,
    upsert_pools,
    upsert_race_extra,
    upsert_results,
    upsert_runner_extra,
)
from ganyan.parse_results import parse_results_file
from ganyan.sources.fetch import fetch
from ganyan.sources.tjk_html import parse_day_cities, parse_results_html
from scripts.backfill_html import has_csv_results, write_city_results

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _read_gz_fixture(name: str) -> str:
    with gzip.open(FIXTURES / name, "rt", encoding="utf-8") as f:
        return f.read()


def _assert_opt_float(a, b, tol=1e-6):
    if b is None:
        assert a is None
    else:
        assert a is not None
        assert a == pytest.approx(b, abs=tol)


def test_ankara_2026_matches_csv_fixture(tmp_path):
    """5a: 2026-10-24 Ankara HTML <-> CSV fixture field-by-field + §2.7 known values."""
    html_text = _read_gz_fixture("results_html_2026-10-24_Ankara.html.gz")
    html_parsed = parse_results_html(html_text, "2026-10-24", "Ankara")
    csv_parsed = parse_results_file(FIXTURES / "results_2026-10-24_Ankara.csv")

    assert len(html_parsed["races"]) == len(csv_parsed["races"]) == 10
    for hr, cr in zip(html_parsed["races"], csv_parsed["races"]):
        for k in ("race_id", "date", "city", "race_no", "post_time", "cls", "breed", "distance", "surface", "status"):
            assert hr[k] == cr[k], f"race mismatch on {hr['race_id']}.{k}: {hr[k]!r} != {cr[k]!r}"

    assert len(html_parsed["runners"]) == len(csv_parsed["runners"])
    csv_runners_by_key = {(r["race_id"], r["horse_key"]): r for r in csv_parsed["runners"]}
    html_runners_by_key = {(r["race_id"], r["horse_key"]): r for r in html_parsed["runners"]}
    assert set(html_runners_by_key.keys()) == set(csv_runners_by_key.keys())

    for key, cr in csv_runners_by_key.items():
        hr = html_runners_by_key[key]
        assert hr["horse_key"] == cr["horse_key"]
        assert hr["name"] == cr["name"]
        assert hr["name_raw"].split() == cr["name_raw"].split()  # CSV bazen çift boşluk içerir
        assert hr["finish"] == cr["finish"]
        _assert_opt_float(hr["agf_close"], cr["agf_close"])
        assert hr["agf_close_rank"] == cr["agf_close_rank"]
        _assert_opt_float(hr["ganyan"], cr["ganyan"])
        _assert_opt_float(hr["time_s"], cr["time_s"])
        assert hr["gate"] == cr["gate"]
        _assert_opt_float(hr["weight"], cr["weight"])
        assert hr["scratched"] == cr["scratched"]
        assert hr["prog_no"] is not None and hr["prog_no"] >= 1

    # GANYAN bets match CSV
    html_ganyan = sorted(
        (b["race_id"], b["combo"], b["payout"]) for b in html_parsed["bets"] if b["bet"] == "GANYAN"
    )
    csv_ganyan = sorted(
        (b["race_id"], b["combo"], b["payout"]) for b in csv_parsed["bets"] if b["bet"] == "GANYAN"
    )
    assert len(html_ganyan) == len(csv_ganyan) == 10
    for (hr_id, hc, hp), (cr_id, cc, cp) in zip(html_ganyan, csv_ganyan):
        assert hr_id == cr_id
        assert hc == cc
        assert hp == pytest.approx(cp, abs=1e-6)

    # Altili legs + payout match CSV
    assert len(html_parsed["altili"]) == len(csv_parsed["altili"]) == 2
    for ha, ca in zip(
        sorted(html_parsed["altili"], key=lambda x: x["which"]),
        sorted(csv_parsed["altili"], key=lambda x: x["which"]),
    ):
        assert ha["which"] == ca["which"]
        assert ha["start_race"] == ca["start_race"]
        assert ha["end_race"] == ca["end_race"]
        assert ha["legs"] == ca["legs"]
        assert ha["payout"] == pytest.approx(ca["payout"], abs=1e-6)

    # Known values (roadmap §2.7)
    by_name = {r["name"]: r for r in html_parsed["runners"]}
    imp = by_name["IMPERIAL GLOIRE"]
    assert imp["finish"] == 1
    assert imp["agf_close"] == pytest.approx(2.99, abs=1e-6)
    assert imp["agf_close_rank"] == 6
    assert imp["ganyan"] == pytest.approx(17.0, abs=1e-6)
    assert imp["time_s"] == pytest.approx(86.56, abs=1e-6)
    assert imp["gate"] == 5
    assert imp["prog_no"] == 5

    qou = by_name["QUEEN OF UNION"]
    assert qou["weight"] == pytest.approx(57.7, abs=1e-6)

    altili_1 = next(a for a in html_parsed["altili"] if a["which"] == 1)
    assert altili_1["legs"] == [[5], [8], [6], [2], [10], [7]]
    assert altili_1["payout"] == pytest.approx(292238.81, abs=1e-6)

    # Extra tables + atomic write + CSV guard check
    assert len(html_parsed["race_extra"]) == 10
    assert html_parsed["race_extra"][0]["prize_1"] == pytest.approx(600000.0, abs=1e-6)
    assert html_parsed["race_extra"][0]["son800_s"] == pytest.approx(49.2, abs=1e-6)  # sayfa: "Son 800 :0.49.20-0.49.40"
    assert len(html_parsed["pools"]) == 10

    conn = init_db(tmp_path / "ankara.db")
    try:
        write_city_results(conn, html_parsed)
        assert not has_csv_results(conn, "2026-10-24", "Ankara")
        saved_prog = conn.execute(
            "SELECT prog_no FROM runners WHERE race_id = ? AND name = ?",
            ("2026-10-24_Ankara_1", "IMPERIAL GLOIRE"),
        ).fetchone()[0]
        assert saved_prog == 5
    finally:
        conn.close()

    conn_csv = init_db(tmp_path / "ankara_csv.db")
    try:
        upsert_results(conn_csv, csv_parsed)
        assert has_csv_results(conn_csv, "2026-10-24", "Ankara")
    finally:
        conn_csv.close()


def test_bursa_2008_no_agf_and_winner_prog_no():
    """5b: 2008-10-05 Bursa has races > 0, AGF all None, 1 winner per result race, winner prog_no == GANYAN combo."""
    html_text = _read_gz_fixture("results_html_2008-10-05_Bursa.html.gz")
    parsed = parse_results_html(html_text, "2008-10-05", "Bursa")

    assert len(parsed["races"]) > 0
    assert len(parsed["runners"]) > 0
    assert all(r["agf_close"] is None and r["agf_close_rank"] is None for r in parsed["runners"])

    ganyan_by_race = {b["race_id"]: b["combo"] for b in parsed["bets"] if b["bet"] == "GANYAN"}
    result_races = [r for r in parsed["races"] if r["status"] == "result"]
    assert len(result_races) > 0

    for race in result_races:
        rid = race["race_id"]
        winners = [
            r for r in parsed["runners"]
            if r["race_id"] == rid and not r["scratched"] and r["finish"] == 1
        ]
        assert len(winners) >= 1
        if len(winners) == 1 and winners[0]["prog_no"] is not None:
            assert rid in ganyan_by_race
            assert str(winners[0]["prog_no"]) == ganyan_by_race[rid]


def test_istanbul_2016_agf_pools_son800(tmp_path):
    """5c: 2016-10-02 İstanbul has AGF populated, non-empty pools, and Son 800 seconds > 0."""
    html_text = _read_gz_fixture("results_html_2016-10-02_Istanbul.html.gz")
    parsed = parse_results_html(html_text, "2016-10-02", "İstanbul")

    assert len(parsed["races"]) > 0
    agf_runners = [r for r in parsed["runners"] if r["agf_close"] is not None]
    assert len(agf_runners) > 0
    assert all(r["agf_close_rank"] is not None for r in agf_runners)

    assert len(parsed["pools"]) > 0
    assert all(p["amount"] > 0 for p in parsed["pools"])

    son800_vals = [r["son800_s"] for r in parsed["race_extra"] if r["son800_s"] is not None]
    assert len(son800_vals) == len(parsed["races"])
    assert all(v > 0 for v in son800_vals)

    conn = init_db(tmp_path / "ist2016.db")
    try:
        upsert_results(conn, parsed)
        upsert_race_extra(conn, parsed["race_extra"])
        upsert_runner_extra(conn, parsed["runner_extra"])
        upsert_pools(conn, parsed["pools"])
        pool_cnt = conn.execute("SELECT COUNT(*) FROM pools WHERE date = '2016-10-02'").fetchone()[0]
        assert pool_cnt == len(parsed["pools"])
    finally:
        conn.close()


def test_day_html_2005_cities():
    """5d: 2005-03-06 day page returns [('İzmir', '2')]."""
    day_html = _read_gz_fixture("day_html_2005-03-06.html.gz")
    assert parse_day_cities(day_html) == [("İzmir", "2")]


def test_fetch_caching_and_error_retry(tmp_path):
    """5e: fetch() skips network on second call when ok + file exists, and retries on error/empty."""
    conn = init_db(tmp_path / "fetch.db")
    try:
        calls = []
        sleeps = []

        def fake_ok(url, extra_headers=None):
            calls.append((url, extra_headers))
            return 200, "<html><body>Türkçe içerik</body></html>".encode("utf-8")

        raw_ok = tmp_path / "raw" / "ok.html.gz"
        text1 = fetch(
            conn,
            "tjk_html",
            "day:2020-01-01",
            "https://example.test/day",
            raw_ok,
            headers={"X-Test": "1"},
            delay=0.25,
            getter=fake_ok,
            sleep_fn=sleeps.append,
        )
        assert text1 == "<html><body>Türkçe içerik</body></html>"
        assert len(calls) == 1
        assert sleeps == [0.25]
        assert raw_ok.exists()
        assert fetched_ok(conn, "tjk_html", "day:2020-01-01")

        def must_not_call(url, extra_headers=None):
            raise AssertionError("Network should not be hit when fetch_log is ok and raw file exists")

        text2 = fetch(
            conn,
            "tjk_html",
            "day:2020-01-01",
            "https://example.test/day",
            raw_ok,
            headers={"X-Test": "1"},
            delay=0.25,
            getter=must_not_call,
            sleep_fn=sleeps.append,
        )
        assert text2 == text1
        assert len(calls) == 1
        assert sleeps == [0.25]

        # Error then empty body then valid response -> retried until ok
        responses = iter([
            (500, b""),
            (200, b"   "),
            (200, b"<html>recovered</html>"),
        ])
        retry_calls = 0

        def flaky_get(url, extra_headers=None):
            nonlocal retry_calls
            retry_calls += 1
            return next(responses)

        raw_err = tmp_path / "raw" / "flaky.html.gz"
        assert fetch(
            conn, "tjk_html", "day:2020-01-02", "https://example.test/flaky",
            raw_err, delay=0.0, getter=flaky_get, sleep_fn=lambda _: None,
        ) is None
        assert not fetched_ok(conn, "tjk_html", "day:2020-01-02")
        status_row = conn.execute(
            "SELECT status, http FROM fetch_log WHERE source='tjk_html' AND target='day:2020-01-02'"
        ).fetchone()
        assert status_row == ("error", 500)

        assert fetch(
            conn, "tjk_html", "day:2020-01-02", "https://example.test/flaky",
            raw_err, delay=0.0, getter=flaky_get, sleep_fn=lambda _: None,
        ) is None
        assert not fetched_ok(conn, "tjk_html", "day:2020-01-02")

        recovered = fetch(
            conn, "tjk_html", "day:2020-01-02", "https://example.test/flaky",
            raw_err, delay=0.0, getter=flaky_get, sleep_fn=lambda _: None,
        )
        assert recovered == "<html>recovered</html>"
        assert retry_calls == 3
        assert fetched_ok(conn, "tjk_html", "day:2020-01-02")
    finally:
        conn.close()


def test_schema_idempotent(tmp_path):
    """5f: init_db called twice succeeds without error and creates all expected tables."""
    db_file = tmp_path / "idempotent.db"
    conn1 = init_db(db_file)
    conn1.close()

    conn2 = init_db(db_file)
    try:
        tables = {
            row[0]
            for row in conn2.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        expected = {
            "races",
            "runners",
            "altili",
            "bets",
            "agf_snapshots",
            "predictions",
            "weather_hourly",
            "fetch_log",
            "race_extra",
            "runner_extra",
            "pools",
            "workouts",
            "steward_notes",
            "ext_ratings",
            "horse_ids",
        }
        assert expected.issubset(tables)
    finally:
        conn2.close()

"""Offline tests for Liderform galop parser, leakage guard, horse_key mapping, and backfill."""
import datetime
import gzip
import io
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.db import fetched_ok, init_db
from ganyan.sources.liderform import (
    DOMESTIC_CITY_SLUGS,
    city_slug,
    detect_liderform_block,
    galop_url,
    parse_galop_horses,
    parse_galop_page,
    parse_next_data,
)
from scripts.backfill_liderform import (
    FETCH_SOURCE,
    WORKOUT_SOURCE,
    ingest_galop_page,
    insert_horse_ids,
    insert_workouts,
    load_target_races,
    resolve_horse_key,
    run_backfill,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FORBIDDEN_LEAK_KEYS = {"races", "ranks", "handicap"}


def _read_gz_fixture(name: str) -> str:
    with gzip.open(FIXTURES / name, "rt", encoding="utf-8") as f:
        return f.read()


def _collect_all_dict_keys(obj) -> set:
    keys = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(str(k))
            keys.update(_collect_all_dict_keys(v))
    elif isinstance(obj, list):
        for item in obj:
            keys.update(_collect_all_dict_keys(item))
    return keys


def test_city_slug_and_galop_url():
    """Madde 1 & 4: city_slug conversions for all 10 domestic cities and galop_url format."""
    expected = {
        "İstanbul": "istanbul",
        "İzmir": "izmir",
        "Şanlıurfa": "sanliurfa",
        "Elazığ": "elazig",
        "Diyarbakır": "diyarbakir",
        "Kocaeli": "kocaeli",
        "Antalya": "antalya",
        "Bursa": "bursa",
        "Ankara": "ankara",
        "Adana": "adana",
    }
    assert DOMESTIC_CITY_SLUGS == expected
    for city, slug in expected.items():
        assert city_slug(city) == slug
        assert city_slug(f"  {city}  ") == slug

    with pytest.raises(ValueError):
        city_slug("")
    with pytest.raises(ValueError):
        city_slug("---")

    assert (
        galop_url("2024-10-06", "İstanbul", 1)
        == "https://liderform.com.tr/program/galop/2024-10-06/istanbul/1"
    )
    assert (
        galop_url(datetime.date(2015, 10, 4), "Şanlıurfa", 7)
        == "https://liderform.com.tr/program/galop/2015-10-04/sanliurfa/7"
    )
    with pytest.raises(ValueError):
        galop_url("2024-10-06", "İstanbul", 0)


def test_parse_2024_galop_page_and_leakage_guard():
    """Madde 1 & 4: 2024 fixture -> 8 horses, 10 workouts for #1, date < race_date, d400 float, effort str, zero leakage."""
    html_text = _read_gz_fixture("liderform_galop_2024-10-06_istanbul_1.html.gz")
    raw_data = parse_next_data(html_text)
    raw_race_data = raw_data["props"]["pageProps"]["raceData"]
    assert len(raw_race_data) == 8
    # Raw Next.js payload contains scrape-time career leakage fields that must never escape parser
    assert "races" in raw_race_data[0]
    assert "ranks" in raw_race_data[0]

    horses = parse_galop_horses(html_text)
    workouts = parse_galop_page(html_text, "2024-10-06")

    assert len(horses) == 8
    assert [h["horse_number"] for h in horses] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert {w["horse_number"] for w in workouts} == {1, 2, 3, 4, 5, 6, 7, 8}

    first_horse_workouts = [w for w in workouts if w["horse_number"] == 1]
    assert len(first_horse_workouts) == 10
    assert first_horse_workouts[0]["horse_name"] == "CHILDOF BOSPHORUS"
    assert first_horse_workouts[0]["ext_horse_id"] == "726567"
    assert first_horse_workouts[0]["date"] == "2024-10-04"
    assert first_horse_workouts[0]["city"] == "Kocaeli"
    assert first_horse_workouts[0]["kind"] == "SPRINT"
    assert first_horse_workouts[0]["d400"] == pytest.approx(25.0)
    assert first_horse_workouts[0]["d200"] is None
    assert first_horse_workouts[0]["effort"] == "UNDERRESTRAINT"

    assert len(workouts) == 80
    for w in workouts:
        assert w["date"] < "2024-10-06"
        assert isinstance(w["d400"], float) and w["d400"] > 0
        assert w["d200"] is None
        assert isinstance(w["effort"], str) and len(w["effort"]) > 0

    # Multi-minute split ('1.15.8' -> 75.8s, '1.03.4' -> 63.4s)
    mercanli_aug4 = next(
        w for w in workouts if w["horse_number"] == 2 and w["date"] == "2024-08-04"
    )
    assert mercanli_aug4["d1200"] == pytest.approx(75.8)
    assert mercanli_aug4["d1000"] == pytest.approx(63.4)
    assert mercanli_aug4["d400"] == pytest.approx(25.0)

    # Leakage guard: races / ranks / handicap appear nowhere in outputs
    assert FORBIDDEN_LEAK_KEYS.isdisjoint(_collect_all_dict_keys(horses))
    assert FORBIDDEN_LEAK_KEYS.isdisjoint(_collect_all_dict_keys(workouts))

    # Strict cutoff filter (< race_date, never <=)
    cutoff_filtered = parse_galop_page(html_text, "2024-10-04")
    assert 0 < len(cutoff_filtered) < len(workouts)
    assert all(w["date"] < "2024-10-04" for w in cutoff_filtered)


def test_parse_2015_galop_page_and_foreign_track():
    """Madde 1 & 4: 2015 fixture has workouts > 0, all date < 2015-10-04, no leakage, foreign track -> city=None."""
    html_text = _read_gz_fixture("liderform_galop_2015-10-04_istanbul_1.html.gz")
    workouts = parse_galop_page(html_text, "2015-10-04")

    assert len(workouts) > 0
    assert len(workouts) == 80
    assert all(w["date"] < "2015-10-04" for w in workouts)
    assert FORBIDDEN_LEAK_KEYS.isdisjoint(_collect_all_dict_keys(workouts))

    birkaya_sep19 = next(
        w for w in workouts if w["horse_number"] == 1 and w["date"] == "2015-09-19"
    )
    assert birkaya_sep19["horse_name"] == "BİRKAYA"
    assert birkaya_sep19["ext_horse_id"] == "439949"
    assert birkaya_sep19["city"] == "Bursa"
    assert birkaya_sep19["d800"] == pytest.approx(54.8)
    assert birkaya_sep19["d400"] == pytest.approx(27.8)
    assert birkaya_sep19["kg"] == pytest.approx(49.0)

    # '1.00.5' split -> 60.5s; weight_kg == 0 -> None
    derin_oct2 = next(
        w for w in workouts if w["horse_number"] == 8 and w["date"] == "2015-10-02"
    )
    assert derin_oct2["d800"] == pytest.approx(60.5)
    pamuk_jul22 = next(
        w for w in workouts if w["horse_number"] == 2 and w["date"] == "2015-07-22"
    )
    assert pamuk_jul22["kg"] is None

    # Synthetic check: foreign track maps to city=None; workouts on/after race_date are dropped
    synthetic_payload = {
        "props": {
            "pageProps": {
                "raceData": [
                    {
                        "horse_number": 1,
                        "horse": {"id": 999001, "name": "FOREIGN RUNNER"},
                        "races": [{"meeting_date": "2026-05-01", "rank": 1}],
                        "ranks": {"first": 5},
                        "handicap": {"now": 95},
                        "workouts": [
                            {
                                "meeting_date": "2020-06-09",
                                "track": {"tjk_code": "LONGCHAMP", "country_code": "FRA"},
                                "track_type": "GALLOP",
                                "jockey": {"name": "J.DOE", "weight_kg": 55},
                                "graph": [{"label": 400, "value": "24.2"}],
                                "effort": "EASILY",
                                "going": "GOOD",
                                "inner_outer": "INNER",
                            },
                            {
                                "meeting_date": "2020-06-10",
                                "track": {"tjk_code": "ISTANBUL", "country_code": "TUR"},
                                "track_type": "SPRINT",
                                "jockey": {"name": "J.DOE", "weight_kg": 55},
                                "graph": [{"label": 400, "value": "23.8"}],
                            },
                        ],
                    }
                ]
            }
        }
    }
    syn_html = (
        f'<html><body><script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(synthetic_payload)}</script></body></html>"
    )
    syn_workouts = parse_galop_page(syn_html, "2020-06-10")
    assert len(syn_workouts) == 1
    assert syn_workouts[0]["city"] is None
    assert syn_workouts[0]["date"] == "2020-06-09"
    assert FORBIDDEN_LEAK_KEYS.isdisjoint(_collect_all_dict_keys(syn_workouts))


def test_horse_key_matching_and_insert_or_ignore_dedup(tmp_path):
    """Madde 2, 3 & 4: fake DB horse_key resolution, horse_ids upsert, and INSERT OR IGNORE dedup."""
    html_2024 = _read_gz_fixture("liderform_galop_2024-10-06_istanbul_1.html.gz")
    conn = init_db(tmp_path / "liderform_test.db")
    try:
        race_id = "2024-10-06_İstanbul_1"
        conn.execute(
            "INSERT INTO races (race_id, date, city, race_no, status) VALUES (?, ?, ?, ?, ?)",
            (race_id, "2024-10-06", "İstanbul", 1, "result"),
        )
        # Seed runners for prog_no 1..6; leave 7 and 8 absent to test unmatched horse_key=None
        for prog_no in range(1, 7):
            conn.execute(
                "INSERT INTO runners (race_id, prog_no, horse_key, name, scratched) VALUES (?, ?, ?, ?, 0)",
                (race_id, prog_no, f"SIRE{prog_no}|DAM{prog_no}|2022", f"HORSE_{prog_no}"),
            )
        conn.commit()

        assert resolve_horse_key(conn, race_id, 1) == "SIRE1|DAM1|2022"
        assert resolve_horse_key(conn, race_id, 8) is None

        st1 = ingest_galop_page(conn, race_id, "2024-10-06", html_2024)
        assert st1 == {
            "horses": 8,
            "unmatched_horses": 2,
            "workouts": 80,
            "inserted_workouts": 80,
        }

        total_w = conn.execute("SELECT COUNT(*) FROM workouts WHERE source = ?", (WORKOUT_SOURCE,)).fetchone()[0]
        assert total_w == 80

        matched_w = conn.execute(
            "SELECT DISTINCT horse_key FROM workouts WHERE horse_name = 'CHILDOF BOSPHORUS'"
        ).fetchall()
        assert matched_w == [("SIRE1|DAM1|2022",)]

        unmatched_w = conn.execute(
            "SELECT DISTINCT horse_key FROM workouts WHERE horse_name = 'NAUTILUS RUN'"
        ).fetchall()
        assert unmatched_w == [(None,)]

        horse_id_rows = dict(
            conn.execute(
                "SELECT ext_id, horse_key FROM horse_ids WHERE source = ?",
                (WORKOUT_SOURCE,),
            ).fetchall()
        )
        assert len(horse_id_rows) == 8
        assert horse_id_rows["726567"] == "SIRE1|DAM1|2022"
        assert horse_id_rows["775116"] is None

        # Re-ingesting the same workouts (same horse in multiple races) -> INSERT OR IGNORE keeps 80 rows
        st2 = ingest_galop_page(conn, race_id, "2024-10-06", html_2024)
        assert st2["workouts"] == 80
        assert st2["inserted_workouts"] == 0
        assert conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0] == 80

        # Foreign workout (city=None) is also deduplicated across repeated insert_workouts calls
        foreign_row = [{
            "horse_key": "SIRE1|DAM1|2022",
            "horse_name": "CHILDOF BOSPHORUS",
            "ext_horse_id": "726567",
            "date": "2024-07-01",
            "city": None,
            "kind": "GALLOP",
            "d400": 24.6,
        }]
        assert insert_workouts(conn, foreign_row) == 1
        assert insert_workouts(conn, foreign_row) == 0
        assert conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0] == 81

        # If previously unmatched horse (#8, ext_id=775116) matches in another race, horse_ids upgrades NULL -> key
        insert_horse_ids(conn, [{
            "source": WORKOUT_SOURCE,
            "ext_id": "775116",
            "horse_key": "SIRE8|DAM8|2022",
            "horse_name": "NAUTILUS RUN",
        }])
        upgraded = conn.execute(
            "SELECT horse_key FROM horse_ids WHERE source = ? AND ext_id = '775116'",
            (WORKOUT_SOURCE,),
        ).fetchone()[0]
        assert upgraded == "SIRE8|DAM8|2022"
    finally:
        conn.close()


def test_backfill_targets_dry_run_and_block_stop(tmp_path):
    """Madde 3: domestic result target filtering, --dry-run no-write behavior, and immediate stop on 403/BTK."""
    html_2024 = _read_gz_fixture("liderform_galop_2024-10-06_istanbul_1.html.gz")
    conn = init_db(tmp_path / "backfill_test.db")
    try:
        conn.executemany(
            "INSERT INTO races (race_id, date, city, race_no, status) VALUES (?, ?, ?, ?, ?)",
            [
                ("2024-10-06_İstanbul_1", "2024-10-06", "İstanbul", 1, "result"),
                ("2024-10-06_İstanbul_2", "2024-10-06", "İstanbul", 2, "result"),
                ("2015-09-30_İstanbul_1", "2015-09-30", "İstanbul", 1, "result"),  # before 2015-10-01
                ("2024-10-06_İstanbul_3", "2024-10-06", "İstanbul", 3, "program"),  # not result
                ("2024-10-06_Longchamp_1", "2024-10-06", "Longchamp", 1, "result"),  # foreign
            ],
        )
        conn.commit()

        targets = load_target_races(conn, "2015-01-01", "2024-12-31")
        assert [t[0] for t in targets] == [
            "2024-10-06_İstanbul_1",
            "2024-10-06_İstanbul_2",
        ]

        # Dry-run processes without writing to DB or raw_dir
        dry_buf = io.StringIO()
        rc_dry = run_backfill(
            conn,
            str(tmp_path / "raw"),
            "2024-10-01",
            "2024-10-10",
            delay=0.0,
            max_races=1,
            dry_run=True,
            getter=lambda url, extra_headers=None: (200, html_2024.encode("utf-8"), url),
            sleep_fn=lambda _: None,
            out=dry_buf,
        )
        assert rc_dry == 0
        assert "[Yıl 2024] koşu=1 at=8 galop=80" in dry_buf.getvalue()
        assert conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0] == 0
        assert not fetched_ok(conn, FETCH_SOURCE, "2024-10-06_istanbul_1")

        # 403 Cloudflare block stops immediately on first request and prints WARP warning
        calls = []
        block_buf = io.StringIO()

        def cf_blocked(url, extra_headers=None):
            calls.append(url)
            return 403, b"<html><title>Attention Required! | Cloudflare</title></html>", url

        rc_block = run_backfill(
            conn,
            str(tmp_path / "raw"),
            "2024-10-01",
            "2024-10-10",
            delay=0.0,
            getter=cf_blocked,
            sleep_fn=lambda _: None,
            out=block_buf,
        )
        assert rc_block == 2
        assert len(calls) == 1
        assert "WARP kapalı olabilir" in block_buf.getvalue()
        assert not fetched_ok(conn, FETCH_SOURCE, "2024-10-06_istanbul_1")

        # BTK redirect / 5651 markers are also detected even on HTTP 200
        assert detect_liderform_block(
            "<html>5651 sayılı kanun uyarınca erişim engellenmiştir</html>",
            http_status=200,
            final_url="https://liderform.com.tr/program/galop/2024-10-06/istanbul/1",
        ) is not None
        assert detect_liderform_block(
            "<html>blocked</html>",
            http_status=200,
            final_url="http://uyari.btk.gov.tr/warning",
        ) is not None
    finally:
        conn.close()

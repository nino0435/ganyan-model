"""Tests for tools/load_cond.py: HTML/Hava parsing, dry-run, idempotence, and post-cutoff protection."""
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ganyan.db import init_db
from tools.backfill_cond import SCHEMA as BACKFILL_SCHEMA
from tools.load_cond import (
    CoverageError,
    compute_post_cutoff_digest,
    extract_hava_raw,
    format_report,
    main as load_cond_main,
    parse_day_block,
    parse_hava_text,
    run_load_cond,
)


def test_parse_hava_formats():
    cases = [
        (
            "29C,Parçalı Bulutlu,Nem%37",
            {"temp_c": 29.0, "rh": 37.0, "sky": "parcali_bulutlu", "windy": 0},
        ),
        (
            "AÇIK , 27 C , NEM %20",
            {"temp_c": 27.0, "rh": 20.0, "sky": "acik", "windy": 0},
        ),
        (
            "Az Bulutlu 17 C, Nem %25",
            {"temp_c": 17.0, "rh": 25.0, "sky": "az_bulutlu", "windy": 0},
        ),
        (
            "28 C,Çok Bulutlu(rüzgarlı),Nem%41",
            {"temp_c": 28.0, "rh": 41.0, "sky": "cok_bulutlu", "windy": 1},
        ),
        (
            "AÇIK 17'C NEM %57",
            {"temp_c": 17.0, "rh": 57.0, "sky": "acik", "windy": 0},
        ),
        (
            "17 C , YAĞMURLU , NEM &81",
            {"temp_c": 17.0, "rh": 81.0, "sky": "yagisli", "windy": 0},
        ),
        (
            "13 C GÖKGÜRÜLTÜLÜ SAĞNAK YAĞIŞ %89 NEM",
            {"temp_c": 13.0, "rh": 89.0, "sky": "yagisli", "windy": 0},
        ),
        (
            "Hava Çok Bulutlu Sıcaklık 10 Derece Nem %91",
            {"temp_c": 10.0, "rh": 91.0, "sky": "cok_bulutlu", "windy": 0},
        ),
        (
            "13 °C, Az Bulutlu, Nem %32, Rüzgar Doğu'dan 29 km/sa",
            {"temp_c": 13.0, "rh": 32.0, "sky": "az_bulutlu", "windy": 1},
        ),
        (
            "23C,G.G.S.Yağışlı,Nem%57",
            {"temp_c": 23.0, "rh": 57.0, "sky": "yagisli", "windy": 0},
        ),
        (
            "HAFİF YAĞMURLU 14,4'C NEM %79",
            {"temp_c": 14.4, "rh": 79.0, "sky": "yagisli", "windy": 0},
        ),
        (
            "14,Çok Bulutlu,Nem%72",
            {"temp_c": 14.0, "rh": 72.0, "sky": "cok_bulutlu", "windy": 0},
        ),
        (
            "Sıcaklık 14 Çok Bulutlu Nem %69",
            {"temp_c": 14.0, "rh": 69.0, "sky": "cok_bulutlu", "windy": 0},
        ),
        (
            "AZ BULUTLU 33\" NEM %34",
            {"temp_c": 33.0, "rh": 34.0, "sky": "az_bulutlu", "windy": 0},
        ),
        (
            "sıcaklık 12°C, nem, hava çok bulutlu",
            {"temp_c": 12.0, "rh": None, "sky": "cok_bulutlu", "windy": 0},
        ),
        (
            "2 C, Kar Yağışlı, Nem %92",
            {"temp_c": 2.0, "rh": 92.0, "sky": "karli", "windy": 0},
        ),
        (
            "ÇOK BULUTLU/RÜZGARLI 24'C , NEM % 18",
            {"temp_c": 24.0, "rh": 18.0, "sky": "cok_bulutlu", "windy": 1},
        ),
        (
            "HAFİF SAĞANAK YAĞIŞLI,21C,NEM/81",
            {"temp_c": 21.0, "rh": 81.0, "sky": "yagisli", "windy": 0},
        ),
    ]
    for raw_txt, exp in cases:
        got = parse_hava_text(raw_txt)
        assert got["temp_c"] == pytest.approx(exp["temp_c"]), raw_txt
        if exp["rh"] is None:
            assert got["rh"] is None, raw_txt
        else:
            assert got["rh"] == pytest.approx(exp["rh"]), raw_txt
        assert got["sky"] == exp["sky"], raw_txt
        assert got["windy"] == exp["windy"], raw_txt

    # HTML extraction cleans raceWeather spans and right-floated PDF links
    html_block = """
    <span class="raceWeatherGreen"> &#199;im: &#199;ok Yumu&#351;ak 4,2 </span>
    <span class="raceWeatherBrown"> Kum: Normal </span>
    Hava: 28 C,&#199;ok Bulutlu(r&#252;zgarl&#305;),Nem%41
    <span style="float: right;"><a id="PDFBulten" target="_blank" href="https://medya-cdn.tjk.org/x.pdf">PDF Bülten</a></span>
    """
    parsed = parse_day_block(html_block)
    assert parsed["cim_raw"] == "Çim: Çok Yumuşak 4,2"
    assert parsed["kum_raw"] == "Kum: Normal"
    assert parsed["sentetik_raw"] is None
    assert parsed["hava_raw"] == "28 C,Çok Bulutlu(rüzgarlı),Nem%41"
    assert parsed["temp_c"] == pytest.approx(28.0)
    assert parsed["rh"] == pytest.approx(41.0)
    assert parsed["sky"] == "cok_bulutlu"
    assert parsed["windy"] == 1

    no_hava_html = """
    <span class="raceWeatherBrown"> Kum: Normal </span>
    <span style="float: right;"><a id="PDFBulten" href="x.pdf">PDF Bülten</a></span>
    """
    assert extract_hava_raw(no_hava_html) is None


def _seed_test_dbs(tmp_path):
    bf_path = tmp_path / "cond_backfill.sqlite"
    db_path = tmp_path / "ganyan.db"

    bf = sqlite3.connect(str(bf_path))
    bf.executescript(BACKFILL_SCHEMA)
    bf.executemany(
        "INSERT INTO day (date, city, http, bytes, block, n_races, fetched_at) VALUES (?,?,?,?,?,?,?)",
        [
            (
                "2024-06-16",
                "İstanbul",
                200,
                300,
                '<span class="raceWeatherGreen"> Çim: Çok Yumuşak 4,2 </span>'
                '<span class="raceWeatherBrown"> Kum: Normal </span>'
                'Hava: 28 C,Çok Bulutlu(rüzgarlı),Nem%41'
                '<span style="float: right;"><a id="PDFBulten">PDF Bülten</a></span>',
                9,
                "2026-11-24T20:00:00+00:00",
            ),
            (
                "2024-06-17",
                "Adana",
                200,
                250,
                '<span class="raceWeatherGreen"> Çim: Buzlu 9,9 </span>'
                'Hava: 19 C, BilinmeyenGok, Nem %50',
                7,
                "2026-11-24T20:01:00+00:00",
            ),
            (
                "2024-10-26",
                "Ankara",
                200,
                250,
                '<span class="raceWeatherBrown"> Kum: Normal </span>'
                '<span class="raceWeatherGreen"> Çim: Ağır 4,8 </span>'
                'Hava: 12 C, Açık, Nem %30',
                8,
                "2026-11-24T20:02:00+00:00",
            ),
        ],
    )
    bf.commit()
    bf.close()

    conn = init_db(db_path)
    conn.executemany(
        """
        INSERT INTO races (
            race_id, date, city, race_no, post_time, yg_no, cls, breed,
            distance, surface, status, track_cond_raw, track_cond
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            ("2024-06-16_İstanbul_1", "2024-06-16", "İstanbul", 1, "14:00", 1, "Handikap 15", "İngiliz", 1600, "Çim", "result", None, None),
            ("2024-06-16_İstanbul_2", "2024-06-16", "İstanbul", 2, "14:30", 1, "Şartlı 3", "Arap", 1400, "Kum", "result", None, None),
            ("2024-06-16_İstanbul_3", "2024-06-16", "İstanbul", 3, "15:00", 1, "Maiden", "İngiliz", 1500, "Sentetik", "result", None, None),
            ("2024-06-17_Adana_1", "2024-06-17", "Adana", 1, "14:00", 1, "Maiden", "İngiliz", 1200, "Çim", "result", None, None),
            ("2024-10-26_Ankara_1", "2024-10-26", "Ankara", 1, "14:00", 1, "Şartlı 4", "İngiliz", 1600, "Kum", "result", "Kum: Islak", "islak"),
            ("2024-10-26_Ankara_2", "2024-10-26", "Ankara", 2, "14:30", 1, "Grup 1", "İngiliz", 2000, "Çim", "result", "Çim: Normal 3,3", "normal"),
        ],
    )
    conn.commit()
    conn.close()
    return bf_path, db_path


def test_unknown_track_cond_and_sky_counted(tmp_path):
    bf_path, db_path = _seed_test_dbs(tmp_path)
    res = run_load_cond(backfill_path=bf_path, db_path=db_path, apply=False, d_from="2024-01-01", d_to="2024-12-31")
    assert res["unknown_track_conds"][("Çim", "Buzlu", "Çim: Buzlu 9,9")] == 1
    assert res["skipped_unknown_map"] == 1
    assert sum(res["unknown_sky"].values()) == 1
    assert "bilinmeyengok" in res["unknown_sky"]


def test_dry_run_does_not_modify_db(tmp_path):
    bf_path, db_path = _seed_test_dbs(tmp_path)
    rc = load_cond_main(["--backfill", str(bf_path), "--db", str(db_path), "--dry-run"])
    assert rc == 0

    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "day_cond" not in tables
    rows = conn.execute("SELECT race_id, track_cond_raw, track_cond FROM races WHERE date='2024-06-16' ORDER BY race_id").fetchall()
    conn.close()
    assert rows == [
        ("2024-06-16_İstanbul_1", None, None),
        ("2024-06-16_İstanbul_2", None, None),
        ("2024-06-16_İstanbul_3", None, None),
    ]


def test_apply_fills_only_empty_preserves_existing_and_sentetik(tmp_path):
    bf_path, db_path = _seed_test_dbs(tmp_path)

    conn = sqlite3.connect(str(db_path))
    before_post = compute_post_cutoff_digest(conn, cutoff="2024-10-25")
    conn.close()

    # Pass d_to=2024-12-31 deliberately to prove filled cells >= 2024-10-25 are NEVER overwritten even if present in backfill!
    res = run_load_cond(backfill_path=bf_path, db_path=db_path, apply=True, d_from="2024-01-01", d_to="2024-12-31")
    assert res["digest_before"] == before_post
    assert res["digest_after"] == before_post
    assert res["skipped_already_filled"] == 2

    conn = sqlite3.connect(str(db_path))
    races = dict(
        (rid, (raw, norm))
        for rid, raw, norm in conn.execute("SELECT race_id, track_cond_raw, track_cond FROM races").fetchall()
    )
    dc = conn.execute(
        "SELECT cim_raw, kum_raw, sentetik_raw, temp_c, rh, sky, windy FROM day_cond WHERE date='2024-06-16' AND city='İstanbul'"
    ).fetchone()
    conn.close()

    assert races["2024-06-16_İstanbul_1"] == ("Çim: Çok Yumuşak 4,2", "yumusak")
    assert races["2024-06-16_İstanbul_2"] == ("Kum: Normal", "normal")
    assert races["2024-06-16_İstanbul_3"] == (None, "bilinmiyor")
    # Unmapped Çim: Buzlu 9,9 must NOT pollute races.track_cond_raw
    assert races["2024-06-17_Adana_1"] == (None, None)
    # Pre-filled 2024-10-26 cells remain untouched
    assert races["2024-10-26_Ankara_1"] == ("Kum: Islak", "islak")
    assert races["2024-10-26_Ankara_2"] == ("Çim: Normal 3,3", "normal")
    assert dc == ("Çim: Çok Yumuşak 4,2", "Kum: Normal", None, 28.0, 41.0, "cok_bulutlu", 1)


def test_apply_idempotent(tmp_path):
    bf_path, db_path = _seed_test_dbs(tmp_path)
    res1 = run_load_cond(backfill_path=bf_path, db_path=db_path, apply=True, d_from="2015-01-01", d_to="2024-10-24")
    assert res1["applied_race_updates"] == 3
    assert res1["applied_day_cond_rows"] == 2

    conn = sqlite3.connect(str(db_path))
    snap1_races = conn.execute("SELECT race_id, track_cond_raw, track_cond FROM races ORDER BY race_id").fetchall()
    snap1_dc = conn.execute("SELECT * FROM day_cond ORDER BY date, city").fetchall()
    conn.close()

    res2 = run_load_cond(backfill_path=bf_path, db_path=db_path, apply=True, d_from="2015-01-01", d_to="2024-10-24")
    assert res2["planned_race_updates"] == 0
    assert res2["applied_race_updates"] == 0

    conn = sqlite3.connect(str(db_path))
    snap2_races = conn.execute("SELECT race_id, track_cond_raw, track_cond FROM races ORDER BY race_id").fetchall()
    snap2_dc = conn.execute("SELECT * FROM day_cond ORDER BY date, city").fetchall()
    conn.close()

    assert snap1_races == snap2_races
    assert snap1_dc == snap2_dc


def test_default_to_uses_max_result_date_and_post_cutoff_checks(tmp_path):
    bf_path = tmp_path / "cond_backfill.sqlite"
    db_path = tmp_path / "ganyan.db"

    bf = sqlite3.connect(str(bf_path))
    bf.executescript(BACKFILL_SCHEMA)
    bf.executemany(
        "INSERT INTO day (date, city, http, bytes, block, n_races, fetched_at) VALUES (?,?,?,?,?,?,?)",
        [
            (
                "2025-05-10",
                "İstanbul",
                200,
                300,
                '<span class="raceWeatherGreen"> Çim: Ağır 4,8 </span>'
                '<span class="raceWeatherBrown"> Kum: Normal </span>'
                "Hava: 22 C, Açık, Nem %45",
                8,
                "2026-11-25T00:00:00+00:00",
            ),
        ],
    )
    bf.commit()
    bf.close()

    conn = init_db(db_path)
    conn.executemany(
        """
        INSERT INTO races (
            race_id, date, city, race_no, post_time, yg_no, cls, breed,
            distance, surface, status, track_cond_raw, track_cond
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            ("2025-05-10_İstanbul_1", "2025-05-10", "İstanbul", 1, "14:00", 1, "Şartlı 3", "İngiliz", 1400, "Kum", "result", "Kum: Normal", "normal"),
            ("2025-05-10_İstanbul_2", "2025-05-10", "İstanbul", 2, "14:30", 1, "Handikap 15", "İngiliz", 1600, "Çim", "result", "Çim: Normal 3,3", "normal"),
            ("2025-05-10_İstanbul_3", "2025-05-10", "İstanbul", 3, "15:00", 1, "Maiden", "Arap", 1200, "Kum", "result", None, None),
            # Scheduled future race must not become default --to
            ("2025-05-11_Ankara_1", "2025-05-11", "Ankara", 1, "14:00", 1, "Maiden", "İngiliz", 1200, "Kum", "scheduled", None, None),
        ],
    )
    conn.commit()
    conn.close()

    res = run_load_cond(backfill_path=bf_path, db_path=db_path, apply=True)
    assert res["d_to"] == "2025-05-10"
    assert res["digest_before"] == res["digest_after"]
    assert res["digest_before"]["filled"] == 2
    assert res["post_cutoff_new_filled_planned"] == 1
    assert res["post_cutoff_new_filled_applied"] == 1
    assert res["post_cutoff_compared"] == 2
    assert res["post_cutoff_norm_mismatch"] == 1

    conn = sqlite3.connect(str(db_path))
    races = dict(
        (rid, (raw, norm))
        for rid, raw, norm in conn.execute("SELECT race_id, track_cond_raw, track_cond FROM races").fetchall()
    )
    conn.close()
    assert races["2025-05-10_İstanbul_1"] == ("Kum: Normal", "normal")
    assert races["2025-05-10_İstanbul_2"] == ("Çim: Normal 3,3", "normal")
    assert races["2025-05-10_İstanbul_3"] == ("Kum: Normal", "normal")

    report = format_report(res)
    assert "Kapsama" in report
    assert "yeni_doldurulan=1" in report
    assert "Crawl vs DB" in report


def test_apply_rejected_when_coverage_below_threshold(tmp_path, capsys):
    bf_path = tmp_path / "cond_backfill.sqlite"
    db_path = tmp_path / "ganyan.db"

    bf = sqlite3.connect(str(bf_path))
    bf.executescript(BACKFILL_SCHEMA)
    bf.execute(
        "INSERT INTO day (date, city, http, bytes, block, n_races, fetched_at) VALUES (?,?,?,?,?,?,?)",
        (
            "2024-06-16",
            "İstanbul",
            200,
            200,
            '<span class="raceWeatherBrown"> Kum: Normal </span>Hava: 25 C, Açık, Nem %40',
            7,
            "2026-11-25T00:00:00+00:00",
        ),
    )
    bf.commit()
    bf.close()

    conn = init_db(db_path)
    conn.executemany(
        """
        INSERT INTO races (
            race_id, date, city, race_no, post_time, yg_no, cls, breed,
            distance, surface, status, track_cond_raw, track_cond
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            ("2024-06-16_İstanbul_1", "2024-06-16", "İstanbul", 1, "14:00", 1, "Şartlı 3", "İngiliz", 1400, "Kum", "result", None, None),
            ("2024-06-17_Adana_1", "2024-06-17", "Adana", 1, "14:00", 1, "Şartlı 3", "İngiliz", 1400, "Kum", "result", None, None),
        ],
    )
    conn.commit()
    conn.close()

    rc_dry = load_cond_main(["--backfill", str(bf_path), "--db", str(db_path), "--dry-run"])
    assert rc_dry == 0
    out_dry = capsys.readouterr().out
    assert "Kapsama" in out_dry
    assert "1/2" in out_dry
    assert "%50.00" in out_dry

    with pytest.raises(CoverageError):
        run_load_cond(backfill_path=bf_path, db_path=db_path, apply=True)

    rc_apply = load_cond_main(["--backfill", str(bf_path), "--db", str(db_path), "--apply"])
    assert rc_apply != 0
    err_apply = capsys.readouterr().err
    assert "Kapsama yetersiz" in err_apply

    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    rows = conn.execute("SELECT race_id, track_cond_raw, track_cond FROM races ORDER BY race_id").fetchall()
    conn.close()
    assert "day_cond" not in tables
    assert rows == [
        ("2024-06-16_İstanbul_1", None, None),
        ("2024-06-17_Adana_1", None, None),
    ]

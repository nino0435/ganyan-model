"""Offline tests for Yenibeygir parser, DB runner matching, ext_ratings upsert, and backfill."""
import datetime
import gzip
import io
import os
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.db import fetched_ok, init_db
from ganyan.sources.yenibeygir import (
    FETCH_SOURCE,
    SOURCE,
    city_slug,
    insert_ext_ratings,
    match_and_save_ratings,
    match_runner_horse_key,
    parse_results_page,
    results_url,
)
from ganyan.tjk import DOMESTIC_CITIES
from scripts.backfill_yenibeygir import list_target_city_days, run_backfill

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _read_gz_fixture(name: str) -> str:
    with gzip.open(FIXTURES / name, "rt", encoding="utf-8") as f:
        return f.read()


def _read_gz_fixture_raw_bytes(name: str) -> bytes:
    with gzip.open(FIXTURES / name, "rb") as f:
        return f.read()


class _FakeHTTPResponse:
    def __init__(self, body: bytes, status: int = 200, url: str = "https://yenibeygir.com/"):
        self._body = body
        self.status = status
        self._url = url

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_city_slug_and_results_url():
    expected_slugs = {
        "İstanbul": "istanbul",
        "İzmir": "izmir",
        "Adana": "adana",
        "Bursa": "bursa",
        "Ankara": "ankara",
        "Antalya": "antalya",
        "Şanlıurfa": "sanliurfa",
        "Elazığ": "elazig",
        "Kocaeli": "kocaeli",
        "Diyarbakır": "diyarbakir",
    }
    for city in DOMESTIC_CITIES:
        assert city_slug(city) == expected_slugs[city]

    assert results_url("2015-10-04", "İstanbul") == "https://yenibeygir.com/04-10-2015/istanbul/sonuclar"
    assert (
        results_url(datetime.date(2024, 10, 6), "Şanlıurfa", race_no=4)
        == "https://yenibeygir.com/06-10-2024/sanliurfa/4/sonuclar"
    )


def test_parse_2015_fixture_gulerce_and_edge_cases():
    html_text = _read_gz_fixture("yenibeygir_sonuclar_2015-10-04_diyarbakir.html.gz")
    parsed = parse_results_page(html_text, "2015-10-04")

    # Even though URL/filename requested 'diyarbakir', page displays İstanbul
    assert parsed["city"] == "İstanbul"
    assert len(parsed["races"]) == 7
    assert [r["race_no"] for r in parsed["races"]] == [1, 2, 3, 4, 5, 6, 7]

    race1 = parsed["races"][0]
    assert race1["race_no"] == 1
    winner = next(r for r in race1["runners"] if r["finish"] == 1)
    assert winner["name"] == "GÜLERCE"
    assert winner["prog_no"] == 5
    assert winner["hiz"] == 55
    assert winner["sire"] == "BİLGİN"
    assert winner["dam"] == "DEFNE"
    assert winner["klv"] == 6
    assert winner["blt"] == "13"

    # Race 2: AGF column with 'Blt. Ort' tooltip, negative hiz, and scratched horse
    race2_by_prog = {r["prog_no"]: r for r in parsed["races"][1]["runners"]}
    assert race2_by_prog[3]["name"] == "BONCUK"
    assert race2_by_prog[3]["hiz"] == 32
    assert race2_by_prog[3]["blt"] == "6"

    assert race2_by_prog[5]["name"] == "DİLIR"
    assert race2_by_prog[5]["hiz"] == -207
    assert race2_by_prog[5]["blt"] == "23"

    scratched = race2_by_prog[10]
    assert scratched["name"] == "NEFESİM"
    assert scratched["finish"] is None
    assert scratched["hiz"] is None

    # Race 4: kulvar cell with '<sup>t</sup>' preference marker
    race4_by_prog = {r["prog_no"]: r for r in parsed["races"][3]["runners"]}
    assert race4_by_prog[2]["name"] == "MY GRAND BOY"
    assert race4_by_prog[2]["klv"] == 10
    assert race4_by_prog[2]["hiz"] == 142


def test_parse_2024_fixture_races_and_hiz_coverage():
    html_text = _read_gz_fixture("yenibeygir_sonuclar_2024-10-06_diyarbakir.html.gz")
    parsed = parse_results_page(html_text, "2024-10-06")

    assert parsed["city"] == "İstanbul"
    assert len(parsed["races"]) > 0

    all_runners = [r for race in parsed["races"] for r in race["runners"]]
    assert len(all_runners) > 0
    hiz_filled = [r for r in all_runners if r["hiz"] is not None]
    assert (len(hiz_filled) / len(all_runners)) > 0.80

    # Zero speed score (0) must be preserved as 0, not dropped as None
    race8 = next(rc for rc in parsed["races"] if rc["race_no"] == 8)
    zagros = next(r for r in race8["runners"] if r["prog_no"] == 14)
    assert zagros["name"] == "ZAGROS ASLANI"
    assert zagros["hiz"] == 0


def test_parse_2010_layout_without_gec_cikis_column():
    html_2010 = """
    <div class="Bulten">
      <ul class="BultenTabs">
        <li class="selected"><span>İzmir Sonuçları</span></li>
      </ul>
      <div id="kosu_3" class="yarisRow">
        <div class="yarisHeader"><div class="yarisNo"><span>3</span><span>.</span></div></div>
        <table class="kosanAtlar">
          <thead>
            <tr>
              <th>Sıra</th><th>At İsmi</th><th>Yaş</th><th>Kilo</th><th>Jokey</th>
              <th></th><th>Sahip/Antr.</th><th>Klv</th><th>Derece</th><th>Hız</th>
              <th>Gny</th><th>Blt</th><th>Fark</th><th>Hnd</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="atno">1</td>
              <td class="atisimcell">GÜLERCE KG DB YP (5) BİLGİN - DEFNE</td>
              <td>3yad</td><td>57</td><td>J. Adı</td><td></td><td>S. Adı</td>
              <td class="kulvarcell"><span>4</span></td>
              <td>1.25.10</td><td><span>(71)</span></td>
              <td>3,10</td><td><span>-</span></td><td>2 B</td><td>60</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    """
    parsed = parse_results_page(html_2010, "2010-05-01")
    assert parsed["city"] == "İzmir"
    assert len(parsed["races"]) == 1
    assert parsed["races"][0]["race_no"] == 3
    r = parsed["races"][0]["runners"][0]
    assert r == {
        "prog_no": 5,
        "name": "GÜLERCE",
        "sire": "BİLGİN",
        "dam": "DEFNE",
        "finish": 1,
        "hiz": 71,
        "blt": "-",
        "klv": 4,
    }


def test_fake_db_matching_and_ext_ratings_upsert(tmp_path):
    conn = init_db(tmp_path / "fake.db")
    try:
        conn.executemany(
            "INSERT INTO races (race_id, date, city, race_no, status) VALUES (?, ?, ?, ?, 'result')",
            [
                ("2015-10-04_İstanbul_1", "2015-10-04", "İstanbul", 1),
                ("2015-10-04_İstanbul_2", "2015-10-04", "İstanbul", 2),
            ],
        )
        conn.executemany(
            """
            INSERT INTO runners (race_id, prog_no, horse_key, name, sire, dam)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                # Primary match via prog_no=5
                ("2015-10-04_İstanbul_1", 5, "BİLGİN|DEFNE|2012", "GÜLERCE", "BİLGİN", "DEFNE"),
                # Fallback match via sire+dam+name (prog_no is NULL, TJK dam carries '(FR)')
                ("2015-10-04_İstanbul_1", None, "KAFKASLI|NUZHA (FR)|2012", "PAMUK PRENSES", "KAFKASLI", "NUZHA (FR)"),
                # Fallback match with '(USA)' on sire and Turkish I/İ fold ('KALIMDOR' vs 'KALİMDOR')
                ("2015-10-04_İstanbul_2", None, "KALIMDOR|ACTIONMAX|2013", "MERCANLI HAKANCAN", "KALIMDOR (USA)", "ACTIONMAX"),
                # Zero speed rating + non-numeric blt ('-')
                ("2015-10-04_İstanbul_2", 9, "YILMABAŞAR|KINALI KUZU|2013", "ZAGROS ASLANI", "YILMABAŞAR", "KINALI KUZU"),
            ],
        )
        conn.commit()

        synthetic_parsed = {
            "city": "İstanbul",
            "races": [
                {
                    "race_no": 1,
                    "runners": [
                        {
                            "prog_no": 5,
                            "name": "GÜLERCE",
                            "sire": "BİLGİN",
                            "dam": "DEFNE",
                            "finish": 1,
                            "hiz": 55,
                            "blt": "13",
                            "klv": 6,
                        },
                        {
                            "prog_no": 2,
                            "name": "PAMUK PRENSES",
                            "sire": "KAFKASLI",
                            "dam": "NUZHA",
                            "finish": 2,
                            "hiz": 56,
                            "blt": "5",
                            "klv": 7,
                        },
                        {
                            "prog_no": 99,
                            "name": "KAYIP AT",
                            "sire": "BABA",
                            "dam": "ANNE",
                            "finish": 3,
                            "hiz": 40,
                            "blt": "8",
                            "klv": 1,
                        },
                    ],
                },
                {
                    "race_no": 2,
                    "runners": [
                        {
                            "prog_no": 2,
                            "name": "MERCANLI HAKANCAN",
                            "sire": "KALİMDOR",
                            "dam": "ACTIONMAX",
                            "finish": 1,
                            "hiz": -18,
                            "blt": "12",
                            "klv": 8,
                        },
                        {
                            "prog_no": 9,
                            "name": "ZAGROS ASLANI",
                            "sire": "YILMABAŞAR",
                            "dam": "KINALI KUZU",
                            "finish": 15,
                            "hiz": 0,
                            "blt": "-",
                            "klv": 13,
                        },
                    ],
                },
            ],
        }

        assert (
            match_runner_horse_key(conn, "2015-10-04_İstanbul_1", synthetic_parsed["races"][0]["runners"][1])
            == "KAFKASLI|NUZHA (FR)|2012"
        )

        stats = match_and_save_ratings(conn, synthetic_parsed, "2015-10-04")
        assert stats["races"] == 2
        assert stats["runners"] == 5
        assert stats["hiz_filled"] == 5
        assert stats["matched"] == 4
        assert stats["unmatched"] == 1
        assert stats["rows_written"] == 7  # 4 hiz + 3 numeric blt ('-' skipped)

        saved = {
            (r[0], r[1], r[2], r[3]): r[4]
            for r in conn.execute(
                "SELECT source, race_id, horse_key, name, value FROM ext_ratings"
            ).fetchall()
        }
        assert saved[(SOURCE, "2015-10-04_İstanbul_1", "BİLGİN|DEFNE|2012", "hiz")] == pytest.approx(55.0)
        assert saved[(SOURCE, "2015-10-04_İstanbul_1", "BİLGİN|DEFNE|2012", "blt")] == pytest.approx(13.0)
        assert saved[(SOURCE, "2015-10-04_İstanbul_1", "KAFKASLI|NUZHA (FR)|2012", "hiz")] == pytest.approx(56.0)
        assert saved[(SOURCE, "2015-10-04_İstanbul_2", "KALIMDOR|ACTIONMAX|2013", "hiz")] == pytest.approx(-18.0)
        assert saved[(SOURCE, "2015-10-04_İstanbul_2", "YILMABAŞAR|KINALI KUZU|2013", "hiz")] == pytest.approx(0.0)
        assert (SOURCE, "2015-10-04_İstanbul_2", "YILMABAŞAR|KINALI KUZU|2013", "blt") not in saved

        # INSERT OR REPLACE overwrites existing value without duplicating rows
        insert_ext_ratings(conn, [(SOURCE, "2015-10-04_İstanbul_1", "BİLGİN|DEFNE|2012", "hiz", 61)])
        total_cnt = conn.execute("SELECT COUNT(*) FROM ext_ratings").fetchone()[0]
        updated_val = conn.execute(
            "SELECT value FROM ext_ratings WHERE source=? AND race_id=? AND horse_key=? AND name='hiz'",
            (SOURCE, "2015-10-04_İstanbul_1", "BİLGİN|DEFNE|2012"),
        ).fetchone()[0]
        assert total_cnt == 7
        assert updated_val == pytest.approx(61.0)
    finally:
        conn.close()


def test_backfill_end_to_end_dry_run_and_warp_stops(tmp_path):
    db_path = tmp_path / "backfill.db"
    raw_dir = tmp_path / "raw_yb"

    conn = init_db(db_path)
    try:
        conn.executemany(
            "INSERT INTO races (race_id, date, city, race_no, status) VALUES (?, ?, ?, ?, 'result')",
            [
                ("2009-12-31_İstanbul_1", "2009-12-31", "İstanbul", 1),  # pre-2010 ignored
                ("2015-10-04_Meydan_1", "2015-10-04", "Meydan", 1),      # foreign ignored
                ("2015-10-04_İstanbul_1", "2015-10-04", "İstanbul", 1),
                ("2024-10-06_İstanbul_1", "2024-10-06", "İstanbul", 1),
            ],
        )
        conn.executemany(
            "INSERT INTO runners (race_id, prog_no, horse_key, name, sire, dam) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("2015-10-04_İstanbul_1", 5, "BİLGİN|DEFNE|2012", "GÜLERCE", "BİLGİN", "DEFNE"),
                ("2024-10-06_İstanbul_1", 2, "KALIMDOR|ACTIONMAX|2022", "MERCANLI HAKANCAN", "KALIMDOR", "ACTIONMAX"),
            ],
        )
        conn.commit()
        assert list_target_city_days(conn) == [
            ("2024-10-06", "İstanbul"),
            ("2015-10-04", "İstanbul"),
        ]
    finally:
        conn.close()

    # 1) guvenliinternet redirect stops immediately and warns about WARP
    buf_block = io.StringIO()
    code_block, _ = run_backfill(
        db_path=db_path,
        raw_dir=raw_dir,
        delay=0.0,
        urlopen_fn=lambda req, timeout=20: _FakeHTTPResponse(
            b"<html><body>guvenliinternet uyari sayfasi</body></html>",
            status=200,
            url="http://uyari.guvenliinternet.org.tr/",
        ),
        sleep_fn=lambda _: None,
        out=buf_block,
    )
    assert code_block != 0
    assert "WARP kapalı olabilir" in buf_block.getvalue()
    assert not (raw_dir / "2024" / "2024-10-06_istanbul.html.gz").exists()

    # 2) Connection error (URLError) stops immediately and warns about WARP
    buf_net = io.StringIO()

    def _raise_url_error(req, timeout=20):
        raise urllib.error.URLError("Connection reset by peer")

    code_net, _ = run_backfill(
        db_path=db_path,
        raw_dir=raw_dir,
        delay=0.0,
        urlopen_fn=_raise_url_error,
        sleep_fn=lambda _: None,
        out=buf_net,
    )
    assert code_net != 0
    assert "WARP kapalı olabilir" in buf_net.getvalue()

    # 3) Dry-run computes year summaries without touching raw_dir or ext_ratings
    raw_2015 = _read_gz_fixture_raw_bytes("yenibeygir_sonuclar_2015-10-04_diyarbakir.html.gz")
    raw_2024 = _read_gz_fixture_raw_bytes("yenibeygir_sonuclar_2024-10-06_diyarbakir.html.gz")

    def _fake_urlopen(req, timeout=20):
        url = req.full_url
        if "06-10-2024" in url:
            return _FakeHTTPResponse(raw_2024, status=200, url=url)
        return _FakeHTTPResponse(raw_2015, status=200, url=url)

    buf_dry = io.StringIO()
    code_dry, summaries_dry = run_backfill(
        db_path=db_path,
        raw_dir=raw_dir,
        delay=0.0,
        dry_run=True,
        urlopen_fn=_fake_urlopen,
        sleep_fn=lambda _: None,
        out=buf_dry,
    )
    assert code_dry == 0
    assert summaries_dry[2024]["races"] > 0
    assert summaries_dry[2015]["races"] == 7
    assert not any(raw_dir.rglob("*.html.gz"))  # dry-run ham dosya yazmaz (dizin önceki adımlarda açılmış olabilir)

    # 4) Full write pass persists .html.gz, fetch_log, and ext_ratings
    buf_ok = io.StringIO()
    code_ok, _ = run_backfill(
        db_path=db_path,
        raw_dir=raw_dir,
        delay=0.0,
        dry_run=False,
        urlopen_fn=_fake_urlopen,
        sleep_fn=lambda _: None,
        out=buf_ok,
    )
    assert code_ok == 0
    out_txt = buf_ok.getvalue()
    assert "[Yıl 2024]" in out_txt and "hız dolu=" in out_txt
    assert "[Yıl 2015]" in out_txt and "eşleşmeyen=" in out_txt
    assert (raw_dir / "2015" / "2015-10-04_istanbul.html.gz").exists()
    assert (raw_dir / "2024" / "2024-10-06_istanbul.html.gz").exists()

    conn_check = init_db(db_path)
    try:
        assert fetched_ok(conn_check, FETCH_SOURCE, "2015-10-04:İstanbul")
        assert fetched_ok(conn_check, FETCH_SOURCE, "2024-10-06:İstanbul")
        gulerce_hiz = conn_check.execute(
            "SELECT value FROM ext_ratings WHERE source=? AND race_id=? AND horse_key=? AND name='hiz'",
            (SOURCE, "2015-10-04_İstanbul_1", "BİLGİN|DEFNE|2012"),
        ).fetchone()[0]
        assert gulerce_hiz == pytest.approx(55.0)
    finally:
        conn_check.close()

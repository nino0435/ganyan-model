"""Tests for Sporx 'hazır kuponlar' parser (ganyan.tips) and collector (scripts.tips_collect)."""
import csv
import datetime
import gzip
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ganyan.tips import content_hash, parse_sporx_coupons
from scripts import tips_collect

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sporx_hazir_kuponlar.html"
IST_TZ = ZoneInfo("Europe/Istanbul")

ALTILI_TIPSTERS = {"fenomen_tilki", "editorun_kuponu", "hipodrom_guzeli"}
AI_TIPSTERS = {"sprintmaster", "beygirbooster"}
ALL_TIPSTERS = ALTILI_TIPSTERS | AI_TIPSTERS
EXPECTED_KEYS = {"tipster", "kind", "altili_name", "leg_no", "race_ref", "picks", "banko"}


def _assert_numeric_picks(picks_str):
    assert isinstance(picks_str, str) and picks_str
    assert " " not in picks_str
    parts = picks_str.split(",")
    assert len(parts) >= 1
    for p in parts:
        assert p.isdigit(), f"Non-numeric pick {p!r} in {picks_str!r}"
        assert 1 <= int(p) <= 30, f"Out-of-range horse number {p!r} in {picks_str!r}"


def test_parse_fixture_finds_all_five_profiles():
    raw = FIXTURE_PATH.read_bytes()
    rows = parse_sporx_coupons(raw)

    assert len(rows) == 20
    assert {r["tipster"] for r in rows} == ALL_TIPSTERS
    for r in rows:
        assert set(r.keys()) == EXPECTED_KEYS


def test_parse_fixture_altili_six_legs_and_exact_values():
    raw = FIXTURE_PATH.read_bytes()
    rows = parse_sporx_coupons(raw)

    by_tipster = {
        t: [r for r in rows if r["tipster"] == t]
        for t in ALTILI_TIPSTERS
    }
    for tipster, prof in by_tipster.items():
        assert len(prof) == 6, f"{tipster} expected 6 legs, got {len(prof)}"
        assert [r["leg_no"] for r in prof] == [1, 2, 3, 4, 5, 6]
        for r in prof:
            assert r["kind"] == "altili"
            assert r["altili_name"] == "İstanbul II. Altılı Ganyan"
            assert r["race_ref"] is None
            _assert_numeric_picks(r["picks"])

    tilki = {r["leg_no"]: r for r in by_tipster["fenomen_tilki"]}
    assert {r["banko"] for r in tilki.values()} == {"GHOST COMMANDER"}
    assert tilki[1]["picks"] == "2"
    assert tilki[2]["picks"] == "7,2,6,1,4,13,12,3,11,10"
    assert tilki[3]["picks"] == "6,5,2,3,7,1,4"
    assert tilki[4]["picks"] == "1"
    assert tilki[5]["picks"] == "7,1,5,6,2,3,4,8"
    assert tilki[6]["picks"] == "2,7,6,1,9,12,3,8,11,14"

    editor = {r["leg_no"]: r for r in by_tipster["editorun_kuponu"]}
    assert {r["banko"] for r in editor.values()} == {"TONBİ"}
    assert editor[1]["picks"] == "3,2,8,1,7,4,5,6,9,10"
    assert editor[3]["picks"] == "5"
    assert editor[4]["picks"] == "4"
    assert editor[6]["picks"] == "2,7,1,3,6,4,9,8,11,14,13"

    hipodrom = {r["leg_no"]: r for r in by_tipster["hipodrom_guzeli"]}
    assert {r["banko"] for r in hipodrom.values()} == {"HAYRETBİŞEY"}
    assert hipodrom[1]["picks"] == "7,3,2,8,1,4,5,6,9,10"
    assert hipodrom[2]["picks"] == "4"
    assert hipodrom[3]["picks"] == "6"
    assert hipodrom[6]["picks"] == "7,2,4,3,9,1,6,8,11,14,13"


def test_parse_fixture_ai_single_race_rows():
    raw = FIXTURE_PATH.read_bytes()
    rows = parse_sporx_coupons(raw)

    sprint = [r for r in rows if r["tipster"] == "sprintmaster"]
    assert sprint == [{
        "tipster": "sprintmaster",
        "kind": "tek_kosu",
        "altili_name": None,
        "leg_no": None,
        "race_ref": "İstanbul 4. koşu",
        "picks": "",
        "banko": "ROCK FOR EVER",
    }]

    beygir = [r for r in rows if r["tipster"] == "beygirbooster"]
    assert beygir == [{
        "tipster": "beygirbooster",
        "kind": "tek_kosu",
        "altili_name": None,
        "leg_no": None,
        "race_ref": "İstanbul 9. koşu",
        "picks": "",
        "banko": "GLONASS",
    }]


def test_content_hash_stability_and_str_input():
    raw = FIXTURE_PATH.read_bytes()
    rows_bytes = parse_sporx_coupons(raw)
    rows_str = parse_sporx_coupons(raw.decode("iso-8859-9", errors="replace"))
    assert rows_bytes == rows_str

    h1 = content_hash(rows_bytes)
    h2 = content_hash(list(reversed(rows_bytes)))
    assert len(h1) == 16
    assert all(c in "0123456789abcdef" for c in h1)
    assert h1 == h2

    mutated_picks = [dict(r) for r in rows_bytes]
    altili_idx = next(i for i, r in enumerate(mutated_picks) if r["kind"] == "altili")
    mutated_picks[altili_idx]["picks"] = "29,30"
    assert content_hash(mutated_picks) != h1

    mutated_banko = [dict(r) for r in rows_bytes]
    mutated_banko[0]["banko"] = "BASKA AT"
    assert content_hash(mutated_banko) != h1


def test_collect_writes_csv_gz_state_and_skips_unchanged(tmp_path, monkeypatch, capsys):
    raw = FIXTURE_PATH.read_bytes()
    monkeypatch.setattr(tips_collect, "get", lambda url, **kw: (200, raw))

    t1 = datetime.datetime(2026, 11, 15, 11, 30, 45, tzinfo=IST_TZ)
    rc1 = tips_collect.collect_tips(out_dir=tmp_path, now=t1)
    assert rc1 == 0
    capsys.readouterr()

    csv_path = tmp_path / "tips.csv"
    state_path = tmp_path / "state.json"
    gz_path_1 = tmp_path / "raw" / "2026-11-15" / "113045.html.gz"

    assert csv_path.exists()
    assert state_path.exists()
    assert gz_path_1.exists()
    assert gzip.decompress(gz_path_1.read_bytes()) == raw

    state_1 = json.loads(state_path.read_text(encoding="utf-8"))
    expected_hash = content_hash(parse_sporx_coupons(raw))
    assert state_1["content_hash"] == expected_hash
    assert state_1["captured_at"] == "2026-11-15T11:30:45+03:00"

    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == [
            "captured_at",
            "tipster",
            "kind",
            "altili_name",
            "leg_no",
            "race_ref",
            "picks",
            "banko",
            "content_hash",
        ]
        csv_rows_1 = list(reader)
    assert len(csv_rows_1) == 20
    assert all(r["captured_at"] == "2026-11-15T11:30:45+03:00" for r in csv_rows_1)
    assert all(r["content_hash"] == expected_hash for r in csv_rows_1)
    assert {r["banko"] for r in csv_rows_1} == {
        "GHOST COMMANDER",
        "TONBİ",
        "HAYRETBİŞEY",
        "ROCK FOR EVER",
        "GLONASS",
    }

    # Second run with identical content -> must NOT write anything
    t2 = datetime.datetime(2026, 11, 15, 11, 45, 0, tzinfo=IST_TZ)
    rc2 = tips_collect.collect_tips(out_dir=tmp_path, now=t2)
    assert rc2 == 0
    out2 = capsys.readouterr().out.strip()
    assert out2 == "değişmedi"
    assert not (tmp_path / "raw" / "2026-11-15" / "114500.html.gz").exists()
    assert json.loads(state_path.read_text(encoding="utf-8")) == state_1
    with csv_path.open(encoding="utf-8", newline="") as f:
        assert len(list(csv.DictReader(f))) == 20

    # Third run with changed content -> appends to CSV (no duplicate header), writes new gz & state
    updated_html = (
        '<meta charset="iso-8859-9">'
        '<div>Yapay Zeka tahmincimiz<br>'
        '<span>SPRINTMASTER</span><br>bugün için öneriyor:<br>'
        '<b>BOLD PILOT (İstanbul 6.kş)</b></div>'
    ).encode("iso-8859-9")
    monkeypatch.setattr(tips_collect, "get", lambda url, **kw: (200, updated_html))

    t3 = datetime.datetime(2026, 11, 15, 12, 5, 9, tzinfo=IST_TZ)
    rc3 = tips_collect.main(["--out-dir", str(tmp_path), "--once"], now=t3)
    assert rc3 == 0

    gz_path_3 = tmp_path / "raw" / "2026-11-15" / "120509.html.gz"
    assert gz_path_3.exists()
    assert gzip.decompress(gz_path_3.read_bytes()) == updated_html

    state_3 = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_3["content_hash"] != expected_hash
    assert state_3["captured_at"] == "2026-11-15T12:05:09+03:00"

    raw_csv_lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert raw_csv_lines[0] == "captured_at,tipster,kind,altili_name,leg_no,race_ref,picks,banko,content_hash"
    assert sum(1 for ln in raw_csv_lines if ln.startswith("captured_at,")) == 1
    with csv_path.open(encoding="utf-8", newline="") as f:
        csv_rows_3 = list(csv.DictReader(f))
    assert len(csv_rows_3) == 21
    assert csv_rows_3[-1]["tipster"] == "sprintmaster"
    assert csv_rows_3[-1]["race_ref"] == "İstanbul 6. koşu"
    assert csv_rows_3[-1]["picks"] == ""
    assert csv_rows_3[-1]["banko"] == "BOLD PILOT"


def test_empty_page_and_missing_profiles_write_nothing(tmp_path, monkeypatch, capsys):
    assert parse_sporx_coupons(b"") == []
    assert parse_sporx_coupons("<html><body>Henüz kupon yok</body></html>") == []

    incomplete_html = (
        '<div><span>SPRINTMASTER</span><b></b></div>'
        '<div><div id="tahmin_tilki" class="tahmin_texts">'
        '<div>GHOST COMMANDER</div><div>İstanbul II. Altılı Ganyan</div></div>'
        '<div><div class="kupon-yazar-container">'
        + "".join('<div class="kupon-yazar-column"><div class="kupon-yazar-item">1</div></div>' for _ in range(5))
        + '</div></div></div>'
    )
    assert parse_sporx_coupons(incomplete_html) == []

    monkeypatch.setattr(
        tips_collect,
        "get",
        lambda url, **kw: (200, b"<html><body>Yapi degisti</body></html>"),
    )
    rc = tips_collect.collect_tips(
        out_dir=tmp_path,
        now="2026-11-15T10:00:00+03:00",
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "UYARI: parse 0 satır" in out
    assert not (tmp_path / "tips.csv").exists()
    assert not (tmp_path / "state.json").exists()
    assert not (tmp_path / "raw").exists()

    # Network failure also exits 0 without writing files
    monkeypatch.setattr(tips_collect, "get", lambda url, **kw: (None, b""))
    rc_net = tips_collect.collect_tips(out_dir=tmp_path, now="2026-11-15T10:05:00+03:00")
    assert rc_net == 0
    assert not (tmp_path / "tips.csv").exists()
    assert not (tmp_path / "state.json").exists()

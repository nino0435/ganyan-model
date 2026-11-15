"""Unit and end-to-end tests for hipodrom.com tips parsers and collector."""
from __future__ import annotations

import csv
import gzip
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.hipodrom_tips import (
    COMMENTS_URL,
    COUPONS_URL,
    PROGRAMS_URL,
    coupon_hash,
    parse_comments,
    parse_coupons,
    parse_programs,
)
from scripts.hipodrom_collect import (
    COMMENT_FIELDS,
    COUPON_FIELDS,
    PROGRAM_FIELDS,
    main,
    run,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_parse_coupons_fixture():
    raw_bytes = (FIXTURES / "hipodrom_predefined_coupons.json").read_bytes()
    rows = parse_coupons(raw_bytes)

    assert parse_coupons(raw_bytes.decode("utf-8")) == rows
    assert parse_coupons(json.loads(raw_bytes)) == rows

    coupon_ids = {r["coupon_id"] for r in rows}
    assert len(coupon_ids) == 62
    assert len(rows) == 368

    oktay_rows = [
        r
        for r in rows
        if r["author"] == "Oktay Ohcak"
        and r["coupon_name"] == "1. ALTILI NORMAL"
        and r["hippodrome"] == "ISTANBUL"
    ]
    assert len(oktay_rows) == 6
    assert [r["leg_no"] for r in oktay_rows] == [1, 2, 3, 4, 5, 6]
    assert oktay_rows[0]["picks"] == "10,3,2,4,5,8,7"
    assert oktay_rows[5]["picks"] == "7"
    assert oktay_rows[0]["author_id"] == 18
    assert oktay_rows[0]["program_id"] == 15507
    assert oktay_rows[0]["foreign"] is False
    assert oktay_rows[0]["race_date"] == "2026-11-15"
    assert oktay_rows[0]["start_time"] == "14:00"
    assert oktay_rows[0]["created_at"] == "2026-11-15T11:27:43+03:00"
    assert oktay_rows[0]["status"] == "ACTIVE"

    yedili_by_id: dict[str, list[dict]] = {}
    for r in rows:
        if r["game_type"] == "YEDILI_GANYAN":
            yedili_by_id.setdefault(r["coupon_id"], []).append(r)
    assert len(yedili_by_id) == 4
    for leg_rows in yedili_by_id.values():
        assert [r["leg_no"] for r in leg_rows] == [1, 2, 3, 4, 5, 6, 7]

    ikili_rows = [r for r in rows if r["game_type"] == "IKILI_BAHIS"]
    assert len(ikili_rows) == 2
    assert [r["leg_no"] for r in ikili_rows] == [1, 2]
    assert ikili_rows[0]["picks"] == "9"
    assert ikili_rows[1]["picks"] == "7,3,6,4,1"

    cifte_rows = [r for r in rows if r["game_type"] == "CIFTE_BAHIS"]
    assert len(cifte_rows) == 2
    assert [r["leg_no"] for r in cifte_rows] == [1, 2]

    assert all(r["race_date"] == "2026-11-15" for r in rows)
    assert any(r["foreign"] is True and r["hippodrome"] == "GREYVILLE" for r in rows)

    serialized = json.dumps(rows, ensure_ascii=False)
    assert "@" not in serialized
    assert "destek12@hipodrom.com" not in serialized
    assert all("em" not in r for r in rows)

    h1 = coupon_hash(oktay_rows)
    assert len(h1) == 16
    assert coupon_hash(list(reversed(oktay_rows))) == h1


def test_parse_comments_fixture():
    raw_bytes = (FIXTURES / "hipodrom_all_comments.json").read_bytes()
    rows = parse_comments(raw_bytes)

    assert parse_comments(raw_bytes.decode("utf-8")) == rows
    assert parse_comments(json.loads(raw_bytes)) == rows
    assert len(rows) == 95

    first = rows[0]
    assert first["comment_id"] == 102241
    assert first["program_id"] == 15507
    assert first["race_no"] == 1
    assert first["author"] == "Hakan Cantınaz"
    assert first["author_id"] == 17
    assert first["picks"] == "2,3,8,5,9,4"
    assert isinstance(first["text_len"], int) and first["text_len"] > 100
    assert len(first["text_hash"]) == 16
    assert set(first.keys()) == {
        "comment_id",
        "program_id",
        "race_no",
        "author",
        "author_id",
        "picks",
        "text_len",
        "text_hash",
    }

    by_id = {r["comment_id"]: r for r in rows}
    assert by_id[102305]["picks"] == ""
    assert by_id[102308]["picks"] == "8,6,4"

    dup_payload = {
        "success": True,
        "data": [
            {
                "i": 1,
                "ri": 15507,
                "rn": 1,
                "au": {"id": 9, "fi": "  Ali ", "la": " Veli  ", "em": "ali@example.com"},
                "co": "<p><strong>(5) A</strong> sonra <strong>(2) B</strong> tekrar <strong>(5) A</strong></p>",
            }
        ],
    }
    dup_rows = parse_comments(dup_payload)
    assert dup_rows[0]["author"] == "Ali Veli"
    assert dup_rows[0]["picks"] == "5,2"

    serialized = json.dumps(rows, ensure_ascii=False)
    assert "YALNIZ AŞIK" not in serialized
    assert "@" not in serialized


def test_parse_programs_fixture_and_invalid_inputs():
    raw_bytes = (FIXTURES / "hipodrom_hippodrome_list.json").read_bytes()
    rows = parse_programs(raw_bytes)

    assert parse_programs(raw_bytes.decode("utf-8")) == rows
    assert parse_programs(json.loads(raw_bytes)) == rows
    assert len(rows) == 4
    assert rows[0] == {
        "program_id": 15507,
        "hippodrome": "ISTANBUL",
        "name": "İstanbul Veliefendi Hipodromu",
        "foreign": False,
    }
    assert rows[1] == {
        "program_id": 15521,
        "hippodrome": "GREYVILLE",
        "name": "Greyville",
        "foreign": True,
    }

    for bad in (b"not-json", b"\xff\xfe", "{}", {"success": False, "data": []}, {"success": True}, None):
        assert parse_coupons(bad) == []
        assert parse_comments(bad) == []
        assert parse_programs(bad) == []


def test_run_end_to_end_idempotent_and_diff(tmp_path, capsys):
    coupons_bytes = (FIXTURES / "hipodrom_predefined_coupons.json").read_bytes()
    comments_bytes = (FIXTURES / "hipodrom_all_comments.json").read_bytes()
    programs_bytes = (FIXTURES / "hipodrom_hippodrome_list.json").read_bytes()

    payloads = {
        COUPONS_URL: coupons_bytes,
        COMMENTS_URL: comments_bytes,
        PROGRAMS_URL: programs_bytes,
    }
    sleeps: list[float] = []

    def fake_get(url: str):
        return 200, payloads[url]

    # 1) First run: writes 3 CSVs + 3 raw gz + state
    res1 = run(tmp_path, now="2026-11-15T12:00:00+03:00", get_fn=fake_get, sleep_fn=sleeps.append)
    out1 = capsys.readouterr().out
    assert res1 == {"coupons": 62, "comments": 95, "programs": 4, "changed": True}
    assert sleeps == [1.0, 1.0]
    assert "kupon: 62 yeni, yorum: 95 yeni, program: 4 yeni" in out1

    coupons_csv = tmp_path / "hipodrom_coupons.csv"
    comments_csv = tmp_path / "hipodrom_comments.csv"
    programs_csv = tmp_path / "hipodrom_programs.csv"
    state_file = tmp_path / "hipodrom_state.json"

    assert coupons_csv.exists()
    assert comments_csv.exists()
    assert programs_csv.exists()
    assert state_file.exists()

    raw_dir = tmp_path / "raw_hipodrom" / "2026-11-15"
    coupons_gz = gzip.decompress((raw_dir / "120000_coupons.json.gz").read_bytes())
    assert b'"em"' not in coupons_gz and b"@" not in coupons_gz
    assert parse_coupons(coupons_gz) == parse_coupons(coupons_bytes)
    assert gzip.decompress((raw_dir / "120000_comments.json.gz").read_bytes()) == comments_bytes
    assert gzip.decompress((raw_dir / "120000_programs.json.gz").read_bytes()) == programs_bytes

    with open(coupons_csv, encoding="utf-8", newline="") as f:
        r_coupons = list(csv.DictReader(f))
        assert f.seek(0) == 0
        coupons_text = f.read()
    assert len(r_coupons) == 368
    assert list(r_coupons[0].keys()) == COUPON_FIELDS
    assert "@" not in coupons_text

    with open(comments_csv, encoding="utf-8", newline="") as f:
        r_comments = list(csv.DictReader(f))
        f.seek(0)
        comments_text = f.read()
    assert len(r_comments) == 95
    assert list(r_comments[0].keys()) == COMMENT_FIELDS
    assert "YALNIZ AŞIK" not in comments_text
    assert "@" not in comments_text

    with open(programs_csv, encoding="utf-8", newline="") as f:
        r_programs = list(csv.DictReader(f))
    assert len(r_programs) == 4
    assert list(r_programs[0].keys()) == PROGRAM_FIELDS

    state1_text = state_file.read_text(encoding="utf-8")
    assert "@" not in state1_text
    state1 = json.loads(state1_text)
    assert len(state1["coupons"]) == 62
    assert len(state1["comments"]) == 95
    assert state1["programs"] == [15507, 15521, 15508, 15530]
    old_hash = state1["coupons"]["0501396d-3f6a-425c-a801-51e693ea18f1"]

    # 2) Second run: nothing changed -> no files written, logs "değişmedi"
    res2 = run(tmp_path, now="2026-11-15T12:05:00+03:00", get_fn=fake_get, sleep_fn=lambda _: None)
    out2 = capsys.readouterr().out.strip()
    assert res2 == {"coupons": 0, "comments": 0, "programs": 0, "changed": False}
    assert out2 == "değişmedi"
    assert sorted(p.name for p in raw_dir.iterdir()) == [
        "120000_comments.json.gz",
        "120000_coupons.json.gz",
        "120000_programs.json.gz",
    ]
    assert coupons_csv.read_text(encoding="utf-8") == coupons_text
    assert comments_csv.read_text(encoding="utf-8") == comments_text
    assert state_file.read_text(encoding="utf-8") == state1_text

    # 3) Third run: modify one coupon's rns -> only its legs appended with new coupon_hash
    coupons_doc = json.loads(coupons_bytes.decode("utf-8"))
    target_coupon = coupons_doc["data"][0]
    assert target_coupon["id"] == "0501396d-3f6a-425c-a801-51e693ea18f1"
    target_coupon["lgr"][5]["rns"] = [7, 1]
    payloads[COUPONS_URL] = json.dumps(coupons_doc, ensure_ascii=False).encode("utf-8")

    res3 = run(tmp_path, now="2026-11-15T12:10:00+03:00", get_fn=fake_get, sleep_fn=lambda _: None)
    out3 = capsys.readouterr().out
    assert res3 == {"coupons": 1, "comments": 0, "programs": 0, "changed": True}
    assert "kupon: 1 yeni, yorum: 0 yeni, program: 0 yeni" in out3

    with open(coupons_csv, encoding="utf-8", newline="") as f:
        r_coupons_after = list(csv.DictReader(f))
    assert len(r_coupons_after) == 368 + 6
    appended = r_coupons_after[368:]
    assert all(r["coupon_id"] == "0501396d-3f6a-425c-a801-51e693ea18f1" for r in appended)
    assert all(r["captured_at"] == "2026-11-15T12:10:00+03:00" for r in appended)
    assert [int(r["leg_no"]) for r in appended] == [1, 2, 3, 4, 5, 6]
    assert appended[5]["picks"] == "7,1"
    new_hash = appended[0]["coupon_hash"]
    assert len(new_hash) == 16 and new_hash != old_hash
    assert all(r["coupon_hash"] == new_hash for r in appended)

    with open(comments_csv, encoding="utf-8", newline="") as f:
        assert len(list(csv.DictReader(f))) == 95
    with open(programs_csv, encoding="utf-8", newline="") as f:
        assert len(list(csv.DictReader(f))) == 4

    assert (raw_dir / "121000_coupons.json.gz").exists()
    assert not (raw_dir / "121000_comments.json.gz").exists()
    assert not (raw_dir / "121000_programs.json.gz").exists()


def test_run_partial_failure_and_corrupt_json(tmp_path, capsys, monkeypatch):
    coupons_bytes = (FIXTURES / "hipodrom_predefined_coupons.json").read_bytes()
    comments_bytes = (FIXTURES / "hipodrom_all_comments.json").read_bytes()
    programs_bytes = (FIXTURES / "hipodrom_hippodrome_list.json").read_bytes()

    def failing_comments_get(url: str):
        if url == COMMENTS_URL:
            return 500, b"Internal Server Error"
        if url == COUPONS_URL:
            return 200, coupons_bytes
        return 200, programs_bytes

    res1 = run(tmp_path, now="2026-11-15T13:00:00+03:00", get_fn=failing_comments_get, sleep_fn=lambda _: None)
    out1 = capsys.readouterr().out
    assert "UYARI:" in out1
    assert res1 == {"coupons": 62, "comments": 0, "programs": 4, "changed": True}
    assert (tmp_path / "hipodrom_coupons.csv").exists()
    assert not (tmp_path / "hipodrom_comments.csv").exists()
    assert (tmp_path / "hipodrom_programs.csv").exists()

    state1 = json.loads((tmp_path / "hipodrom_state.json").read_text(encoding="utf-8"))
    assert "comments" not in state1["raw"]
    assert state1["comments"] == {}

    def corrupt_coupons_get(url: str):
        if url == COUPONS_URL:
            return 200, b"{corrupt-json"
        if url == COMMENTS_URL:
            return 200, comments_bytes
        return 200, programs_bytes

    res2 = run(tmp_path, now="2026-11-15T13:05:00+03:00", get_fn=corrupt_coupons_get, sleep_fn=lambda _: None)
    out2 = capsys.readouterr().out
    assert "UYARI:" in out2
    assert res2 == {"coupons": 0, "comments": 95, "programs": 0, "changed": True}
    assert (tmp_path / "hipodrom_comments.csv").exists()

    state2 = json.loads((tmp_path / "hipodrom_state.json").read_text(encoding="utf-8"))
    assert len(state2["coupons"]) == 62
    assert len(state2["comments"]) == 95

    # CLI exit code is always 0 even when network raises
    def raising_get(url: str):
        raise OSError("network down")

    out_empty = tmp_path / "empty_run"
    run(out_empty, now="2026-11-15T13:10:00+03:00", get_fn=raising_get, sleep_fn=lambda _: None)
    assert not out_empty.exists()

    import scripts.hipodrom_collect as hc

    monkeypatch.setattr(hc, "tjk_get", raising_get)
    monkeypatch.setattr(hc.time, "sleep", lambda _: None)
    assert main(["--out-dir", str(out_empty)]) == 0
    assert not out_empty.exists()

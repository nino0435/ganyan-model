"""Unit and end-to-end tests for Milliyet daily tip image collector."""
import csv
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.milliyet_tips import AUTHOR_URL, image_ext, parse_article, parse_listing
from scripts.milliyet_collect import CSV_COLUMNS, run

FIXTURES = Path(__file__).resolve().parent / "fixtures"
IST_TZ = ZoneInfo("Europe/Istanbul")


def test_parse_listing_fixture():
    html = (FIXTURES / "milliyet_yazar_liste.html").read_text(encoding="utf-8")
    items = parse_listing(html)
    assert len(items) == 7
    assert items[0]["article_id"] == 7700875
    assert items[0]["url"].endswith("/altili-ganyanda-bugun-15-kasim-7700875")
    ids = [it["article_id"] for it in items]
    assert ids == sorted(set(ids), reverse=True)
    for it in items:
        assert it["url"].startswith("https://www.milliyet.com.tr/")
        assert "altili-ganyanda-bugun-" in it["url"]


def test_parse_listing_dedup_and_order():
    html = (
        '<a href="/skorer/afsin-yakuboglu/altili-ganyanda-bugun-1-kasim-100">a</a>'
        '<a href="https://www.milliyet.com.tr/skorer/afsin-yakuboglu/altili-ganyanda-bugun-2-kasim-250">b</a>'
        '<a href="/skorer/afsin-yakuboglu/altili-ganyanda-bugun-2-kasim-250#yorum">b2</a>'
        '<a href="/skorer/afsin-yakuboglu/baska-yazi-999">c</a>'
    )
    items = parse_listing(html)
    assert [it["article_id"] for it in items] == [250, 100]
    assert items[0]["url"] == (
        "https://www.milliyet.com.tr/skorer/afsin-yakuboglu/altili-ganyanda-bugun-2-kasim-250"
    )


def test_parse_article_fixture():
    html = (FIXTURES / "milliyet_altili_makale.html").read_text(encoding="utf-8")
    info = parse_article(html)
    assert info["title"] and "15" in info["title"]
    assert info["published"] == "2026-11-15T07:01:08+03:00"
    assert info["image_url"] is not None
    assert info["image_url"].endswith("/6af8d339545758672f57754c.jpg")


def test_parse_article_fallbacks_and_empty():
    assert parse_article("") == {"title": None, "published": None, "image_url": None}
    assert parse_article("<html><body><p>yok</p></body></html>") == {
        "title": None,
        "published": None,
        "image_url": None,
    }
    src_only = '<img data-inline-image="true" src="https://image.milimaj.com/a/b.jpg">'
    assert parse_article(src_only)["image_url"] == "https://image.milimaj.com/a/b.jpg"


def test_image_ext():
    assert image_ext(b"\x89PNG" + b"x" * 2000) == "png"
    assert image_ext(b"\xff\xd8\xff\xe0" + b"y" * 2000) == "jpg"
    assert image_ext(b"GIF89a" + b"z" * 100) is None
    assert image_ext(b"") is None


def test_run_end_to_end_idempotent_and_image_update(tmp_path):
    listing_bytes = (FIXTURES / "milliyet_yazar_liste.html").read_bytes()
    article_bytes = (FIXTURES / "milliyet_altili_makale.html").read_bytes()
    article_info = parse_article(article_bytes.decode("utf-8"))
    first_url = parse_listing(listing_bytes.decode("utf-8"))[0]["url"]
    img_url = article_info["image_url"]

    png_v1 = b"\x89PNG" + b"x" * 2000
    calls: list[str] = []

    def fake_get_v1(url: str):
        calls.append(url)
        if url == AUTHOR_URL:
            return 200, listing_bytes
        if url == first_url:
            return 200, article_bytes
        if url == img_url:
            return 200, png_v1
        return 404, b""

    t1 = datetime.datetime(2026, 11, 15, 7, 30, 0, tzinfo=IST_TZ)
    res1 = run(tmp_path, max_articles=1, now=t1, get_fn=fake_get_v1)
    assert res1 == {"new": 1, "skipped": 0}

    png_path = tmp_path / "milliyet" / "2026-11-15.png"
    raw_path = tmp_path / "raw_milliyet" / "2026-11-15.html.gz"
    csv_path = tmp_path / "milliyet.csv"
    state_path = tmp_path / "milliyet_state.json"

    assert png_path.read_bytes() == png_v1
    assert gzip.decompress(raw_path.read_bytes()) == article_bytes

    with open(csv_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
        f.seek(0)
        header = next(csv.reader(f))
    assert header == CSV_COLUMNS
    assert len(rows) == 1
    expected_sha1 = hashlib.sha256(png_v1).hexdigest()
    assert rows[0]["captured_at"] == "2026-11-15T07:30:00+03:00"
    assert rows[0]["published"] == "2026-11-15T07:01:08+03:00"
    assert rows[0]["url"] == first_url
    assert rows[0]["image_url"] == img_url
    assert rows[0]["image_file"] == "milliyet/2026-11-15.png"
    assert rows[0]["sha256"] == expected_sha1
    assert rows[0]["bytes"] == str(len(png_v1))
    assert json.loads(state_path.read_text(encoding="utf-8")) == {first_url: expected_sha1}

    # Second run: nothing new added, article/image not re-fetched
    calls.clear()
    t2 = datetime.datetime(2026, 11, 15, 8, 0, 0, tzinfo=IST_TZ)
    res2 = run(tmp_path, max_articles=1, now=t2, get_fn=fake_get_v1)
    assert res2 == {"new": 0, "skipped": 1}
    assert calls == [AUTHOR_URL]
    with open(csv_path, encoding="utf-8", newline="") as f:
        assert len(list(csv.DictReader(f))) == 1
    assert sorted(p.name for p in (tmp_path / "milliyet").iterdir()) == ["2026-11-15.png"]

    # Updated image on same date (e.g. corrected article URL on same day): writes timestamped file
    updated_url = "https://www.milliyet.com.tr/skorer/afsin-yakuboglu/altili-ganyanda-bugun-15-kasim-7700999"
    updated_listing = f'<a href="{updated_url}">yeni</a>'.encode("utf-8")
    png_v2 = b"\x89PNG" + b"y" * 2000

    def fake_get_v2(url: str):
        if url == AUTHOR_URL:
            return 200, updated_listing
        if url == updated_url:
            return 200, article_bytes
        if url == img_url:
            return 200, png_v2
        return 404, b""

    t3 = datetime.datetime(2026, 11, 15, 9, 15, 42, tzinfo=IST_TZ)
    res3 = run(tmp_path, max_articles=1, now=t3, get_fn=fake_get_v2)
    assert res3 == {"new": 1, "skipped": 0}
    assert png_path.read_bytes() == png_v1
    ts_png = tmp_path / "milliyet" / "2026-11-15_091542.png"
    assert ts_png.read_bytes() == png_v2
    with open(csv_path, encoding="utf-8", newline="") as f:
        rows_after = list(csv.DictReader(f))
    assert len(rows_after) == 2
    assert rows_after[1]["image_file"] == "milliyet/2026-11-15_091542.png"


def test_run_imageless_article_not_saved_to_state(tmp_path):
    art_url = "https://www.milliyet.com.tr/skorer/afsin-yakuboglu/altili-ganyanda-bugun-15-kasim-7700875"
    listing_bytes = f'<a href="{art_url}">makale</a>'.encode("utf-8")
    no_img_html = b"<html><head><title>Bekliyor</title></head><body><p>.</p></body></html>"

    def fake_get(url: str):
        if url == AUTHOR_URL:
            return 200, listing_bytes
        if url == art_url:
            return 200, no_img_html
        return 404, b""

    res = run(tmp_path, max_articles=1, now="2026-11-15T07:00:00+03:00", get_fn=fake_get)
    assert res == {"new": 0, "skipped": 1}
    state_path = tmp_path / "milliyet_state.json"
    assert not state_path.exists() or art_url not in json.loads(
        state_path.read_text(encoding="utf-8")
    )
    assert not (tmp_path / "milliyet.csv").exists()


def test_run_network_error_does_not_crash(tmp_path):
    res = run(
        tmp_path,
        max_articles=3,
        now=datetime.datetime(2026, 11, 15, 7, 0, 0, tzinfo=IST_TZ),
        get_fn=lambda _url: (None, b""),
    )
    assert res == {"new": 0, "skipped": 0}
    assert not (tmp_path / "milliyet_state.json").exists()


def test_run_same_file_not_rewritten_and_invalid_image_skipped(tmp_path):
    art_ok = "https://www.milliyet.com.tr/skorer/afsin-yakuboglu/altili-ganyanda-bugun-15-kasim-7700875"
    art_bad = "https://www.milliyet.com.tr/skorer/afsin-yakuboglu/altili-ganyanda-bugun-14-kasim-7700449"
    img_ok = "https://image.milimaj.com/i/milliyet/75/770x0/ok.jpg"
    img_short = "https://image.milimaj.com/i/milliyet/75/770x0/short.jpg"
    listing = f'<a href="{art_ok}">1</a><a href="{art_bad}">2</a>'.encode("utf-8")
    html_ok = f'<img data-inline-image="true" data-src="{img_ok}">'.encode("utf-8")
    html_bad = f'<img data-inline-image="true" data-src="{img_short}">'.encode("utf-8")
    png_bytes = b"\x89PNG" + b"z" * 2000

    # Pre-create target PNG with identical bytes and an older mtime
    pre_png = tmp_path / "milliyet" / "2026-11-15.png"
    pre_png.parent.mkdir(parents=True, exist_ok=True)
    pre_png.write_bytes(png_bytes)
    os.utime(pre_png, (1_700_000_000, 1_700_000_000))

    def fake_get(url: str):
        if url == AUTHOR_URL:
            return 200, listing
        if url == art_ok:
            return 200, html_ok
        if url == art_bad:
            return 200, html_bad
        if url == img_ok:
            return 200, png_bytes
        if url == img_short:
            return 200, b"\x89PNGshort"
        return 404, b""

    t = datetime.datetime(2026, 11, 15, 10, 0, 0, tzinfo=IST_TZ)
    res = run(tmp_path, max_articles=2, now=t, get_fn=fake_get)
    assert res == {"new": 1, "skipped": 1}
    # Identical file was not rewritten
    assert int(pre_png.stat().st_mtime) == 1_700_000_000
    # Short image article was not written to state
    state = json.loads((tmp_path / "milliyet_state.json").read_text(encoding="utf-8"))
    assert list(state.keys()) == [art_ok]


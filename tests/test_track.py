"""Tests for ganyan.tracks, ganyan.db weather_hourly, and ganyan.track (§2.3, §3.1)."""
import os
import sqlite3
import pytest
from ganyan.db import init_db
from ganyan.tracks import TRACK_COORDS
from scripts.fetch_weather import upsert_weather_json


def test_parse_conditions_html_and_normalize():
    track = pytest.importorskip("ganyan.track")
    sample_html = """
    <span class="raceWeatherGreen"> &#199;im: Yumuşak 3,7 </span>
    <span class="raceWeatherBrown"> Kum: Normal </span>
    Hava: 17 C , AZ BULUTLU , NEM %66
    """
    conds = track.parse_conditions_html(sample_html)
    assert conds == {"Çim": "Çim: Yumuşak 3,7", "Kum": "Kum: Normal"}
    assert track.normalize_track_cond("Çim", conds["Çim"]) == "yumusak"
    assert track.normalize_track_cond("Kum", conds["Kum"]) == "normal"
    assert track.normalize_track_cond("Sentetik", None) == "bilinmiyor"

    with pytest.raises(KeyError):
        track.normalize_track_cond("Çim", "Çim: Buzlu 9,9")


def test_db_cities_and_track_cond_raw_covered():
    if not os.path.exists("data/ganyan.db"):
        pytest.skip("data/ganyan.db not present")
    conn = sqlite3.connect("data/ganyan.db", timeout=30)
    cities = [r[0] for r in conn.execute("SELECT DISTINCT city FROM races").fetchall()]
    for c in cities:
        assert c in TRACK_COORDS, f"City {c!r} missing from TRACK_COORDS"
        lat, lon = TRACK_COORDS[c]
        assert 35.0 <= lat <= 42.5
        assert 26.0 <= lon <= 45.0

    # Every non-null track_cond_raw in DB must be mapped in TRACK_COND_MAP
    cols = {r[1] for r in conn.execute("PRAGMA table_info(races)").fetchall()}
    if "track_cond_raw" in cols:
        track = pytest.importorskip("ganyan.track")
        raw_pairs = conn.execute(
            "SELECT DISTINCT surface, track_cond_raw FROM races WHERE track_cond_raw IS NOT NULL AND track_cond_raw != ''"
        ).fetchall()
        for surf, raw in raw_pairs:
            key = track.extract_cond_key(surf, raw)
            assert key in track.TRACK_COND_MAP, f"Unmapped DB track_cond_raw: surface={surf!r}, raw={raw!r}, key={key!r}"
            norm = track.normalize_track_cond(surf, raw)
            assert norm in track.VALID_TRACK_CONDS
    conn.close()


def test_weather_hourly_upsert(tmp_path):
    conn = init_db(tmp_path / "w.db")
    payload = {
        "hourly": {
            "time": ["2026-10-24T12:00", "2026-10-24T13:00"],
            "precipitation": [0.0, 2.4],
            "temperature_2m": [17.5, 16.8],
            "relative_humidity_2m": [62.0, 75.0],
            "wind_speed_10m": [12.0, 18.5],
        }
    }
    n = upsert_weather_json(conn, "Ankara", payload)
    assert n == 2
    row = conn.execute(
        "SELECT precip_mm, temp_c, rh, wind_kmh, src FROM weather_hourly WHERE city='Ankara' AND ts='2026-10-24T13:00'"
    ).fetchone()
    assert row == pytest.approx((2.4, 16.8, 75.0, 18.5, "archive"))
    conn.close()

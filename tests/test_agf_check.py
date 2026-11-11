"""AGF bütünlük kuralı ve raporun geçersiz koşuları dışlaması."""
import math

from ganyan.agf_check import agf_complete
from ganyan.db import init_db
from scripts.forward_report import build_forward_report

D = "2026-11-10"


def test_agf_complete_accepts_full_distribution():
    assert agf_complete([50.0, 30.0, 20.0])


def test_agf_complete_rejects_zero_null_nan_and_bad_sum():
    assert not agf_complete([50.0, 50.0, 0.0])  # %0 placeholder
    assert not agf_complete([50.0, 50.0, None])
    assert not agf_complete([50.0, 50.0, math.nan])
    assert not agf_complete([20.0, 20.0, 20.0])  # toplam ~%60
    assert not agf_complete([])


def test_agf_complete_scratched_horse_only_counts_in_sum():
    # çekilen at (all_values'ta) toplamı tamamlar; koşan atlar eksiksiz olduğu sürece geçerli
    assert agf_complete([46.0, 46.0], [46.0, 46.0, 8.0])
    assert not agf_complete([46.0, 0.0], [46.0, 0.0, 54.0])


def _seed(tmp_path, agf_by_race):
    conn = init_db(tmp_path / "t.db")
    for i, agfs in enumerate(agf_by_race, start=1):
        rid = f"{D}_Bursa_{i}"
        conn.execute(
            "INSERT INTO races (race_id, date, city, race_no, post_time, status) VALUES (?,?,?,?,?,?)",
            (rid, D, "Bursa", i, "14:00", "result"),
        )
        for no, a in enumerate(agfs, start=1):
            conn.execute(
                "INSERT INTO runners (race_id, prog_no, horse_key, name, finish, scratched, agf_close) VALUES (?,?,?,?,?,?,?)",
                (rid, no, f"h{i}{no}", f"H{no}", no, 0, 33.3),
            )
            conn.execute(
                "INSERT INTO predictions (race_id, prog_no, model_version, created_at, p_win, agf_used) VALUES (?,?,?,?,?,?)",
                (rid, no, "v1_agf", f"{D}T09:00:00", 1 / len(agfs), a),
            )
    conn.commit()
    return conn


def test_report_excludes_races_with_zero_agf(tmp_path):
    conn = _seed(tmp_path, [[50.0, 30.0, 20.0], [50.0, 50.0, 0.0]])
    md = build_forward_report(conn)
    assert "`2` koşu (`6` at)" in md  # ikisi de kayıtlı
    assert "Geçerli Tahmin (`created_at < post_time`):** `1` koşu" in md
    assert "dışlanan koşu:** `1`" in md
    assert "Sonuçlanmış Geçerli Koşu:** `1`" in md

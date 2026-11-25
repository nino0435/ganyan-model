"""Unit, hand-calculation, edge-case, and strict temporal leakage tests for ganyan/features_v11.py."""
import os
import sqlite3
import sys

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import ganyan.features_v11 as fv11
from ganyan.features_v11 import (
    GOING_COLS,
    GPREF_COLS,
    GPREF_FPCT_PRIOR_K,
    GPREF_SF_PRIOR_K,
    GPREF_WR_PRIOR_N,
    GPREF_WR_PRIOR_W,
    SMOOTHING_CONSTANTS,
    V11_BLOCK_COLS,
    V11_CANDIDATE_BLOCKS,
    WX_COLS,
    attach_GOING,
    attach_GPREF,
    attach_WX,
    attach_v11,
    get_v11_cols,
    load_v11_tables,
)
from ganyan.model_v10 import V10_CONFIG


def test_v11_column_definitions_and_no_overlap():
    assert len(GOING_COLS) == 5
    assert len(WX_COLS) == 4
    assert len(GPREF_COLS) == 7
    assert V11_CANDIDATE_BLOCKS == ("GOING", "WX", "GPREF")
    assert set(V11_BLOCK_COLS) == {"GOING", "WX", "GPREF"}

    base_v10 = list(V10_CONFIG["feature_cols"])
    assert len(base_v10) == 155
    assert get_v11_cols(()) == base_v10

    v11_only = [c for blk in V11_CANDIDATE_BLOCKS for c in V11_BLOCK_COLS[blk]]
    assert len(v11_only) == 16
    assert len(v11_only) <= 20
    assert len(set(v11_only)) == 16
    assert set(base_v10).isdisjoint(v11_only)

    all_cols = get_v11_cols(V11_CANDIDATE_BLOCKS)
    assert len(all_cols) == 155 + 16
    assert len(set(all_cols)) == 171

    prog_cols = get_v11_cols(("GOING",), with_program=True)
    assert len(prog_cols) == 155 + len(GOING_COLS) + 6


def test_going_exact_mapping_and_turf_num():
    df = pd.DataFrame(
        [
            {"race_id": "2026-01-01_A_1", "date": "2026-01-01", "city": "İstanbul", "race_no": 1, "horse_key": "H1", "surface": "Çim", "track_cond": "kuru", "track_cond_raw": "Çim: Kuru 3,0", "scratched": 0},
            {"race_id": "2026-01-01_A_2", "date": "2026-01-01", "city": "İstanbul", "race_no": 2, "horse_key": "H2", "surface": "Çim", "track_cond": "normal", "track_cond_raw": "Çim: Normal 0", "scratched": 0},
            {"race_id": "2026-01-01_A_3", "date": "2026-01-01", "city": "İstanbul", "race_no": 3, "horse_key": "H3", "surface": "Kum", "track_cond": "nemli", "track_cond_raw": "Kum: Nemli", "scratched": 0},
            {"race_id": "2026-01-01_A_4", "date": "2026-01-01", "city": "İstanbul", "race_no": 4, "horse_key": "H4", "surface": "Kum", "track_cond": "islak", "track_cond_raw": "Kum: Islak", "scratched": 0},
            {"race_id": "2026-01-01_A_5", "date": "2026-01-01", "city": "İstanbul", "race_no": 5, "horse_key": "H5", "surface": "Çim", "track_cond": "yumusak", "track_cond_raw": "Çim: Çok Yumuşak 4,2", "scratched": 0},
            {"race_id": "2026-01-01_A_6", "date": "2026-01-01", "city": "İstanbul", "race_no": 6, "horse_key": "H6", "surface": "Çim", "track_cond": "agir", "track_cond_raw": "Çim: Ağır 4,9", "scratched": 0},
            {"race_id": "2026-01-01_A_7", "date": "2026-01-01", "city": "İstanbul", "race_no": 7, "horse_key": "H7", "surface": "Sentetik", "track_cond": "bilinmiyor", "track_cond_raw": None, "scratched": 0},
            # Missing track_cond in df, filled from day_cond fallback
            {"race_id": "2026-01-02_B_1", "date": "2026-01-02", "city": "Ankara", "race_no": 1, "horse_key": "H8", "surface": "Çim", "track_cond": None, "track_cond_raw": None, "scratched": 0},
        ]
    )
    dc = pd.DataFrame(
        [
            {"date": "2026-01-02", "city": "Ankara", "cim_raw": "Çim: Yumuşak 3,7", "kum_raw": "Kum: Normal", "sentetik_raw": None, "temp_c": 20.0, "rh": 40.0, "sky": "acik", "windy": 0}
        ]
    )
    out = attach_GOING(df, v5_tables={"day_cond": dc}).set_index("horse_key")

    assert out.loc["H1", "going_ord"] == pytest.approx(0.0)
    assert out.loc["H1", "going_wet"] == pytest.approx(0.0)
    assert out.loc["H1", "going_turf_num"] == pytest.approx(3.0)
    assert out.loc["H1", "going_turf_ord"] == pytest.approx(0.0)
    assert np.isnan(out.loc["H1", "going_dirt_ord"])

    # Bogus '0' penetrometer reading filtered to NaN
    assert out.loc["H2", "going_ord"] == pytest.approx(1.0)
    assert np.isnan(out.loc["H2", "going_turf_num"])

    assert out.loc["H3", "going_ord"] == pytest.approx(2.0)
    assert out.loc["H3", "going_wet"] == pytest.approx(1.0)
    assert np.isnan(out.loc["H3", "going_turf_ord"])
    assert out.loc["H3", "going_dirt_ord"] == pytest.approx(2.0)

    assert out.loc["H4", "going_ord"] == pytest.approx(3.0)
    assert out.loc["H5", "going_ord"] == pytest.approx(4.0)
    assert out.loc["H5", "going_turf_num"] == pytest.approx(4.2)
    assert out.loc["H6", "going_ord"] == pytest.approx(5.0)
    assert out.loc["H6", "going_turf_num"] == pytest.approx(4.9)

    for c in GOING_COLS:
        assert np.isnan(out.loc["H7", c])

    # Fallback from day_cond
    assert out.loc["H8", "going_ord"] == pytest.approx(4.0)
    assert out.loc["H8", "going_wet"] == pytest.approx(1.0)
    assert out.loc["H8", "going_turf_num"] == pytest.approx(3.7)


def test_wx_uses_only_day_cond_and_ignores_weather_hourly(tmp_path):
    assert not hasattr(fv11, "WX_HOURLY_RAIN_3H_MM")
    assert not hasattr(fv11, "WX_HOURLY_WIND_KMH")
    assert "WX_HOURLY_RAIN_3H_MM" not in SMOOTHING_CONSTANTS
    assert "WX_HOURLY_WIND_KMH" not in SMOOTHING_CONSTANTS

    df = pd.DataFrame(
        [
            {"race_id": "2026-03-01_Ankara_1", "date": "2026-03-01", "city": "Ankara", "race_no": 1, "post_time": "14:30", "horse_key": "H1", "scratched": 0},
            {"race_id": "2026-03-02_Ankara_1", "date": "2026-03-02", "city": "Ankara", "race_no": 1, "post_time": "14:30", "horse_key": "H2", "scratched": 0},
        ]
    )
    dc = pd.DataFrame(
        [
            {"date": "2026-03-01", "city": "Ankara", "cim_raw": None, "kum_raw": "Kum: Normal", "sentetik_raw": None, "temp_c": 22.0, "rh": 35.0, "sky": "yagisli", "windy": 1},
        ]
    )
    wh = pd.DataFrame(
        [
            {"city": "Ankara", "ts": "2026-03-01T13:00", "precip_mm": 0.0, "temp_c": 5.0, "rh": 90.0, "wind_kmh": 0.0},
            {"city": "Ankara", "ts": "2026-03-02T11:00", "precip_mm": 0.0, "temp_c": 16.0, "rh": 50.0, "wind_kmh": 8.0},
            {"city": "Ankara", "ts": "2026-03-02T12:00", "precip_mm": 0.0, "temp_c": 17.0, "rh": 48.0, "wind_kmh": 9.0},
            {"city": "Ankara", "ts": "2026-03-02T13:00", "precip_mm": 0.0, "temp_c": 18.0, "rh": 44.0, "wind_kmh": 10.0},
        ]
    )
    out = attach_WX(df, v5_tables={"day_cond": dc, "weather_hourly": wh}).set_index("horse_key")

    assert out.loc["H1", "wx_temp_c"] == pytest.approx(22.0)
    assert out.loc["H1", "wx_rh"] == pytest.approx(35.0)
    assert out.loc["H1", "wx_rainy"] == pytest.approx(1.0)
    assert out.loc["H1", "wx_windy"] == pytest.approx(1.0)

    for col in WX_COLS:
        assert np.isnan(out.loc["H2", col])

    db_path = tmp_path / "tables_check.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE day_cond (
            date TEXT, city TEXT, cim_raw TEXT, kum_raw TEXT, sentetik_raw TEXT,
            hava_raw TEXT, temp_c REAL, rh REAL, sky TEXT, windy INTEGER
        )
        """
    )
    conn.execute(
        "CREATE TABLE weather_hourly (city TEXT, ts TEXT, precip_mm REAL, temp_c REAL, rh REAL, wind_kmh REAL)"
    )
    conn.execute(
        "INSERT INTO day_cond VALUES ('2026-03-01','Ankara',NULL,'Kum: Normal',NULL,'22 C',22.0,35.0,'yagisli',1)"
    )
    conn.execute("INSERT INTO weather_hourly VALUES ('Ankara','2026-03-02T13:00',0.0,18.0,44.0,10.0)")
    conn.commit()
    conn.close()

    loaded = load_v11_tables(db_path)
    assert "weather_hourly" not in loaded
    assert "day_cond" in loaded
    assert len(loaded["day_cond"]) == 1


def test_gpref_exact_math_unknown_exclusion_and_maiden():
    rows = [
        # H1: 2 wet wins (fpct=0.0, sf=40), 1 dry 4th (fpct=0.8, sf=20), plus 1 UNKNOWN race (must NOT enter dry or wet!)
        {"race_id": "2026-01-01_A_1", "date": "2026-01-01", "city": "A", "race_no": 1, "horse_key": "H1", "surface": "Çim", "track_cond": "yumusak", "finish": 1, "fpct": 0.0, "sf": 40.0, "scratched": 0},
        {"race_id": "2026-01-10_A_1", "date": "2026-01-10", "city": "A", "race_no": 1, "horse_key": "H1", "surface": "Çim", "track_cond": "agir", "finish": 1, "fpct": 0.0, "sf": 40.0, "scratched": 0},
        {"race_id": "2026-01-20_A_1", "date": "2026-01-20", "city": "A", "race_no": 1, "horse_key": "H1", "surface": "Kum", "track_cond": "normal", "finish": 4, "fpct": 0.8, "sf": 20.0, "scratched": 0},
        {"race_id": "2026-01-25_A_1", "date": "2026-01-25", "city": "A", "race_no": 1, "horse_key": "H1", "surface": "Sentetik", "track_cond": "bilinmiyor", "finish": 5, "fpct": 1.0, "sf": 5.0, "scratched": 0},
        # H2: 1 wet loss (fpct=1.0, sf=10), 1 dry win (fpct=0.0, sf=30)
        {"race_id": "2026-01-05_A_1", "date": "2026-01-05", "city": "A", "race_no": 1, "horse_key": "H2", "surface": "Çim", "track_cond": "islak", "finish": 4, "fpct": 1.0, "sf": 10.0, "scratched": 0},
        {"race_id": "2026-01-15_A_1", "date": "2026-01-15", "city": "A", "race_no": 1, "horse_key": "H2", "surface": "Kum", "track_cond": "kuru", "finish": 1, "fpct": 0.0, "sf": 30.0, "scratched": 0},
        # Target wet race on 2026-02-01 with H1, H2, H_MAIDEN, H_SCR (scratched)
        {"race_id": "2026-02-01_A_1", "date": "2026-02-01", "city": "A", "race_no": 1, "horse_key": "H1", "surface": "Çim", "track_cond": "yumusak", "finish": np.nan, "fpct": np.nan, "sf": np.nan, "scratched": 0},
        {"race_id": "2026-02-01_A_1", "date": "2026-02-01", "city": "A", "race_no": 1, "horse_key": "H2", "surface": "Çim", "track_cond": "yumusak", "finish": np.nan, "fpct": np.nan, "sf": np.nan, "scratched": 0},
        {"race_id": "2026-02-01_A_1", "date": "2026-02-01", "city": "A", "race_no": 1, "horse_key": "H_MAIDEN", "surface": "Çim", "track_cond": "yumusak", "finish": np.nan, "fpct": np.nan, "sf": np.nan, "scratched": 0},
        {"race_id": "2026-02-01_A_1", "date": "2026-02-01", "city": "A", "race_no": 1, "horse_key": "H_SCR", "surface": "Çim", "track_cond": "yumusak", "finish": np.nan, "fpct": np.nan, "sf": np.nan, "scratched": 1},
    ]
    out = attach_GPREF(pd.DataFrame(rows))
    tgt = out[out["race_id"] == "2026-02-01_A_1"].set_index("horse_key")

    neff1 = (2.0 * 1.0) / (2.0 + 1.0)
    exp_fp1 = (0.8 - 0.0) * (neff1 / (neff1 + GPREF_FPCT_PRIOR_K))
    exp_sf1 = (40.0 - 20.0) * (neff1 / (neff1 + GPREF_SF_PRIOR_K))
    exp_wr1 = (2.0 + GPREF_WR_PRIOR_W) / (2.0 + GPREF_WR_PRIOR_N)

    neff2 = (1.0 * 1.0) / (1.0 + 1.0)
    exp_fp2 = (0.0 - 1.0) * (neff2 / (neff2 + GPREF_FPCT_PRIOR_K))
    exp_sf2 = (10.0 - 30.0) * (neff2 / (neff2 + GPREF_SF_PRIOR_K))
    exp_wr2 = (0.0 + GPREF_WR_PRIOR_W) / (1.0 + GPREF_WR_PRIOR_N)

    assert tgt.loc["H1", "gpref_wet_n"] == pytest.approx(2.0)
    assert tgt.loc["H1", "gpref_wet_wr"] == pytest.approx(exp_wr1)
    assert tgt.loc["H1", "gpref_wet_fpct_delta"] == pytest.approx(exp_fp1)
    assert tgt.loc["H1", "gpref_wet_sf_delta"] == pytest.approx(exp_sf1)
    assert tgt.loc["H1", "gpref_wet_x_fpct_delta"] == pytest.approx(exp_fp1)
    assert tgt.loc["H1", "gpref_wet_x_sf_delta"] == pytest.approx(exp_sf1)

    assert tgt.loc["H2", "gpref_wet_n"] == pytest.approx(1.0)
    assert tgt.loc["H2", "gpref_wet_wr"] == pytest.approx(exp_wr2)
    assert tgt.loc["H2", "gpref_wet_fpct_delta"] == pytest.approx(exp_fp2)
    assert tgt.loc["H2", "gpref_wet_sf_delta"] == pytest.approx(exp_sf2)

    mean_x = (exp_fp1 + exp_fp2) / 2.0
    assert tgt.loc["H1", "gpref_wet_x_fpct_rel"] == pytest.approx(exp_fp1 - mean_x)
    assert tgt.loc["H2", "gpref_wet_x_fpct_rel"] == pytest.approx(exp_fp2 - mean_x)

    assert tgt.loc["H_MAIDEN", "gpref_wet_n"] == pytest.approx(0.0)
    for col in ("gpref_wet_wr", "gpref_wet_fpct_delta", "gpref_wet_sf_delta", "gpref_wet_x_fpct_delta", "gpref_wet_x_sf_delta", "gpref_wet_x_fpct_rel"):
        assert np.isnan(tgt.loc["H_MAIDEN", col])

    for col in GPREF_COLS:
        assert np.isnan(tgt.loc["H_SCR", col])


def _synthetic_history_df():
    return pd.DataFrame(
        [
            {"race_id": "2026-01-01_Ankara_1", "date": "2026-01-01", "city": "Ankara", "race_no": 1, "post_time": "14:00", "surface": "Çim", "track_cond": "yumusak", "track_cond_raw": "Çim: Yumuşak 3,6", "horse_key": "H1", "finish": 1, "sf": 35.0, "fpct": 0.0, "scratched": 0},
            {"race_id": "2026-01-01_Ankara_1", "date": "2026-01-01", "city": "Ankara", "race_no": 1, "post_time": "14:00", "surface": "Çim", "track_cond": "yumusak", "track_cond_raw": "Çim: Yumuşak 3,6", "horse_key": "H2", "finish": 2, "sf": 25.0, "fpct": 1.0, "scratched": 0},
            {"race_id": "2026-02-01_Ankara_1", "date": "2026-02-01", "city": "Ankara", "race_no": 1, "post_time": "14:30", "surface": "Kum", "track_cond": "normal", "track_cond_raw": "Kum: Normal", "horse_key": "H1", "finish": 2, "sf": 20.0, "fpct": 1.0, "scratched": 0},
            {"race_id": "2026-02-01_Ankara_1", "date": "2026-02-01", "city": "Ankara", "race_no": 1, "post_time": "14:30", "surface": "Kum", "track_cond": "normal", "track_cond_raw": "Kum: Normal", "horse_key": "H2", "finish": 1, "sf": 32.0, "fpct": 0.0, "scratched": 0},
            {"race_id": "2026-04-01_Ankara_1", "date": "2026-04-01", "city": "Ankara", "race_no": 1, "post_time": "15:00", "surface": "Çim", "track_cond": "agir", "track_cond_raw": "Çim: Ağır 4,8", "horse_key": "H1", "finish": np.nan, "sf": np.nan, "fpct": np.nan, "scratched": 0},
            {"race_id": "2026-04-01_Ankara_1", "date": "2026-04-01", "city": "Ankara", "race_no": 1, "post_time": "15:00", "surface": "Çim", "track_cond": "agir", "track_cond_raw": "Çim: Ağır 4,8", "horse_key": "H2", "finish": np.nan, "fpct": np.nan, "sf": np.nan, "scratched": 0},
        ]
    )


def _synthetic_tables():
    return {
        "day_cond": pd.DataFrame(
            [
                {"date": "2026-01-01", "city": "Ankara", "cim_raw": "Çim: Yumuşak 3,6", "kum_raw": None, "sentetik_raw": None, "temp_c": 11.0, "rh": 82.0, "sky": "yagisli", "windy": 1},
                {"date": "2026-02-01", "city": "Ankara", "cim_raw": None, "kum_raw": "Kum: Normal", "sentetik_raw": None, "temp_c": 19.0, "rh": 40.0, "sky": "acik", "windy": 0},
                {"date": "2026-04-01", "city": "Ankara", "cim_raw": "Çim: Ağır 4,8", "kum_raw": None, "sentetik_raw": None, "temp_c": 14.0, "rh": 75.0, "sky": "yagisli", "windy": 0},
            ]
        ),
    }


def test_v11_strict_future_invariance():
    base = _synthetic_history_df()
    tables = _synthetic_tables()

    future_mod = base.copy()
    mask_0401 = future_mod["date"] == "2026-04-01"
    future_mod.loc[mask_0401, "finish"] = [2.0, 1.0]
    future_mod.loc[mask_0401, "sf"] = [5.0, 50.0]
    future_mod.loc[mask_0401, "fpct"] = [1.0, 0.0]

    extra_future = pd.DataFrame(
        [
            {"race_id": "2026-05-01_Ankara_1", "date": "2026-05-01", "city": "Ankara", "race_no": 1, "post_time": "15:00", "surface": "Çim", "track_cond": "islak", "track_cond_raw": "Çim: Islak", "horse_key": "H1", "finish": 1, "sf": 60.0, "fpct": 0.0, "scratched": 0},
            {"race_id": "2026-05-01_Ankara_1", "date": "2026-05-01", "city": "Ankara", "race_no": 1, "post_time": "15:00", "surface": "Çim", "track_cond": "islak", "track_cond_raw": "Çim: Islak", "horse_key": "H2", "finish": 2, "sf": 10.0, "fpct": 1.0, "scratched": 0},
        ]
    )
    future_mod = pd.concat([future_mod, extra_future], ignore_index=True)

    out_base = attach_v11(base, blocks=V11_CANDIDATE_BLOCKS, v5_tables=tables)
    out_fut = attach_v11(future_mod, blocks=V11_CANDIDATE_BLOCKS, v5_tables=tables).iloc[: len(base)].reset_index(drop=True)

    v11_cols = [c for b in V11_CANDIDATE_BLOCKS for c in V11_BLOCK_COLS[b]]
    for col in v11_cols:
        a = out_base[col].to_numpy(dtype=np.float64)
        b = out_fut[col].to_numpy(dtype=np.float64)
        assert np.array_equal(a, b, equal_nan=True), f"Gelecek sızıntısı: {col}"


def test_v11_same_day_freeze():
    base = _synthetic_history_df()
    tables = _synthetic_tables()
    earlier_same_day = pd.DataFrame(
        [
            {"race_id": "2026-04-01_Ankara_0", "date": "2026-04-01", "city": "Ankara", "race_no": 0, "post_time": "13:00", "surface": "Çim", "track_cond": "agir", "track_cond_raw": "Çim: Ağır 4,8", "horse_key": "H1", "finish": 1, "sf": 99.0, "fpct": 0.0, "scratched": 0},
            {"race_id": "2026-04-01_Ankara_0", "date": "2026-04-01", "city": "Ankara", "race_no": 0, "post_time": "13:00", "surface": "Çim", "track_cond": "agir", "track_cond_raw": "Çim: Ağır 4,8", "horse_key": "H2", "finish": 2, "sf": 1.0, "fpct": 1.0, "scratched": 0},
        ]
    )
    with_same_day = pd.concat([base, earlier_same_day], ignore_index=True)

    out_base = attach_v11(base, blocks=V11_CANDIDATE_BLOCKS, v5_tables=tables)
    out_same = attach_v11(with_same_day, blocks=V11_CANDIDATE_BLOCKS, v5_tables=tables)

    b_rows = out_base[out_base["race_id"] == "2026-04-01_Ankara_1"].sort_values("horse_key").reset_index(drop=True)
    s_rows = out_same[out_same["race_id"] == "2026-04-01_Ankara_1"].sort_values("horse_key").reset_index(drop=True)
    for col in [c for b in V11_CANDIDATE_BLOCKS for c in V11_BLOCK_COLS[b]]:
        assert np.array_equal(
            b_rows[col].to_numpy(dtype=np.float64),
            s_rows[col].to_numpy(dtype=np.float64),
            equal_nan=True,
        ), f"Aynı gün sızıntısı: {col}"


def test_v11_row_order_invariance_and_scratched():
    base = _synthetic_history_df()
    tables = _synthetic_tables()
    scr = pd.DataFrame(
        [
            {"race_id": "2026-04-01_Ankara_1", "date": "2026-04-01", "city": "Ankara", "race_no": 1, "post_time": "15:00", "surface": "Çim", "track_cond": "agir", "track_cond_raw": "Çim: Ağır 4,8", "horse_key": "H_SCR", "finish": np.nan, "sf": np.nan, "fpct": np.nan, "scratched": 1},
        ]
    )
    df_with_scr = pd.concat([base, scr], ignore_index=True)
    out_orig = attach_v11(df_with_scr, blocks=V11_CANDIDATE_BLOCKS, v5_tables=tables)

    scr_out = out_orig[out_orig["scratched"] == 1]
    v11_cols = [c for b in V11_CANDIDATE_BLOCKS for c in V11_BLOCK_COLS[b]]
    for col in v11_cols:
        assert scr_out[col].isna().all(), f"Koşmaz at için NaN değil: {col}"

    shuffled = df_with_scr.sample(frac=1.0, random_state=42).reset_index(drop=True)
    out_shuf = attach_v11(shuffled, blocks=V11_CANDIDATE_BLOCKS, v5_tables=tables)

    o_sorted = out_orig.sort_values(["race_id", "horse_key"]).reset_index(drop=True)
    s_sorted = out_shuf.sort_values(["race_id", "horse_key"]).reset_index(drop=True)
    for col in v11_cols:
        assert np.array_equal(
            o_sorted[col].to_numpy(dtype=np.float64),
            s_sorted[col].to_numpy(dtype=np.float64),
            equal_nan=True,
        ), f"Satır sırası duyarlılığı: {col}"


def test_v11_empty_and_invalid_block():
    empty = pd.DataFrame(columns=["race_id", "date", "city", "race_no", "horse_key", "surface", "finish", "scratched"])
    for fn in (attach_GOING, attach_WX, attach_GPREF):
        res = fn(empty)
        assert len(res) == 0

    res_all = attach_v11(empty, blocks=V11_CANDIDATE_BLOCKS)
    assert len(res_all) == 0
    for b in V11_CANDIDATE_BLOCKS:
        for col in V11_BLOCK_COLS[b]:
            assert col in res_all.columns

    with pytest.raises(ValueError):
        attach_v11(empty, blocks=("GOING", "BAD_BLOCK"))
    with pytest.raises(ValueError):
        get_v11_cols(v11_blocks=("BAD_BLOCK",))

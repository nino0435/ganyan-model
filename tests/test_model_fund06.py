"""Birim testleri: ganyan/model_fund06.py (AGF'siz saf-güç teşhis modeli)."""
import numpy as np
import pandas as pd
import pytest

from ganyan.model_benter import TODAY_AGF_COLS, get_fund_cols
from ganyan.model_fund06 import (
    FUND06_CONFIG,
    FUND06_LIVE_MODEL_VERSION,
    FUND06_TRAIN_START,
    fit_predict_fund06_live,
)
from ganyan.model_v10 import V10_CONFIG


def test_fund06_config_strips_today_agf_cols_and_matches_report():
    assert FUND06_CONFIG["variant"] == "FUND_06"
    assert FUND06_CONFIG["require_agf"] is False
    assert FUND06_CONFIG["train_start_year"] == 2006
    assert FUND06_CONFIG["calibration"] is None
    assert FUND06_CONFIG["seeds"] == [0]
    assert FUND06_CONFIG["feature_cols"] == get_fund_cols(pure_sport=False)
    assert len(FUND06_CONFIG["feature_cols"]) == 147
    assert not (set(FUND06_CONFIG["feature_cols"]) & set(TODAY_AGF_COLS))
    # V10'un 155 özelliğinin kesin bir alt kümesi (canlıda feat_v10'un yeniden kullanılabilmesi için önemli).
    assert set(FUND06_CONFIG["feature_cols"]) <= set(V10_CONFIG["feature_cols"])


def test_fund06_live_model_version_and_train_start():
    assert FUND06_LIVE_MODEL_VERSION == "fund_06"
    assert FUND06_TRAIN_START == "2006-01-01"


def _synthetic_df(n_races=8, horses_per_race=6, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    cols = FUND06_CONFIG["feature_cols"]
    dates = pd.date_range("2024-01-01", periods=n_races, freq="7D")
    for ri, d in enumerate(dates):
        rid = f"r{ri}"
        winner = int(rng.integers(0, horses_per_race))
        for hi in range(horses_per_race):
            row = {c: float(rng.normal()) for c in cols}
            row.update(
                {
                    "race_id": rid,
                    "date": d,
                    "win": 1 if hi == winner else 0,
                    "finish": 1 if hi == winner else hi + 2,
                    "agf_share": float(rng.random()),
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def test_fit_predict_fund06_live_smoke_no_agf_needed():
    df = _synthetic_df()
    train_df = df[df["date"] < "2024-02-15"]
    today_df = df[df["date"] == df["date"].max()].copy()

    # agf_share'i tamamen bozsak bile (AGF'siz model olduğu için) tahmin bozulmamalı / hata vermemeli.
    today_df["agf_share"] = np.nan

    p = fit_predict_fund06_live(train_df, today_df, config=FUND06_CONFIG)
    assert len(p) == len(today_df)
    assert np.all(np.isfinite(p))
    assert np.all(p >= 0.0)
    assert p.sum() == pytest.approx(1.0, abs=1e-6)


def test_fit_predict_fund06_live_empty_today_returns_empty():
    df = _synthetic_df()
    train_df = df
    today_df = df.iloc[0:0]
    p = fit_predict_fund06_live(train_df, today_df, config=FUND06_CONFIG)
    assert len(p) == 0


def test_fit_predict_fund06_live_cache_roundtrip(tmp_path):
    df = _synthetic_df()
    train_df = df[df["date"] < "2024-02-15"]
    today_df = df[df["date"] == df["date"].max()].copy()
    cache_path = tmp_path / "2024-02-22_fund_06.pkl"

    p1 = fit_predict_fund06_live(
        train_df,
        today_df,
        config=FUND06_CONFIG,
        cache_path=str(cache_path),
        cache_meta={"date": "2024-02-22", "train_start": FUND06_TRAIN_START},
    )
    assert cache_path.exists()

    # İkinci çağrı aynı günü/anahtarı önbellekten okumalı ve birebir aynı sonucu vermeli.
    p2 = fit_predict_fund06_live(
        train_df,
        today_df,
        config=FUND06_CONFIG,
        cache_path=str(cache_path),
        cache_meta={"date": "2024-02-22", "train_start": FUND06_TRAIN_START},
    )
    np.testing.assert_allclose(p1, p2)

"""Model FUND_06: AGF'siz saf-güç teşhis modeli — canlıda yalnız ek kayıt, varsayılan modeli değiştirmez.

`reports/BENTER.md` / `docs/BENTER_BULGULAR.md`'deki "FUND_06" varyantının canlı/ileri-test sürümü: V10'un 155
özelliğinden bugünün AGF'sine dokunan 8 sütun çıkarılmış (147 özellik, `get_fund_cols`), 2006'dan itibaren eğitim,
tek tohum, sıcaklık kalibrasyonu yok (ham log-loss için). `forward_v5.py`'de yalnız `fund_06` adıyla `--models`
listesine eklenince devreye girer; canlı varsayılan `v10_hlb` modeline hiç dokunmaz.
"""
import numpy as np

from ganyan import model_v6
from ganyan.model_benter import get_fund_cols
from ganyan.model_v10 import V10_CONFIG

FUND06_LIVE_MODEL_VERSION = "fund_06"
FUND06_TRAIN_START = "2006-01-01"

FUND06_CONFIG = {
    "variant": "FUND_06",
    "family": "BENTER",
    "description": (
        "AGF'siz saf güç modeli (147 özellik, bugünün AGF'sine bağlı 8 sütun çıkarılmış, 2006'dan itibaren "
        "eğitim, 1 tohum, kalibrasyonsuz) — teşhis amaçlı canlı kayıt."
    ),
    "history_start": str(V10_CONFIG["history_start"]),
    "history_start_year": int(V10_CONFIG["history_start_year"]),
    "train_start_year": 2006,
    "require_agf": False,
    "v7_blocks": list(V10_CONFIG["v7_blocks"]),
    "v8_blocks": list(V10_CONFIG["v8_blocks"]),
    "v9_blocks": list(V10_CONFIG["v9_blocks"]),
    "v10_blocks": list(V10_CONFIG["v10_blocks"]),
    "feature_cols": get_fund_cols(pure_sport=False),
    "hgb_params": dict(V10_CONFIG["hgb_params"]),
    "temporal_val_frac": None,
    "seeds": [0],
    "calibration": None,
}


def build_fund06_cache_key(date_str, train_start, config=None):
    """Build deterministic daily cache key `(date, train_start, config_digest)` for trained FUND_06 HGB bundle."""
    cfg = FUND06_CONFIG if config is None else config
    return model_v6.build_v6_cache_key(date_str, train_start, config=cfg)


def fit_fund06_model_bundle(train_df, config=None):
    """Fit single-seed HGB estimator specified by `config` (defaults to `FUND06_CONFIG`) on `train_df`."""
    cfg = FUND06_CONFIG if config is None else config
    return model_v6.fit_v6_model_bundle(train_df, config=cfg)


def predict_fund06_model_bundle(bundle, today_df, warn_fn=None):
    """Predict race-normalized `p_win` on `today_df` from a fitted FUND_06 bundle (no temperature calibration)."""
    if len(today_df) == 0:
        return np.zeros(0, dtype=np.float64)
    return model_v6.predict_v6_model_bundle(bundle, today_df, gamma=1.0, warn_fn=warn_fn)


def fit_predict_fund06_live(
    train_df,
    today_df,
    config=None,
    cache_path=None,
    cache_meta=None,
    warn_fn=None,
    **_ignored,
):
    """Core live/backcheck FUND_06 predictor: `train_df` + `today_df` -> 1-seed, uncalibrated `p_win`.

    When `cache_path` is provided, loads/saves the fitted HGB bundle keyed by
    `(date, train_start, config_digest)` and retrains automatically on any key mismatch.
    Accepts (and ignores) `year`/`gamma` keyword arguments so it can be called through the same
    generic dispatch helper used by `fit_predict_v10_live` et al.
    """
    cfg = FUND06_CONFIG if config is None else config
    if len(today_df) == 0:
        return np.zeros(0, dtype=np.float64)

    bundle = None
    if cache_path is not None:
        meta = dict(cache_meta or {})
        date_val = meta.get("date")
        if not date_val:
            if "date" in today_df.columns:
                import pandas as pd

                date_val = pd.Timestamp(today_df["date"].iloc[0]).strftime("%Y-%m-%d")
            else:
                date_val = str(today_df["race_id"].iloc[0])[:10]
        train_start_val = meta.get("train_start", FUND06_TRAIN_START)
        expected_key = build_fund06_cache_key(date_val, train_start_val, config=cfg)
        bundle = model_v6._load_v6_bundle_cache(cache_path, expected_key)
        if bundle is None:
            bundle = fit_fund06_model_bundle(train_df, config=cfg)
            try:
                model_v6._save_v6_bundle_cache({"cache_key": expected_key, "bundle": bundle}, cache_path)
            except OSError as exc:
                if warn_fn is not None:
                    warn_fn(f"UYARI: FUND_06 model önbelleği yazılamadı ({cache_path}): {exc}")
    else:
        bundle = fit_fund06_model_bundle(train_df, config=cfg)

    return predict_fund06_model_bundle(bundle, today_df, warn_fn=warn_fn)


__all__ = [
    "FUND06_CONFIG",
    "FUND06_LIVE_MODEL_VERSION",
    "FUND06_TRAIN_START",
    "build_fund06_cache_key",
    "fit_fund06_model_bundle",
    "fit_predict_fund06_live",
    "predict_fund06_model_bundle",
]

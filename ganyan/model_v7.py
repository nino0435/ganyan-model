"""Model v7: pinned V7_TCJP_CAL configuration, yearly gamma, and live predict/cache wrappers."""
import numpy as np
import pandas as pd

from ganyan import model_v6
from ganyan.features_v7 import get_v7_cols
from ganyan.model_v6 import V6_CONFIG

V7_LIVE_MODEL_VERSION = "v7_tcjp"
V7_BLOCKS = ("T", "C", "J", "P")

V7_CONFIG = {
    "variant": "V7_TCJP_CAL",
    "family": "V7",
    "description": (
        "V6 (E5_best_temp) + 4 gazete tecrübesi bloğu (T+C+J+P, 100 özellik, "
        "5 tohum + ileri-yürüyen sıcaklık kalibrasyonu)"
    ),
    "history_start": str(V6_CONFIG["history_start"]),
    "history_start_year": int(V6_CONFIG["history_start_year"]),
    "train_start_year": int(V6_CONFIG["train_start_year"]),
    "require_agf": bool(V6_CONFIG["require_agf"]),
    "extra_blocks": [],
    "v7_blocks": list(V7_BLOCKS),
    "feature_cols": get_v7_cols(v7_blocks=V7_BLOCKS, with_program=False),
    "hgb_params": dict(V6_CONFIG["hgb_params"]),
    "temporal_val_frac": None,
    "seeds": list(V6_CONFIG["seeds"]),
    "calibration": "temperature",
    "calibrated_from": "V7_TCJP_5s",
}

# Walk-forward temperature calibration gamma (= 1/T) per calendar year from reports/V7.md (V7_TCJP_CAL)
V7_YEARLY_GAMMA = {
    2017: 0.9900,
    2018: 0.9917,
    2019: 0.9958,
    2020: 0.9957,
    2021: 1.0046,
    2022: 1.0152,
    2023: 1.0285,
    2024: 1.0333,
    2025: 1.0337,
    2026: 1.0310,
}


def get_v7_gamma(year, warn_fn=None, gamma_table=None):
    """Return walk-forward temperature `gamma` for calendar `year` from `V7_YEARLY_GAMMA`.

    If `year` is absent from the table, falls back to the latest year in the table and emits a warning.
    """
    tbl = V7_YEARLY_GAMMA if gamma_table is None else gamma_table
    if not tbl:
        raise ValueError("V7_YEARLY_GAMMA tablosu boş olamaz.")
    y_int = int(year)
    if y_int in tbl:
        return float(tbl[y_int])
    last_year = max(int(k) for k in tbl)
    gamma_val = float(tbl[last_year])
    msg = (
        f"UYARI: V7 sıcaklık (gamma) tablosunda {y_int} yılı bulunamadı; "
        f"en son yıl ({last_year}) gamma={gamma_val:.4f} kullanılıyor (yeniden kalibrasyon önerilir)."
    )
    if warn_fn is not None:
        warn_fn(msg)
    else:
        print(msg, flush=True)
    return gamma_val


def build_v7_cache_key(date_str, train_start, config=None):
    """Build deterministic daily cache key `(date, train_start, config_digest)` for trained V7 HGB bundle."""
    cfg = V7_CONFIG if config is None else config
    if cfg is None:
        raise ValueError("V7_CONFIG tanımlı değil (None).")
    return model_v6.build_v6_cache_key(date_str, train_start, config=cfg)


def fit_v7_model_bundle(train_df, config=None):
    """Fit multi-seed HGB estimators specified by `config` (defaults to `V7_CONFIG`) on `train_df`."""
    cfg = V7_CONFIG if config is None else config
    if cfg is None:
        raise ValueError("V7_CONFIG tanımlı değil (None).")
    return model_v6.fit_v6_model_bundle(train_df, config=cfg)


def predict_v7_model_bundle(bundle, today_df, gamma=None, year=None, warn_fn=None):
    """Predict race-normalized, V7 temperature-calibrated `p_win` on `today_df` from a fitted V7 bundle."""
    if len(today_df) == 0:
        return np.zeros(0, dtype=np.float64)

    if gamma is not None:
        eff_gamma = float(gamma)
    else:
        if year is not None:
            eff_year = int(year)
        elif "date" in today_df.columns:
            eff_year = int(pd.Timestamp(today_df["date"].iloc[0]).year)
        else:
            eff_year = int(str(today_df["race_id"].iloc[0])[:4])
        eff_gamma = get_v7_gamma(eff_year, warn_fn=warn_fn)

    return model_v6.predict_v6_model_bundle(
        bundle,
        today_df,
        gamma=eff_gamma,
        year=year,
        warn_fn=warn_fn,
    )


def fit_predict_v7_live(
    train_df,
    today_df,
    config=None,
    gamma=None,
    year=None,
    cache_path=None,
    cache_meta=None,
    warn_fn=None,
):
    """Core live/backcheck V7 predictor: `train_df` + `today_df` -> 5-seed normalized + V7 `gamma`-calibrated `p_win`.

    When `cache_path` is provided, loads/saves the fitted 5-HGB bundle keyed by
    `(date, train_start, config_digest)` and retrains automatically on any key mismatch.
    """
    cfg = V7_CONFIG if config is None else config
    if cfg is None:
        raise ValueError("V7_CONFIG tanımlı değil (None).")
    if len(today_df) == 0:
        return np.zeros(0, dtype=np.float64)

    bundle = None
    if cache_path is not None:
        meta = dict(cache_meta or {})
        date_val = meta.get("date")
        if not date_val:
            if "date" in today_df.columns:
                date_val = pd.Timestamp(today_df["date"].iloc[0]).strftime("%Y-%m-%d")
            else:
                date_val = str(today_df["race_id"].iloc[0])[:10]
        train_start_val = meta.get("train_start", f"{int(cfg['train_start_year']):04d}-01-01")
        expected_key = build_v7_cache_key(date_val, train_start_val, config=cfg)
        bundle = model_v6._load_v6_bundle_cache(cache_path, expected_key)
        if bundle is None:
            bundle = fit_v7_model_bundle(train_df, config=cfg)
            try:
                model_v6._save_v6_bundle_cache({"cache_key": expected_key, "bundle": bundle}, cache_path)
            except OSError as exc:
                if warn_fn is not None:
                    warn_fn(f"UYARI: V7 model önbelleği yazılamadı ({cache_path}): {exc}")
    else:
        bundle = fit_v7_model_bundle(train_df, config=cfg)

    return predict_v7_model_bundle(bundle, today_df, gamma=gamma, year=year, warn_fn=warn_fn)


__all__ = [
    "V7_BLOCKS",
    "V7_CONFIG",
    "V7_LIVE_MODEL_VERSION",
    "V7_YEARLY_GAMMA",
    "build_v7_cache_key",
    "fit_predict_v7_live",
    "fit_v7_model_bundle",
    "get_v7_gamma",
    "predict_v7_model_bundle",
]

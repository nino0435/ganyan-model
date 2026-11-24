"""Model v10: pinned V10_HLB_CAL configuration, yearly gamma, and live predict/cache wrappers."""
import numpy as np
import pandas as pd

from ganyan import model_v6
from ganyan.features_v10 import get_v10_cols
from ganyan.model_v9 import V9_CONFIG

V10_LIVE_MODEL_VERSION = "v10_hlb"
V10_BLOCKS = ("BELL", "LOAD", "H2H")

V10_CONFIG = {
    "variant": "V10_HLB_CAL",
    "family": "V10",
    "description": (
        "V9 (V9_SEL_CAL) + 3 yeni bağlam bloğu (BELL: çan eğrisi/tavan + "
        "LOAD: iş yükü/hız ivmesi + H2H: ikili rekabet, 155 özellik, "
        "5 tohum + ileri-yürüyen sıcaklık kalibrasyonu)"
    ),
    "history_start": str(V9_CONFIG["history_start"]),
    "history_start_year": int(V9_CONFIG["history_start_year"]),
    "train_start_year": int(V9_CONFIG["train_start_year"]),
    "require_agf": bool(V9_CONFIG["require_agf"]),
    "extra_blocks": list(V9_CONFIG["extra_blocks"]),
    "v7_blocks": list(V9_CONFIG["v7_blocks"]),
    "v8_blocks": list(V9_CONFIG["v8_blocks"]),
    "v9_blocks": list(V9_CONFIG["v9_blocks"]),
    "v10_blocks": list(V10_BLOCKS),
    "feature_cols": get_v10_cols(v10_blocks=V10_BLOCKS, with_program=False),
    "hgb_params": dict(V9_CONFIG["hgb_params"]),
    "temporal_val_frac": V9_CONFIG["temporal_val_frac"],
    "seeds": list(V9_CONFIG["seeds"]),
    "calibration": str(V9_CONFIG["calibration"]),
    "calibrated_from": "V10_HLB_5s",
}

# Walk-forward temperature calibration gamma (= 1/T) per calendar year from reports/V10.md (V10_HLB_CAL)
V10_YEARLY_GAMMA = {
    2017: 0.9759,
    2018: 0.9843,
    2019: 0.9928,
    2020: 0.9942,
    2021: 1.0036,
    2022: 1.0136,
    2023: 1.0277,
    2024: 1.0326,
    2025: 1.0332,
    2026: 1.0304,
}


def get_v10_gamma(year, warn_fn=None, gamma_table=None):
    """Return walk-forward temperature `gamma` for calendar `year` from `V10_YEARLY_GAMMA`.

    If `year` is absent from the table, falls back to the latest year in the table and emits a warning.
    """
    tbl = V10_YEARLY_GAMMA if gamma_table is None else gamma_table
    if not tbl:
        raise ValueError("V10_YEARLY_GAMMA tablosu boş olamaz.")
    y_int = int(year)
    if y_int in tbl:
        return float(tbl[y_int])
    last_year = max(int(k) for k in tbl)
    gamma_val = float(tbl[last_year])
    msg = (
        f"UYARI: V10 sıcaklık (gamma) tablosunda {y_int} yılı bulunamadı; "
        f"en son yıl ({last_year}) gamma={gamma_val:.4f} kullanılıyor (yeniden kalibrasyon önerilir)."
    )
    if warn_fn is not None:
        warn_fn(msg)
    else:
        print(msg, flush=True)
    return gamma_val


def build_v10_cache_key(date_str, train_start, config=None):
    """Build deterministic daily cache key `(date, train_start, config_digest)` for trained V10 HGB bundle."""
    cfg = V10_CONFIG if config is None else config
    if cfg is None:
        raise ValueError("V10_CONFIG tanımlı değil (None).")
    return model_v6.build_v6_cache_key(date_str, train_start, config=cfg)


def fit_v10_model_bundle(train_df, config=None):
    """Fit multi-seed HGB estimators specified by `config` (defaults to `V10_CONFIG`) on `train_df`."""
    cfg = V10_CONFIG if config is None else config
    if cfg is None:
        raise ValueError("V10_CONFIG tanımlı değil (None).")
    return model_v6.fit_v6_model_bundle(train_df, config=cfg)


def predict_v10_model_bundle(bundle, today_df, gamma=None, year=None, warn_fn=None):
    """Predict race-normalized, V10 temperature-calibrated `p_win` on `today_df` from a fitted V10 bundle."""
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
        eff_gamma = get_v10_gamma(eff_year, warn_fn=warn_fn)

    return model_v6.predict_v6_model_bundle(
        bundle,
        today_df,
        gamma=eff_gamma,
        year=year,
        warn_fn=warn_fn,
    )


def fit_predict_v10_live(
    train_df,
    today_df,
    config=None,
    gamma=None,
    year=None,
    cache_path=None,
    cache_meta=None,
    warn_fn=None,
):
    """Core live/backcheck V10 predictor: `train_df` + `today_df` -> 5-seed normalized + V10 `gamma`-calibrated `p_win`.

    When `cache_path` is provided, loads/saves the fitted 5-HGB bundle keyed by
    `(date, train_start, config_digest)` and retrains automatically on any key mismatch.
    """
    cfg = V10_CONFIG if config is None else config
    if cfg is None:
        raise ValueError("V10_CONFIG tanımlı değil (None).")
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
        expected_key = build_v10_cache_key(date_val, train_start_val, config=cfg)
        bundle = model_v6._load_v6_bundle_cache(cache_path, expected_key)
        if bundle is None:
            bundle = fit_v10_model_bundle(train_df, config=cfg)
            try:
                model_v6._save_v6_bundle_cache({"cache_key": expected_key, "bundle": bundle}, cache_path)
            except OSError as exc:
                if warn_fn is not None:
                    warn_fn(f"UYARI: V10 model önbelleği yazılamadı ({cache_path}): {exc}")
    else:
        bundle = fit_v10_model_bundle(train_df, config=cfg)

    return predict_v10_model_bundle(bundle, today_df, gamma=gamma, year=year, warn_fn=warn_fn)


__all__ = [
    "V10_BLOCKS",
    "V10_CONFIG",
    "V10_LIVE_MODEL_VERSION",
    "V10_YEARLY_GAMMA",
    "build_v10_cache_key",
    "fit_predict_v10_live",
    "fit_v10_model_bundle",
    "get_v10_gamma",
    "predict_v10_model_bundle",
]

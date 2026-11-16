"""Model v6: candidate configurations, multi-seed HGB, walk-forward calibration, gate, and EV metrics."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import pickle
import pprint
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression

from ganyan.features_v6 import V6_BLOCK_COLS
from ganyan.model_v5 import (
    _group_races_contiguous,
    bootstrap_mean_ci,
    compute_edge_buckets,
    compute_top1_roi,
    get_b1x_cols,
    to_log_prob,
)

V5_DB_HISTORY_START = "2006-03-04"
FULL_HISTORY_START = "2005-01-01"
SHORT_HISTORY_START = "2015-01-01"

# Exact match to ganyan.model.make_estimator() (early_stopping='auto' is sklearn default)
DEFAULT_HGB_PARAMS = {
    "max_iter": 300,
    "learning_rate": 0.04,
    "max_leaf_nodes": 31,
    "min_samples_leaf": 60,
    "l2_regularization": 1.0,
    "early_stopping": "auto",
}

E2_VARIANT_NAMES = (
    "E2_01",
    "E2_02",
    "E2_03",
    "E2_04",
    "E2_05",
    "E2_06",
    "E2_07",
    "E2_08",
    "E2_09",
    "E2_10",
)

E4_VARIANT_NAMES = (
    "E4_gc",
    "E4_fark",
    "E4_s800",
    "E4_prize",
    "E4_pool",
    "E4_stew",
)

E1_E2_POOL = ("E1a", "E1b") + E2_VARIANT_NAMES
E1_TO_E4_POOL = E1_E2_POOL + ("E3",) + E4_VARIANT_NAMES

VARIANT_SPECS = {
    "E0": {
        "family": "E0",
        "description": "Taban B1_SGR (v5 ile birebir: 2006-03-04→ özellik geçmişi, 2015→ AGF'li eğitim, varsayılan HGB)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": dict(DEFAULT_HGB_PARAMS),
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    "E1a": {
        "family": "E1",
        "description": "Uzun geçmiş (a): 2005-01-01→ özellik geçmişi (at, Elo, hız referansı), 2015→ AGF'li eğitim",
        "history_start": FULL_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": dict(DEFAULT_HGB_PARAMS),
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    "E1b": {
        "family": "E1",
        "description": "Uzun geçmiş (b): 2005-01-01→ özellik geçmişi + 2005–2014 AGF'siz koşular eğitimde (AGF=NaN)",
        "history_start": FULL_HISTORY_START,
        "train_start_year": 2005,
        "require_agf": False,
        "extra_blocks": (),
        "hgb_params": dict(DEFAULT_HGB_PARAMS),
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    # E2: HGB hiperparametre ızgarası (10 yapılandırma <= 12 sınırı; hepsi E0 ile aynı geçmiş ve eğitim kuralında)
    "E2_01": {
        "family": "E2",
        "description": "HGB 01: düşük öğrenme hızı + auto erken durdurma (iter=550, lr=0.025, leaf=31, min=100, l2=3.0)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": {
            "max_iter": 550,
            "learning_rate": 0.025,
            "max_leaf_nodes": 31,
            "min_samples_leaf": 100,
            "l2_regularization": 3.0,
            "early_stopping": "auto",
        },
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    "E2_02": {
        "family": "E2",
        "description": "HGB 02: çok yavaş öğrenme + güçlü L2 (iter=700, lr=0.02, leaf=31, min=150, l2=5.0, auto)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": {
            "max_iter": 700,
            "learning_rate": 0.02,
            "max_leaf_nodes": 31,
            "min_samples_leaf": 150,
            "l2_regularization": 5.0,
            "early_stopping": "auto",
        },
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    "E2_03": {
        "family": "E2",
        "description": "HGB 03: sığ yaprak + %100 eğitim verisi (iter=450, lr=0.03, leaf=15, min=150, l2=5.0, es=False)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": {
            "max_iter": 450,
            "learning_rate": 0.03,
            "max_leaf_nodes": 15,
            "min_samples_leaf": 150,
            "l2_regularization": 5.0,
            "early_stopping": False,
        },
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    "E2_04": {
        "family": "E2",
        "description": "HGB 04: çok sığ eklemeli ağaçlar (iter=550, lr=0.025, leaf=10, min=200, l2=5.0, es=False)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": {
            "max_iter": 550,
            "learning_rate": 0.025,
            "max_leaf_nodes": 10,
            "min_samples_leaf": 200,
            "l2_regularization": 5.0,
            "early_stopping": False,
        },
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    "E2_05": {
        "family": "E2",
        "description": "HGB 05: orta yaprak + %100 eğitim verisi (iter=400, lr=0.03, leaf=23, min=120, l2=3.0, es=False)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": {
            "max_iter": 400,
            "learning_rate": 0.03,
            "max_leaf_nodes": 23,
            "min_samples_leaf": 120,
            "l2_regularization": 3.0,
            "early_stopping": False,
        },
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    "E2_06": {
        "family": "E2",
        "description": "HGB 06: kuyruk düzenlileştirmesi (iter=380, lr=0.03, leaf=31, min=250, l2=10.0, es=False)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": {
            "max_iter": 380,
            "learning_rate": 0.03,
            "max_leaf_nodes": 31,
            "min_samples_leaf": 250,
            "l2_regularization": 10.0,
            "early_stopping": False,
        },
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    "E2_07": {
        "family": "E2",
        "description": "HGB 07: ağır yaprak alt sınırı + L2=15 (iter=420, lr=0.03, leaf=23, min=400, l2=15.0, es=False)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": {
            "max_iter": 420,
            "learning_rate": 0.03,
            "max_leaf_nodes": 23,
            "min_samples_leaf": 400,
            "l2_regularization": 15.0,
            "early_stopping": False,
        },
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    "E2_08": {
        "family": "E2",
        "description": "HGB 08: derin etkileşim + güçlü koruma (iter=420, lr=0.025, leaf=47, min=200, l2=8.0, auto)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": {
            "max_iter": 420,
            "learning_rate": 0.025,
            "max_leaf_nodes": 47,
            "min_samples_leaf": 200,
            "l2_regularization": 8.0,
            "early_stopping": "auto",
        },
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    "E2_09": {
        "family": "E2",
        "description": "HGB 09: geniş yaprak + yüksek min_samples_leaf (iter=360, lr=0.025, leaf=63, min=300, l2=10.0, auto)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": {
            "max_iter": 360,
            "learning_rate": 0.025,
            "max_leaf_nodes": 63,
            "min_samples_leaf": 300,
            "l2_regularization": 10.0,
            "early_stopping": "auto",
        },
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    "E2_10": {
        "family": "E2",
        "description": "HGB 10: zamansal koşu-NLL erken durdurma (eğitim son %15 gün doğrulama, iter<=550, lr=0.03, leaf=23, min=180, l2=6.0)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": {
            "max_iter": 550,
            "learning_rate": 0.03,
            "max_leaf_nodes": 23,
            "min_samples_leaf": 180,
            "l2_regularization": 6.0,
            "early_stopping": False,
        },
        "temporal_val_frac": 0.15,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    # E3: E1/E2'nin Aşama A en iyisi üzerinde 5 tohum ortalaması + koşu içi normalize
    "E3": {
        "family": "E3",
        "description": "Çoklu tohum: E1/E2 en iyisi üzerinde 5 tohum (0..4) ham olasılık ortalaması + koşu içi normalize",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": dict(DEFAULT_HGB_PARAMS),
        "temporal_val_frac": None,
        "seeds": (0, 1, 2, 3, 4),
        "calibration": None,
        "fixed_base": None,
        "base_pool": E1_E2_POOL,
    },
    # E4: 6 sızıntısız koşu-öncesi özellik grubu (<= 6 sınırı; her biri ayrı varyant)
    "E4_gc": {
        "family": "E4",
        "description": "Yeni özellik 1 (X_GC): runner_extra geç çıkış geçmişi (< D)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": ("X_GC",),
        "hgb_params": dict(DEFAULT_HGB_PARAMS),
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    "E4_fark": {
        "family": "E4",
        "description": "Yeni özellik 2 (X_FARK): runner_extra bitiş farkı hakimiyeti ve yakın kayıp geçmişi (< D)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": ("X_FARK",),
        "hgb_params": dict(DEFAULT_HGB_PARAMS),
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    "E4_s800": {
        "family": "E4",
        "description": "Yeni özellik 3 (X_S800): race_extra kapanış son 800m hız ve tempo oranı geçmişi (< D)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": ("X_S800",),
        "hgb_params": dict(DEFAULT_HGB_PARAMS),
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    "E4_prize": {
        "family": "E4",
        "description": "Yeni özellik 4 (X_PRIZE): enflasyon-düzeltmeli race_extra birincilik ikramiyesi sınıf geçmişi (< D)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": ("X_PRIZE",),
        "hgb_params": dict(DEFAULT_HGB_PARAMS),
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    "E4_pool": {
        "family": "E4",
        "description": "Yeni özellik 5 (X_POOL): pools şehir bahis havuzu derinliği ve deplasman farkı (< D)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": ("X_POOL",),
        "hgb_params": dict(DEFAULT_HGB_PARAMS),
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    "E4_stew": {
        "family": "E4",
        "description": "Yeni özellik 6 (X_STEW): steward_notes komiser raporu geçmişi (< D)",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": ("X_STEW",),
        "hgb_params": dict(DEFAULT_HGB_PARAMS),
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    },
    # E5: İleri-yürüyen (yalnız önceki yılların tahminleriyle) koşu-içi sıcaklık ve izotonik kalibrasyon
    "E5_temp": {
        "family": "E5",
        "description": "Kalibrasyon (sıcaklık / E0): önceki yılların örnek-dışı tahminleriyle koşu-içi logit ölçekleme",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": dict(DEFAULT_HGB_PARAMS),
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": "temperature",
        "fixed_base": "E0",
        "base_pool": None,
    },
    "E5_iso": {
        "family": "E5",
        "description": "Kalibrasyon (izotonik / E0): önceki yılların örnek-dışı tahminleriyle izotonik + koşu-içi normalize",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": dict(DEFAULT_HGB_PARAMS),
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": "isotonic",
        "fixed_base": "E0",
        "base_pool": None,
    },
    "E5_best_temp": {
        "family": "E5",
        "description": "Kalibrasyon (sıcaklık / Aşama A en iyisi): önceki yılların tahminleriyle koşu-içi logit ölçekleme",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": dict(DEFAULT_HGB_PARAMS),
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": "temperature",
        "fixed_base": None,
        "base_pool": E1_TO_E4_POOL,
    },
    "E5_best_iso": {
        "family": "E5",
        "description": "Kalibrasyon (izotonik / Aşama A en iyisi): önceki yılların tahminleriyle izotonik + koşu-içi normalize",
        "history_start": V5_DB_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": dict(DEFAULT_HGB_PARAMS),
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": "isotonic",
        "fixed_base": None,
        "base_pool": E1_TO_E4_POOL,
    },
}

# Diagnostic-only control (quantifies stripping 2005–2014 feature history; does not enter candidate selection)
DIAGNOSTIC_SPECS = {
    "Ref_2015_Gecmis": {
        "family": "Kontrol",
        "description": "Geçmiş kontrolü: yalnız 2015-01-01→ özellik geçmişi + 2015→ AGF'li eğitim (2005–2014 geçmişi kesilmiş)",
        "history_start": SHORT_HISTORY_START,
        "train_start_year": 2015,
        "require_agf": True,
        "extra_blocks": (),
        "hgb_params": dict(DEFAULT_HGB_PARAMS),
        "temporal_val_frac": None,
        "seeds": (0,),
        "calibration": None,
        "fixed_base": None,
        "base_pool": None,
    }
}

CANDIDATE_VARIANTS = tuple(v for v in VARIANT_SPECS if v != "E0")

STAGE_A_YEARS = (2017, 2018, 2019, 2020, 2021)
STAGE_B_YEARS = (2022, 2023, 2024, 2025)
STAGE_C_YEARS = (2026,)

# Uzun koşu sonunda Aşama B kapısını geçen aday olursa tam yapılandırması buraya sabitlenir;
# kapıyı geçen aday yoksa None kalır (B1_SGR korunur).
# --- V6_CONFIG_START ---
V6_CONFIG = {'calibrated_from': 'E3',
 'calibration': 'temperature',
 'description': 'Kalibrasyon (sıcaklık / Aşama A en iyisi): önceki yılların tahminleriyle koşu-içi '
                'logit ölçekleme',
 'extra_blocks': [],
 'family': 'E5',
 'feature_cols': ['h_n',
                  'h_wr',
                  'h_t3r',
                  'h_fpct_last',
                  'h_fpct_m3',
                  'h_sf_last',
                  'h_sf_m3',
                  'h_sf_best',
                  'h_beaten_last',
                  'h_beaten_m3',
                  'h_logodds_last',
                  'h_logodds_m3',
                  'h_days',
                  'h_dist_chg',
                  'h_same_surf',
                  'j_n',
                  'j_wr',
                  't_n',
                  't_wr',
                  'weight',
                  'hp',
                  'age',
                  'sex_d',
                  'gate',
                  'gate_frac',
                  'field',
                  'distance',
                  'surf',
                  'arap',
                  'weight_rel',
                  'weight_rk',
                  'hp_rel',
                  'hp_rk',
                  'h_sf_m3_rel',
                  'h_sf_m3_rk',
                  'h_sf_best_rel',
                  'h_sf_best_rk',
                  'j_wr_rel',
                  'j_wr_rk',
                  'h_logodds_m3_rel',
                  'h_logodds_m3_rk',
                  'h_fpct_m3_rel',
                  'h_fpct_m3_rk',
                  'agf_share',
                  'log_agf',
                  'yb_hiz_last',
                  'yb_hiz_m3',
                  'yb_hiz_best5',
                  'yb_hiz_n',
                  'sfa_last',
                  'sfa_m3',
                  'sfa_best5',
                  'g_n14',
                  'g_n30',
                  'g_days_last',
                  'g_last_d400',
                  'g_last_d600',
                  'g_last_d800',
                  'g_best_d400_30',
                  'g_best_d800_30',
                  'g_allout_30',
                  'g_sprint_30',
                  'g_last_d400_rel',
                  'elo_h',
                  'elo_j',
                  'elo_t',
                  'elo_h_rel',
                  'elo_h_rk'],
 'hgb_params': {'early_stopping': False,
                'l2_regularization': 15.0,
                'learning_rate': 0.03,
                'max_iter': 420,
                'max_leaf_nodes': 23,
                'min_samples_leaf': 400},
 'history_start': '2006-03-04',
 'history_start_year': 2006,
 'require_agf': True,
 'seeds': [0, 1, 2, 3, 4],
 'temporal_val_frac': None,
 'train_start_year': 2015,
 'variant': 'E5_best_temp'}
# --- V6_CONFIG_END ---

V6_LIVE_MODEL_VERSION = "v6_e5"

# Walk-forward temperature calibration gamma (= 1/T) per calendar year from reports/V6.md (E5_best_temp)
V6_YEARLY_GAMMA = {
    2017: 0.9794,
    2018: 0.9844,
    2019: 0.9915,
    2020: 0.9932,
    2021: 1.0030,
    2022: 1.0139,
    2023: 1.0278,
    2024: 1.0331,
    2025: 1.0336,
    2026: 1.0307,
}


def _normalize_history_start(val):
    if isinstance(val, (int, np.integer)):
        return f"{int(val):04d}-01-01"
    s = str(val).strip()
    if len(s) == 4 and s.isdigit():
        return f"{int(s):04d}-01-01"
    return s


def get_v6_cols(extra_blocks=(), with_program=False):
    """Return B1_SGR feature list extended with selected `V6_BLOCK_COLS` (order-preserving, deduplicated)."""
    cols = list(get_b1x_cols("B1_SGR", with_program=with_program))
    for blk in extra_blocks or ():
        if blk not in V6_BLOCK_COLS:
            raise ValueError(f"Unknown v6 extra block: {blk!r}. Expected one of {list(V6_BLOCK_COLS)}.")
        cols.extend(V6_BLOCK_COLS[blk])
    return list(dict.fromkeys(cols))


def resolve_variant_config(variant, base_config=None, extra_meta=None):
    """Build a self-contained resolved configuration dictionary for `variant`."""
    all_specs = {**VARIANT_SPECS, **DIAGNOSTIC_SPECS}
    if variant not in all_specs:
        raise ValueError(f"Bilinmeyen V6 varyantı: {variant!r}. Geçerli: {list(VARIANT_SPECS)}")
    spec = copy.deepcopy(all_specs[variant])

    if base_config is not None:
        hist_src = base_config.get("history_start", base_config.get("history_start_year", spec["history_start"]))
        spec["history_start"] = _normalize_history_start(hist_src)
        spec["train_start_year"] = int(base_config["train_start_year"])
        spec["require_agf"] = bool(base_config["require_agf"])
        spec["extra_blocks"] = tuple(base_config["extra_blocks"])
        merged_hgb = dict(DEFAULT_HGB_PARAMS)
        merged_hgb.update(base_config["hgb_params"])
        spec["hgb_params"] = merged_hgb
        spec["temporal_val_frac"] = base_config.get("temporal_val_frac")
        if spec["calibration"] is not None:
            spec["seeds"] = tuple(base_config["seeds"])
            spec["calibrated_from"] = str(base_config.get("variant", ""))
        elif variant == "E3":
            spec["ensemble_from"] = str(base_config.get("variant", ""))
    elif spec.get("fixed_base"):
        fb_name = str(spec["fixed_base"])
        fb_cfg = resolve_variant_config(fb_name)
        spec["history_start"] = fb_cfg["history_start"]
        spec["train_start_year"] = fb_cfg["train_start_year"]
        spec["require_agf"] = fb_cfg["require_agf"]
        spec["extra_blocks"] = tuple(fb_cfg["extra_blocks"])
        spec["hgb_params"] = dict(fb_cfg["hgb_params"])
        spec["temporal_val_frac"] = fb_cfg["temporal_val_frac"]
        spec["seeds"] = tuple(fb_cfg["seeds"])
        spec["calibrated_from"] = fb_name

    hist_str = _normalize_history_start(spec["history_start"])
    cols = get_v6_cols(extra_blocks=spec["extra_blocks"], with_program=False)
    merged_params = dict(DEFAULT_HGB_PARAMS)
    merged_params.update(spec["hgb_params"])

    resolved = {
        "variant": str(variant),
        "family": str(spec["family"]),
        "description": str(spec["description"]),
        "history_start": hist_str,
        "history_start_year": int(hist_str[:4]),
        "train_start_year": int(spec["train_start_year"]),
        "require_agf": bool(spec["require_agf"]),
        "extra_blocks": list(spec["extra_blocks"]),
        "feature_cols": cols,
        "hgb_params": {k: merged_params[k] for k in sorted(merged_params)},
        "temporal_val_frac": (
            float(spec["temporal_val_frac"]) if spec.get("temporal_val_frac") is not None else None
        ),
        "seeds": [int(s) for s in spec["seeds"]],
        "calibration": spec["calibration"],
    }
    if "ensemble_from" in spec:
        resolved["ensemble_from"] = spec["ensemble_from"]
    if "calibrated_from" in spec:
        resolved["calibrated_from"] = spec["calibrated_from"]
    if extra_meta:
        for k, v in sorted(extra_meta.items()):
            resolved[str(k)] = v
    return resolved


def config_digest(resolved_cfg):
    """Return deterministic 10-hex SHA1 digest of a resolved variant configuration."""
    hash_payload = {
        k: v
        for k, v in resolved_cfg.items()
        if k not in ("description", "family")
    }
    blob = json.dumps(hash_payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10]


def pin_v6_config_in_source(config_obj, module_path=None):
    """Deterministically write `V6_CONFIG = ...` into `model_v6.py` (or `module_path`) and validate syntax."""
    target = Path(module_path) if module_path is not None else Path(__file__).resolve()
    src = target.read_text(encoding="utf-8")

    start_marker = "# --- V6_CONFIG_START ---\n"
    end_marker = "\n# --- V6_CONFIG_END ---"
    s_idx = src.find(start_marker)
    e_idx = src.find(end_marker)
    if s_idx < 0 or e_idx < 0 or e_idx < s_idx:
        raise RuntimeError(f"V6_CONFIG sınır işaretçileri bulunamadı: {target}")

    if config_obj is None:
        formatted = "None"
    else:
        clean_copy = json.loads(json.dumps(config_obj, sort_keys=True))
        formatted = pprint.pformat(clean_copy, width=100, sort_dicts=True)

    new_src = (
        src[: s_idx + len(start_marker)]
        + f"V6_CONFIG = {formatted}"
        + src[e_idx:]
    )
    ast.parse(new_src, filename=str(target))

    tmp_target = target.with_name(f".{target.name}.tmp.{os.getpid()}")
    tmp_target.write_text(new_src, encoding="utf-8")
    os.replace(tmp_target, target)
    return str(target)


def make_v6_estimator(hgb_params=None, random_state=0):
    """Instantiate HistGradientBoostingClassifier with merged `DEFAULT_HGB_PARAMS` and `random_state`."""
    params = dict(DEFAULT_HGB_PARAMS)
    if hgb_params:
        params.update(hgb_params)
    es_val = params.get("early_stopping", "auto")
    if isinstance(es_val, str) and es_val.lower() == "false":
        es_val = False
    elif isinstance(es_val, str) and es_val.lower() == "true":
        es_val = True
    return HistGradientBoostingClassifier(
        max_iter=int(params["max_iter"]),
        learning_rate=float(params["learning_rate"]),
        max_leaf_nodes=int(params["max_leaf_nodes"]),
        min_samples_leaf=int(params["min_samples_leaf"]),
        l2_regularization=float(params["l2_regularization"]),
        early_stopping=es_val,
        random_state=int(random_state),
    )


def race_normalize_probs(p_raw, race_ids):
    """Normalize positive scores `p_raw` within each contiguous/non-contiguous `race_id` to sum to 1."""
    arr = np.asarray(p_raw, dtype=np.float64)
    if len(arr) != len(race_ids):
        raise ValueError("p_raw and race_ids must have equal length.")
    if len(arr) == 0:
        return np.zeros(0, dtype=np.float64)

    order, starts, _ends, counts = _group_races_contiguous(race_ids)
    ps = np.where(np.isfinite(arr[order]) & (arr[order] > 0.0), arr[order], 0.0)
    denom_r = np.add.reduceat(ps, starts)
    denom_row = np.repeat(denom_r, counts)
    unif_row = 1.0 / np.repeat(counts.astype(np.float64), counts)
    norm_sorted = np.where(denom_row > 0.0, ps / np.where(denom_row > 0.0, denom_row, 1.0), unif_row)

    out = np.empty(len(arr), dtype=np.float64)
    out[order] = norm_sorted
    return out


def _select_best_iter_temporal(train_df, feats, hgb_params, val_frac=0.15, random_state=0):
    """Select `best_iter` using a strictly temporal validation tail of `train_df` (never touches test)."""
    dt = pd.to_datetime(train_df["date"])
    uniq_days = np.sort(dt.unique())
    if len(uniq_days) < 4:
        return int((hgb_params or DEFAULT_HGB_PARAMS).get("max_iter", 300))

    split_idx = max(1, int(round(len(uniq_days) * (1.0 - float(val_frac)))))
    split_idx = min(split_idx, len(uniq_days) - 1)
    cutoff_dt = uniq_days[split_idx]

    tr_inner = train_df[dt < cutoff_dt]
    val_inner = train_df[dt >= cutoff_dt]
    if len(tr_inner) < 20 or len(val_inner) < 8 or (tr_inner["finish"] == 1).nunique() < 2:
        return int((hgb_params or DEFAULT_HGB_PARAMS).get("max_iter", 300))

    X_tr = tr_inner[feats].copy()
    X_val = val_inner[feats].copy()
    all_nan = [c for c in feats if X_tr[c].isna().all()]
    if all_nan:
        X_tr[all_nan] = 0.0
        X_val[all_nan] = 0.0

    inner_params = dict(DEFAULT_HGB_PARAMS)
    if hgb_params:
        inner_params.update(hgb_params)
    inner_params["early_stopping"] = False

    y_tr = (tr_inner["finish"] == 1).astype(int)
    est = make_v6_estimator(hgb_params=inner_params, random_state=random_state)
    est.fit(X_tr, y_tr)

    val_rids = val_inner["race_id"].to_numpy()
    val_win = (val_inner["finish"] == 1).to_numpy()
    if not np.any(val_win):
        return int(est.n_iter_)

    order, starts, _ends, counts = _group_races_contiguous(val_rids)
    win_sorted = val_win[order]
    if not np.any(win_sorted):
        return int(est.n_iter_)
    unif_sorted = 1.0 / np.repeat(counts.astype(np.float64), counts)

    best_iter = int(est.n_iter_)
    best_ll = np.inf
    for step_i, proba in enumerate(est.staged_predict_proba(X_val), start=1):
        if step_i < 20:
            continue
        p1 = proba[:, 1][order]
        ps = np.where(np.isfinite(p1) & (p1 > 0.0), p1, 0.0)
        denom_r = np.add.reduceat(ps, starts)
        denom_row = np.repeat(denom_r, counts)
        p_norm_s = np.where(denom_row > 0.0, ps / np.where(denom_row > 0.0, denom_row, 1.0), unif_sorted)
        ll = float(-np.log(np.clip(p_norm_s[win_sorted], 1e-6, None)).mean())
        if ll < best_ll:
            best_ll = ll
            best_iter = step_i
    return max(20, int(best_iter))


def fit_predict_v6(
    train_df,
    test_df,
    feats,
    hgb_params=None,
    seeds=(0,),
    temporal_val_frac=None,
):
    """Fit single-seed or multi-seed HGB on `train_df[feats]` and return race-normalized probs on `test_df`.

    For multi-seed (`len(seeds) > 1`), raw binary win probabilities across seeds are averaged first
    and then normalized within each `race_id` per spec ("olasılıkları ortala, sonra koşu içi normalize").
    """
    feats = list(feats)
    seeds = tuple(int(s) for s in seeds)
    if not seeds:
        raise ValueError("At least one random seed is required.")

    eff_params = dict(DEFAULT_HGB_PARAMS)
    if hgb_params:
        eff_params.update(hgb_params)

    if temporal_val_frac is not None and 0.0 < float(temporal_val_frac) < 0.5:
        eff_params["max_iter"] = _select_best_iter_temporal(
            train_df,
            feats,
            eff_params,
            val_frac=float(temporal_val_frac),
            random_state=seeds[0],
        )
        eff_params["early_stopping"] = False

    y_train = (train_df["finish"] == 1).astype(int)
    X_train = train_df[feats].copy()
    X_test = test_df[feats].copy()
    all_nan = [c for c in feats if X_train[c].isna().all()]
    if all_nan:
        X_train[all_nan] = 0.0
        X_test[all_nan] = 0.0

    raw_sum = np.zeros(len(test_df), dtype=np.float64)
    for s in seeds:
        est = make_v6_estimator(eff_params, random_state=s)
        est.fit(X_train, y_train)
        raw_sum += est.predict_proba(X_test)[:, 1]

    avg_raw = raw_sum / float(len(seeds))
    return race_normalize_probs(avg_raw, test_df["race_id"].to_numpy())


class RaceTemperatureCalibrator:
    """Conditional-logit race temperature calibrator: `p_i ∝ clip(p_base_i, clip_min)^gamma` (`gamma = 1/T`)."""

    def __init__(self, clip_min=1e-6, reg=1e-4):
        self.clip_min = float(clip_min)
        self.reg = float(reg)
        self.gamma = 1.0
        self.temperature = 1.0
        self.opt_result_ = None

    def fit(self, p_base, race_ids, winner_mask):
        """Fit `gamma = 1/T` on prior-year race-normalized probabilities by minimizing conditional race NLL."""
        lp = to_log_prob(p_base, self.clip_min)
        w_raw = np.asarray(winner_mask, dtype=np.float64)
        if not (len(lp) == len(w_raw) == len(race_ids)):
            raise ValueError("p_base, race_ids, and winner_mask must have equal length.")

        order, starts, _ends, counts = _group_races_contiguous(race_ids)
        if len(starts) == 0:
            self.gamma = 1.0
            self.temperature = 1.0
            return self

        xs = lp[order]
        ws = np.where(np.isfinite(w_raw[order]) & (w_raw[order] > 0.0), w_raw[order], 0.0)
        finite_cnt = np.add.reduceat(np.isfinite(xs).astype(np.int64), starts)
        w_race_sum = np.add.reduceat(ws, starts)
        valid_race = (finite_cnt == counts) & (counts >= 2) & (w_race_sum > 0.0)
        if not np.any(valid_race):
            self.gamma = 1.0
            self.temperature = 1.0
            return self

        if not np.all(valid_race):
            keep_row = np.repeat(valid_race, counts)
            xs = xs[keep_row]
            ws = ws[keep_row]
            counts = counts[valid_race]
            w_race_sum = w_race_sum[valid_race]
            starts = np.r_[0, np.cumsum(counts[:-1])]

        n_races = float(len(counts))

        def obj(gamma_val):
            g = float(gamma_val)
            z = g * xs
            m_r = np.maximum.reduceat(z, starts)
            exp_z = np.exp(z - np.repeat(m_r, counts))
            sum_exp = np.add.reduceat(exp_z, starts)
            log_denom = m_r + np.log(sum_exp)
            ll = np.sum(ws * z) - np.sum(w_race_sum * log_denom)
            pen = 0.5 * self.reg * (np.log(g) ** 2)
            return float(-ll / n_races + pen)

        res = minimize_scalar(obj, bounds=(0.25, 4.0), method="bounded")
        self.gamma = float(res.x) if np.isfinite(res.x) else 1.0
        self.temperature = float(1.0 / self.gamma)
        self.opt_result_ = res
        return self

    def predict(self, p_base, race_ids):
        """Apply fitted `gamma` and softmax-normalize probabilities within each race."""
        lp = to_log_prob(p_base, self.clip_min)
        if len(lp) != len(race_ids):
            raise ValueError("p_base and race_ids must have equal length.")
        if len(lp) == 0:
            return np.zeros(0, dtype=np.float64)

        order, starts, _ends, counts = _group_races_contiguous(race_ids)
        xs = lp[order]
        z = self.gamma * xs
        finite_row = np.isfinite(z)
        race_ok = np.add.reduceat(finite_row.astype(np.int64), starts) == counts

        z_safe = np.where(finite_row, z, 0.0)
        m_r = np.maximum.reduceat(z_safe, starts)
        exp_z = np.exp(z_safe - np.repeat(m_r, counts))
        sum_exp = np.add.reduceat(exp_z, starts)
        p_sorted = exp_z / np.repeat(sum_exp, counts)

        if not np.all(race_ok):
            ok_row = np.repeat(race_ok, counts)
            unif = 1.0 / np.repeat(counts.astype(np.float64), counts)
            p_sorted = np.where(ok_row, p_sorted, unif)

        out = np.empty(len(lp), dtype=np.float64)
        out[order] = p_sorted
        return out


class IsotonicRaceCalibrator:
    """Walk-forward isotonic probability calibrator with monotone lower-tail guard + race normalization."""

    def __init__(self, clip_min=1e-6, tail_floor_ratio=0.2):
        self.clip_min = float(clip_min)
        self.tail_floor_ratio = float(tail_floor_ratio)
        self.iso_ = None

    def fit(self, p_base, winner_mask):
        p_arr = np.asarray(p_base, dtype=np.float64)
        w_arr = np.asarray(winner_mask, dtype=np.float64)
        ok = np.isfinite(p_arr) & np.isfinite(w_arr)
        if np.sum(ok) < 10 or len(np.unique(w_arr[ok])) < 2:
            self.iso_ = None
            return self
        self.iso_ = IsotonicRegression(
            y_min=self.clip_min,
            y_max=1.0 - self.clip_min,
            out_of_bounds="clip",
        )
        self.iso_.fit(p_arr[ok], w_arr[ok])
        return self

    def predict(self, p_base, race_ids):
        p_arr = np.asarray(p_base, dtype=np.float64)
        if self.iso_ is None:
            return race_normalize_probs(p_arr, race_ids)
        p_safe = np.where(np.isfinite(p_arr) & (p_arr > 0.0), p_arr, self.clip_min)
        q = self.iso_.predict(p_safe)
        # Pointwise max of two monotone non-decreasing functions stays strictly monotone
        # while preventing 0-win empirical tail buckets from collapsing longshots to 1e-6.
        if self.tail_floor_ratio > 0.0:
            q = np.maximum(q, self.tail_floor_ratio * np.clip(p_safe, self.clip_min, 1.0))
        return race_normalize_probs(q, race_ids)


def evaluate_stage_b_gate(yearly_dll_map, race_dll_values, n_boot=2000, seed=0, min_neg_years=3):
    """Evaluate fixed Stage B (2022–2025) validation gate against E0.

    Gate requires BOTH:
      1. Race-paired bootstrap 95% CI upper bound < 0 (`bootstrap_mean_ci`), AND
      2. `ΔLL < 0` in at least `min_neg_years` (default 3 of 4) validation years.
    """
    arr = np.asarray(race_dll_values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    mean_dll, ci_lo, ci_hi = bootstrap_mean_ci(arr, n_boot=n_boot, seed=seed)
    valid_years = {int(k): float(v) for k, v in (yearly_dll_map or {}).items() if np.isfinite(v)}
    neg_years = sum(1 for v in valid_years.values() if v < 0.0)
    passed = bool(
        len(arr) > 0
        and np.isfinite(ci_hi)
        and (ci_hi < 0.0)
        and (neg_years >= int(min_neg_years))
    )
    return {
        "races": int(len(arr)),
        "mean_dll": float(mean_dll) if np.isfinite(mean_dll) else np.nan,
        "ci95_low": float(ci_lo) if np.isfinite(ci_lo) else np.nan,
        "ci95_high": float(ci_hi) if np.isfinite(ci_hi) else np.nan,
        "neg_years": int(neg_years),
        "total_years": int(len(valid_years)),
        "passed": passed,
    }


def compute_topk_coverage(df, p_col, ks=(1, 2, 3)):
    """Compute winner top-k inclusion rates (`top1`, `top2`, `top3`) on evaluation DataFrame."""
    sub = df[df[p_col].notna() & df["win"].notna()].copy()
    if sub.empty:
        res = {"races": 0}
        for k in ks:
            res[f"top{int(k)}"] = np.nan
        return res
    sub["_rk"] = sub.groupby("race_id", sort=False)[p_col].rank(ascending=False, method="first")
    winners = sub[sub["win"] == 1]
    n_w = len(winners)
    res = {"races": int(n_w)}
    for k in ks:
        res[f"top{int(k)}"] = float((winners["_rk"] <= int(k)).mean()) if n_w > 0 else np.nan
    return res


def _day_clustered_roi_ci(dates_arr, net_ret_arr, n_boot=1000, seed=0):
    """Compute `(roi, ci95_low, ci95_high)` via day-clustered bootstrap (fallback to bet-level if <5 days)."""
    n = len(net_ret_arr)
    if n == 0:
        return np.nan, np.nan, np.nan
    roi_mean = float(net_ret_arr.mean())
    if np.all(net_ret_arr == net_ret_arr[0]):
        return roi_mean, roi_mean, roi_mean

    if dates_arr is not None and len(dates_arr) == n:
        d_codes, uniq_d = pd.factorize(pd.DatetimeIndex(pd.to_datetime(dates_arr)).normalize(), sort=False)
        n_days = len(uniq_d)
        if n_days >= 5:
            day_cnt = np.bincount(d_codes, minlength=n_days).astype(np.float64)
            day_sum = np.bincount(d_codes, weights=net_ret_arr, minlength=n_days).astype(np.float64)
            rng = np.random.default_rng(seed)
            rois = np.empty(n_boot, dtype=np.float64)
            chunk = max(1, min(250, max(1, 2_000_000 // n_days)))
            pos = 0
            while pos < n_boot:
                m = min(chunk, n_boot - pos)
                idx = rng.integers(0, n_days, size=(m, n_days))
                c_b = day_cnt[idx].sum(axis=1)
                s_b = day_sum[idx].sum(axis=1)
                rois[pos : pos + m] = np.where(c_b > 0, s_b / np.maximum(c_b, 1.0), 0.0)
                pos += m
            return roi_mean, float(np.percentile(rois, 2.5)), float(np.percentile(rois, 97.5))

    return bootstrap_mean_ci(net_ret_arr, n_boot=n_boot, seed=seed)


def compute_ev_bet_stats(df, p_col, thresholds=(1.2, 1.35, 1.5), top_n_exclude=10, n_boot=1000, seed=0):
    """Compute flat 1 TL value-bet stats (`EV = p_model * ganyan >= thr`) including ex-top-10-win ROI."""
    valid = df[df[p_col].notna() & df["ganyan"].notna() & (df["ganyan"] > 0) & df["win"].notna()].copy()
    has_date = "date" in valid.columns

    rows = []
    for thr in thresholds:
        thr_f = float(thr)
        if valid.empty:
            rows.append(
                {
                    "ev_min": thr_f,
                    "bets": 0,
                    "win_rate": np.nan,
                    "roi": np.nan,
                    "ci95_low": np.nan,
                    "ci95_high": np.nan,
                    "bets_ex_top10": 0,
                    "roi_ex_top10": np.nan,
                    "ci95_ex_low": np.nan,
                    "ci95_ex_high": np.nan,
                }
            )
            continue

        p_arr = valid[p_col].to_numpy(dtype=np.float64)
        g_arr = valid["ganyan"].to_numpy(dtype=np.float64)
        w_arr = (valid["win"].to_numpy(dtype=np.float64) == 1.0).astype(np.float64)
        ev_arr = p_arr * g_arr

        sel = np.isfinite(ev_arr) & (ev_arr >= thr_f)
        cnt = int(np.sum(sel))
        if cnt == 0:
            rows.append(
                {
                    "ev_min": thr_f,
                    "bets": 0,
                    "win_rate": np.nan,
                    "roi": np.nan,
                    "ci95_low": np.nan,
                    "ci95_high": np.nan,
                    "bets_ex_top10": 0,
                    "roi_ex_top10": np.nan,
                    "ci95_ex_low": np.nan,
                    "ci95_ex_high": np.nan,
                }
            )
            continue

        sel_w = w_arr[sel]
        sel_g = g_arr[sel]
        sel_pay = sel_w * sel_g
        sel_net = sel_pay - 1.0
        sel_dates = valid.loc[sel, "date"].to_numpy() if has_date else None

        roi_m, ci_lo, ci_hi = _day_clustered_roi_ci(sel_dates, sel_net, n_boot=n_boot, seed=seed)

        win_indices = np.flatnonzero(sel_w > 0.0)
        if len(win_indices) > 0 and int(top_n_exclude) > 0:
            k_drop = min(int(top_n_exclude), len(win_indices))
            order_desc = np.argsort(-sel_pay[win_indices], kind="mergesort")
            drop_local = win_indices[order_desc[:k_drop]]
            keep_mask = np.ones(cnt, dtype=bool)
            keep_mask[drop_local] = False
        else:
            keep_mask = np.ones(cnt, dtype=bool)

        cnt_ex = int(np.sum(keep_mask))
        if cnt_ex > 0:
            ex_net = sel_net[keep_mask]
            ex_dates = sel_dates[keep_mask] if sel_dates is not None else None
            roi_ex, ex_lo, ex_hi = _day_clustered_roi_ci(ex_dates, ex_net, n_boot=n_boot, seed=seed)
        else:
            roi_ex, ex_lo, ex_hi = np.nan, np.nan, np.nan

        rows.append(
            {
                "ev_min": thr_f,
                "bets": cnt,
                "win_rate": float(sel_w.mean()),
                "roi": roi_m,
                "ci95_low": ci_lo,
                "ci95_high": ci_hi,
                "bets_ex_top10": cnt_ex,
                "roi_ex_top10": roi_ex,
                "ci95_ex_low": ex_lo,
                "ci95_ex_high": ex_hi,
            }
        )

    return pd.DataFrame(rows)


def get_v6_gamma(year, warn_fn=None, gamma_table=None):
    """Return walk-forward temperature `gamma` for calendar `year` from `V6_YEARLY_GAMMA`.

    If `year` is absent from the table, falls back to the latest year in the table and emits a warning.
    """
    tbl = V6_YEARLY_GAMMA if gamma_table is None else gamma_table
    if not tbl:
        raise ValueError("V6_YEARLY_GAMMA tablosu boş olamaz.")
    y_int = int(year)
    if y_int in tbl:
        return float(tbl[y_int])
    last_year = max(int(k) for k in tbl)
    gamma_val = float(tbl[last_year])
    msg = (
        f"UYARI: V6 sıcaklık (gamma) tablosunda {y_int} yılı bulunamadı; "
        f"en son yıl ({last_year}) gamma={gamma_val:.4f} kullanılıyor (yeniden kalibrasyon önerilir)."
    )
    if warn_fn is not None:
        warn_fn(msg)
    else:
        print(msg, flush=True)
    return gamma_val


def build_v6_cache_key(date_str, train_start, config=None):
    """Build deterministic daily cache key `(date, train_start, config_digest)` for trained V6 HGB bundle."""
    cfg = V6_CONFIG if config is None else config
    if cfg is None:
        raise ValueError("V6_CONFIG tanımlı değil (None).")
    return {
        "date": str(date_str)[:10],
        "train_start": str(train_start),
        "config_digest": config_digest(cfg),
    }


def _load_v6_bundle_cache(cache_path, expected_key):
    p_str = str(cache_path)
    if not os.path.exists(p_str):
        return None
    try:
        with open(p_str, "rb") as f:
            payload = pickle.load(f)
        if isinstance(payload, dict) and payload.get("cache_key") == expected_key:
            bundle = payload.get("bundle")
            if isinstance(bundle, dict) and bundle.get("estimators"):
                return bundle
    except Exception:
        return None
    return None


def _save_v6_bundle_cache(payload, cache_path):
    p_str = str(cache_path)
    parent = os.path.dirname(p_str)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp_p = f"{p_str}.tmp.{os.getpid()}"
    with open(tmp_p, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp_p, p_str)


def fit_v6_model_bundle(train_df, config=None):
    """Fit multi-seed HGB estimators specified by `config` (defaults to `V6_CONFIG`) on `train_df`."""
    cfg = V6_CONFIG if config is None else config
    if cfg is None:
        raise ValueError("V6_CONFIG tanımlı değil (None).")

    feats = list(cfg["feature_cols"])
    seeds = tuple(int(s) for s in cfg["seeds"])
    if not seeds:
        raise ValueError("En az bir tohum (seed) gerekli.")

    eff_params = dict(DEFAULT_HGB_PARAMS)
    if cfg.get("hgb_params"):
        eff_params.update(cfg["hgb_params"])

    temporal_val_frac = cfg.get("temporal_val_frac")
    if temporal_val_frac is not None and 0.0 < float(temporal_val_frac) < 0.5:
        eff_params["max_iter"] = _select_best_iter_temporal(
            train_df,
            feats,
            eff_params,
            val_frac=float(temporal_val_frac),
            random_state=seeds[0],
        )
        eff_params["early_stopping"] = False

    y_train = (train_df["finish"] == 1).astype(int)
    X_train = train_df[feats].copy()
    all_nan = [c for c in feats if X_train[c].isna().all()]
    if all_nan:
        X_train[all_nan] = 0.0

    estimators = []
    for s in seeds:
        est = make_v6_estimator(eff_params, random_state=s)
        est.fit(X_train, y_train)
        estimators.append(est)

    return {
        "estimators": estimators,
        "feature_cols": feats,
        "all_nan_cols": all_nan,
        "seeds": list(seeds),
        "config_digest": config_digest(cfg),
    }


def predict_v6_model_bundle(bundle, today_df, gamma=None, year=None, warn_fn=None):
    """Predict race-normalized, temperature-calibrated `p_win` on `today_df` from a fitted V6 bundle."""
    if len(today_df) == 0:
        return np.zeros(0, dtype=np.float64)

    feats = list(bundle["feature_cols"])
    X_test = today_df[feats].copy()
    all_nan = list(bundle.get("all_nan_cols") or ())
    if all_nan:
        X_test[all_nan] = 0.0

    estimators = bundle["estimators"]
    raw_sum = np.zeros(len(today_df), dtype=np.float64)
    for est in estimators:
        raw_sum += est.predict_proba(X_test)[:, 1]
    avg_raw = raw_sum / float(len(estimators))

    rids = today_df["race_id"].to_numpy()
    p_base = race_normalize_probs(avg_raw, rids)

    if gamma is not None:
        eff_gamma = float(gamma)
    else:
        if year is not None:
            eff_year = int(year)
        elif "date" in today_df.columns:
            eff_year = int(pd.Timestamp(today_df["date"].iloc[0]).year)
        else:
            eff_year = int(str(today_df["race_id"].iloc[0])[:4])
        eff_gamma = get_v6_gamma(eff_year, warn_fn=warn_fn)

    if eff_gamma == 1.0:
        return p_base

    cal = RaceTemperatureCalibrator(clip_min=1e-6)
    cal.gamma = eff_gamma
    cal.temperature = float(1.0 / eff_gamma)
    return cal.predict(p_base, rids)


def fit_predict_v6_live(
    train_df,
    today_df,
    config=None,
    gamma=None,
    year=None,
    cache_path=None,
    cache_meta=None,
    warn_fn=None,
):
    """Core live/backcheck V6 predictor: `train_df` + `today_df` -> 5-seed normalized + `gamma`-calibrated `p_win`.

    When `cache_path` is provided, loads/saves the fitted 5-HGB bundle keyed by
    `(date, train_start, config_digest)` and retrains automatically on any key mismatch.
    """
    cfg = V6_CONFIG if config is None else config
    if cfg is None:
        raise ValueError("V6_CONFIG tanımlı değil (None).")
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
        expected_key = build_v6_cache_key(date_val, train_start_val, config=cfg)
        bundle = _load_v6_bundle_cache(cache_path, expected_key)
        if bundle is None:
            bundle = fit_v6_model_bundle(train_df, config=cfg)
            try:
                _save_v6_bundle_cache({"cache_key": expected_key, "bundle": bundle}, cache_path)
            except OSError as exc:
                if warn_fn is not None:
                    warn_fn(f"UYARI: V6 model önbelleği yazılamadı ({cache_path}): {exc}")
    else:
        bundle = fit_v6_model_bundle(train_df, config=cfg)

    return predict_v6_model_bundle(bundle, today_df, gamma=gamma, year=year, warn_fn=warn_fn)


__all__ = [
    "CANDIDATE_VARIANTS",
    "DEFAULT_HGB_PARAMS",
    "DIAGNOSTIC_SPECS",
    "E1_E2_POOL",
    "E1_TO_E4_POOL",
    "E2_VARIANT_NAMES",
    "E4_VARIANT_NAMES",
    "FULL_HISTORY_START",
    "SHORT_HISTORY_START",
    "STAGE_A_YEARS",
    "STAGE_B_YEARS",
    "STAGE_C_YEARS",
    "V5_DB_HISTORY_START",
    "V6_CONFIG",
    "V6_LIVE_MODEL_VERSION",
    "V6_YEARLY_GAMMA",
    "VARIANT_SPECS",
    "IsotonicRaceCalibrator",
    "RaceTemperatureCalibrator",
    "bootstrap_mean_ci",
    "build_v6_cache_key",
    "compute_edge_buckets",
    "compute_ev_bet_stats",
    "compute_top1_roi",
    "compute_topk_coverage",
    "config_digest",
    "evaluate_stage_b_gate",
    "fit_predict_v6",
    "fit_predict_v6_live",
    "fit_v6_model_bundle",
    "get_v6_cols",
    "get_v6_gamma",
    "make_v6_estimator",
    "pin_v6_config_in_source",
    "predict_v6_model_bundle",
    "race_normalize_probs",
    "resolve_variant_config",
]

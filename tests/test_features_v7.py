"""Unit, hand-calculated value, and strict temporal leakage tests for Model v7 feature blocks."""
import numpy as np
import pandas as pd
import pytest

from ganyan.features import build_features
from ganyan.features_v5 import attach_v5
from ganyan.features_v7 import (
    ALL_EQUIP_TOKENS,
    C_COLS,
    J_COLS,
    P_COLS,
    T_COLS,
    V7_BLOCK_COLS,
    attach_C,
    attach_J,
    attach_P,
    attach_T,
    attach_v7,
    get_v7_cols,
    parse_cls_tier,
    parse_equip_tokens,
)
from ganyan.model_v6 import V6_CONFIG


def test_parse_equip_tokens():
    assert parse_equip_tokens("ALBAYRAĞIN AKKUŞU KG K DB") == frozenset({"KG", "K", "DB"})
    assert parse_equip_tokens("BOLD VOFİ KG DB SKG SK (Koşmaz)") == frozenset({"KG", "DB", "SKG", "SK"})
    assert parse_equip_tokens("OTTOMAN") == frozenset()
    assert parse_equip_tokens("GOLDEN BEST SK") == frozenset({"SK"})
    # Single-token horse name matching a code must not strip the entire name
    assert parse_equip_tokens("KG") == frozenset()
    # Non-code horse name words are preserved
    assert parse_equip_tokens("KIZIM MERYEM DB SKG SK") == frozenset({"DB", "SKG", "SK"})
    assert parse_equip_tokens(None) == frozenset()
    assert parse_equip_tokens("") == frozenset()
    assert "KG" in ALL_EQUIP_TOKENS and "DB" in ALL_EQUIP_TOKENS and "KUL" in ALL_EQUIP_TOKENS


def test_parse_cls_tier():
    assert parse_cls_tier("Maiden/DHÖW") == 0.0
    assert parse_cls_tier("SATIŞ 2") == 0.0
    assert parse_cls_tier("ŞARTLI 1/DHÖW") == 0.0
    assert parse_cls_tier("ŞARTLI 19") == 0.0
    assert parse_cls_tier("Handikap 14 /H2") == 1.0
    assert parse_cls_tier("Handikap 15/DHÖW /H1") == 1.0
    assert parse_cls_tier("ŞARTLI 3/Dişi") == 2.0
    assert parse_cls_tier("ŞARTLI 4") == 2.0
    assert parse_cls_tier("Handikap 16/DHÖW") == 2.0
    assert parse_cls_tier("ŞARTLI 5") == 3.0
    assert parse_cls_tier("Handikap 17 /H1") == 2.0
    assert parse_cls_tier("Handikap 21") == 3.0
    assert parse_cls_tier("KV-6/DHÖW") == 4.0
    assert parse_cls_tier("KV-8") == 4.0
    assert parse_cls_tier("KV-21") == 4.0
    assert parse_cls_tier("G 1") == 5.0
    assert parse_cls_tier("A 3") == 5.0
    assert np.isnan(parse_cls_tier(""))
    assert np.isnan(parse_cls_tier(None))
    assert np.isnan(parse_cls_tier("KADIN AMATÖR BİNİCİ"))


def test_get_v7_cols_and_block_defs():
    assert set(V7_BLOCK_COLS) == {"T", "C", "J", "P"}
    assert len(T_COLS) == 8
    assert len(C_COLS) == 6
    assert len(J_COLS) == 8
    assert len(P_COLS) == 10
    base = list(V6_CONFIG["feature_cols"])
    assert get_v7_cols(()) == base
    all_cols = get_v7_cols(("T", "C", "J", "P"))
    assert len(all_cols) == len(base) + 32
    assert len(all_cols) == len(set(all_cols))
    with pytest.raises(ValueError):
        get_v7_cols(("UNKNOWN",))


def test_block_exact_values():
    # Hand-crafted 5-race sequence around target horse H0 ("S0|D0|2021") and opponents H1, H2
    # Day 0: 2026-01-01 (D-40): H0 runs in Ankara 1200m Kum, Maiden, name_raw="H0", J_A, wt=55, elo_h=0.2, hp=30, fin=2
    # Day 1: 2026-01-11 (D-30): J_B rides H1 (win=1) in another race (exactly D-30 from 2026-02-10!)
    # Day 2: 2026-01-10 (D-31): J_B rides H2 (win=1) -> must be EXCLUDED from 30d window on 2026-02-10!
    # Day 3: 2026-01-20 (D-21): H0 adds KG ("H0 KG"), Handikap 16 (tier 2), Istanbul 1500m Sentetik, J_B AP, wt=57, fin=1
    # Day 4: 2026-02-01 (D-9):  H0 keeps KG ("H0 KG"), Handikap 16, Ankara 1200m Kum, J_B, wt=56, fin=1
    # Day 5: 2026-02-10 (D=0):  H0 removes KG ("H0 SK"), Maiden (tier 0), Ankara 1200m Kum, J_B, wt=54, fin=NaN
    rows = [
        # D-40 (2026-01-01)
        {"race_id": "2026-01-01_Ankara_1", "date": "2026-01-01", "city": "Ankara", "race_no": 1, "cls": "Maiden",
         "distance": 1200, "surface": "Kum", "horse_key": "H0", "name_raw": "AT0", "jockey": "J_A", "weight": 55.0,
         "hp": 30.0, "elo_h": 0.2, "elo_j": 0.1, "j_wr": 0.10, "sf": 10.0, "finish": 2, "field": 3, "fpct": 0.5, "scratched": 0},
        {"race_id": "2026-01-01_Ankara_1", "date": "2026-01-01", "city": "Ankara", "race_no": 1, "cls": "Maiden",
         "distance": 1200, "surface": "Kum", "horse_key": "H1", "name_raw": "AT1", "jockey": "J_C", "weight": 56.0,
         "hp": 40.0, "elo_h": 0.6, "elo_j": 0.2, "j_wr": 0.15, "sf": 12.0, "finish": 1, "field": 3, "fpct": 0.0, "scratched": 0},
        {"race_id": "2026-01-01_Ankara_1", "date": "2026-01-01", "city": "Ankara", "race_no": 1, "cls": "Maiden",
         "distance": 1200, "surface": "Kum", "horse_key": "H2", "name_raw": "AT2", "jockey": "J_D", "weight": 54.0,
         "hp": 50.0, "elo_h": 0.8, "elo_j": 0.3, "j_wr": 0.20, "sf": 8.0, "finish": 3, "field": 3, "fpct": 1.0, "scratched": 0},
        # D-31 (2026-01-10) - outside 30d window for 2026-02-10
        {"race_id": "2026-01-10_Ankara_1", "date": "2026-01-10", "city": "Ankara", "race_no": 1, "cls": "Handikap 15",
         "distance": 1400, "surface": "Kum", "horse_key": "H1", "name_raw": "AT1", "jockey": "J_B", "weight": 55.0,
         "hp": 45.0, "elo_h": 0.5, "elo_j": 0.4, "j_wr": 0.20, "sf": 5.0, "finish": 1, "field": 2, "fpct": 0.0, "scratched": 0},
        {"race_id": "2026-01-10_Ankara_1", "date": "2026-01-10", "city": "Ankara", "race_no": 1, "cls": "Handikap 15",
         "distance": 1400, "surface": "Kum", "horse_key": "H2", "name_raw": "AT2", "jockey": "J_C", "weight": 55.0,
         "hp": 45.0, "elo_h": 0.5, "elo_j": 0.2, "j_wr": 0.15, "sf": 3.0, "finish": 2, "field": 2, "fpct": 1.0, "scratched": 0},
        # D-30 (2026-01-11) - ON boundary [D-30, D) for 2026-02-10 -> must be INCLUDED
        {"race_id": "2026-01-11_Ankara_1", "date": "2026-01-11", "city": "Ankara", "race_no": 1, "cls": "Handikap 15",
         "distance": 1400, "surface": "Kum", "horse_key": "H1", "name_raw": "AT1", "jockey": "J_B", "weight": 55.0,
         "hp": 45.0, "elo_h": 0.5, "elo_j": 0.4, "j_wr": 0.20, "sf": 5.0, "finish": 1, "field": 2, "fpct": 0.0, "scratched": 0},
        {"race_id": "2026-01-11_Ankara_1", "date": "2026-01-11", "city": "Ankara", "race_no": 1, "cls": "Handikap 15",
         "distance": 1400, "surface": "Kum", "horse_key": "H2", "name_raw": "AT2", "jockey": "J_C", "weight": 55.0,
         "hp": 45.0, "elo_h": 0.5, "elo_j": 0.2, "j_wr": 0.15, "sf": 3.0, "finish": 2, "field": 2, "fpct": 1.0, "scratched": 0},
        # D-21 (2026-01-20)
        {"race_id": "2026-01-20_İstanbul_1", "date": "2026-01-20", "city": "İstanbul", "race_no": 1, "cls": "Handikap 16",
         "distance": 1500, "surface": "Sentetik", "horse_key": "H0", "name_raw": "AT0 KG", "jockey": "J_B AP", "weight": 57.0,
         "hp": 50.0, "elo_h": 0.3, "elo_j": 0.5, "j_wr": 0.25, "sf": 15.0, "finish": 1, "field": 2, "fpct": 0.0, "scratched": 0},
        {"race_id": "2026-01-20_İstanbul_1", "date": "2026-01-20", "city": "İstanbul", "race_no": 1, "cls": "Handikap 16",
         "distance": 1500, "surface": "Sentetik", "horse_key": "H1", "name_raw": "AT1", "jockey": "J_C", "weight": 55.0,
         "hp": 60.0, "elo_h": 1.0, "elo_j": 0.2, "j_wr": 0.15, "sf": 10.0, "finish": 2, "field": 2, "fpct": 1.0, "scratched": 0},
        # D-9 (2026-02-01)
        {"race_id": "2026-02-01_Ankara_1", "date": "2026-02-01", "city": "Ankara", "race_no": 1, "cls": "Handikap 16",
         "distance": 1200, "surface": "Kum", "horse_key": "H0", "name_raw": "AT0 KG", "jockey": "J_B", "weight": 56.0,
         "hp": 55.0, "elo_h": 0.5, "elo_j": 0.6, "j_wr": 0.30, "sf": 18.0, "finish": 1, "field": 2, "fpct": 0.0, "scratched": 0},
        {"race_id": "2026-02-01_Ankara_1", "date": "2026-02-01", "city": "Ankara", "race_no": 1, "cls": "Handikap 16",
         "distance": 1200, "surface": "Kum", "horse_key": "H2", "name_raw": "AT2", "jockey": "J_D", "weight": 55.0,
         "hp": 70.0, "elo_h": 1.4, "elo_j": 0.3, "j_wr": 0.20, "sf": 11.0, "finish": 2, "field": 2, "fpct": 1.0, "scratched": 0},
        # D=0 (2026-02-10)
        {"race_id": "2026-02-10_Ankara_1", "date": "2026-02-10", "city": "Ankara", "race_no": 1, "cls": "Maiden",
         "distance": 1200, "surface": "Kum", "horse_key": "H0", "name_raw": "AT0 SK", "jockey": "J_B", "weight": 54.0,
         "hp": 30.0, "elo_h": 0.7, "elo_j": 0.6, "j_wr": 0.32, "sf": np.nan, "finish": np.nan, "field": 2, "fpct": np.nan, "scratched": 0},
        {"race_id": "2026-02-10_Ankara_1", "date": "2026-02-10", "city": "Ankara", "race_no": 1, "cls": "Maiden",
         "distance": 1200, "surface": "Kum", "horse_key": "H1", "name_raw": "AT1", "jockey": "J_C", "weight": 55.0,
         "hp": 32.0, "elo_h": 0.2, "elo_j": 0.2, "j_wr": 0.14, "sf": np.nan, "finish": np.nan, "field": 2, "fpct": np.nan, "scratched": 0},
    ]
    df = pd.DataFrame(rows)
    res = attach_v7(df, blocks=("T", "C", "J", "P"))
    h0 = res[res["horse_key"] == "H0"].sort_values("date").reset_index(drop=True)

    # Block T checks for H0: debut(2026-01-01), 2nd(+KG), 3rd(keep KG), 4th(-KG +SK)
    assert h0.loc[0, "eq_has_kg"] == 0.0
    assert np.isnan(h0.loc[0, "eq_kg_chg"])
    assert np.isnan(h0.loc[0, "eq_first_kg_or_db"])
    assert np.isnan(h0.loc[0, "eq_any_chg"])

    assert h0.loc[1, "eq_has_kg"] == 1.0
    assert h0.loc[1, "eq_kg_chg"] == pytest.approx(1.0)
    assert h0.loc[1, "eq_first_kg_or_db"] == pytest.approx(1.0)
    assert h0.loc[1, "eq_any_chg"] == pytest.approx(1.0)

    assert h0.loc[2, "eq_kg_chg"] == pytest.approx(0.0)
    assert h0.loc[2, "eq_first_kg_or_db"] == pytest.approx(0.0)
    assert h0.loc[2, "eq_any_chg"] == pytest.approx(0.0)

    assert h0.loc[3, "eq_has_kg"] == 0.0
    assert h0.loc[3, "eq_kg_chg"] == pytest.approx(-1.0)
    assert h0.loc[3, "eq_first_kg_or_db"] == pytest.approx(0.0)
    assert h0.loc[3, "eq_any_chg"] == pytest.approx(1.0)

    # Block C checks on D=0 (2026-02-10): prev cls was tier 2 -> now tier 0 -> chg = -2
    # Opp Elo on D=0 is H1=0.2; prev race opp was H2=1.4 -> opp_elo_chg = -1.2
    # Prev3 opp Elo mean = mean(0.7, 1.0, 1.4) = 3.1/3 -> opp_elo_chg_m3 = 0.2 - 3.1/3
    # Opp HP on D=0 is H1=32; prev opp HP was 70 -> opp_hp_chg = -38.0
    assert h0.loc[3, "cls_tier"] == pytest.approx(0.0)
    assert h0.loc[3, "cls_tier_chg"] == pytest.approx(-2.0)
    assert h0.loc[3, "opp_elo_chg"] == pytest.approx(0.2 - 1.4)
    assert h0.loc[3, "opp_elo_chg_m3"] == pytest.approx(0.2 - (0.7 + 1.0 + 1.4) / 3.0)
    assert h0.loc[3, "opp_hp_chg"] == pytest.approx(32.0 - 70.0)

    # Block J checks on D=0 (2026-02-10): J_B AP (2026-01-20) and J_B (2026-02-01) normalize identically!
    assert h0.loc[1, "j_elo_chg"] == pytest.approx(0.5 - 0.1)
    assert h0.loc[1, "j_wr_chg"] == pytest.approx(0.25 - 0.10)
    assert h0.loc[1, "j_same_prev"] == pytest.approx(0.0)
    assert h0.loc[2, "j_same_prev"] == pytest.approx(1.0)  # J_B == J_B AP!
    assert h0.loc[3, "j_same_prev"] == pytest.approx(1.0)
    assert h0.loc[3, "hj_n"] == pytest.approx(2.0)
    assert h0.loc[3, "hj_wr"] == pytest.approx((2.0 + 0.3) / (2.0 + 3.0))
    assert h0.loc[3, "hj_fpct"] == pytest.approx((0.0 + 1.5) / (2.0 + 3.0))
    assert h0.loc[3, "h_weight_chg"] == pytest.approx(54.0 - 56.0)
    # 30-day window [2026-01-11, 2026-02-10): J_B rode 2026-01-11 (w), 2026-01-20 (w), 2026-02-01 (w) -> 3 starts, 3 wins! (2026-01-10 excluded!)
    assert h0.loc[3, "j_wr_30d"] == pytest.approx((3.0 + 1.0) / (3.0 + 10.0))

    # Block P checks on D=0 (2026-02-10, Ankara 1200m Kum):
    # H0 prior Kum starts: D-40 (fin=2, fpct=0.5, sf=10), D-9 (fin=1, fpct=0.0, sf=18) -> 2 starts, 2 top3, sf_best=18
    # H0 all prior fpct: D-40 (0.5), D-21 (0.0), D-9 (0.0) -> (0.5+1.5)/(3+3) = 2/6
    # H0 Kum fpct: (0.5+1.5)/(2+3) = 2/5 -> delta = 2/5 - 2/6
    assert h0.loc[3, "h_surf_n"] == pytest.approx(2.0)
    assert h0.loc[3, "h_surf_t3r"] == pytest.approx((2.0 + 0.9) / (2.0 + 3.0))
    assert h0.loc[3, "h_surf_fpct"] == pytest.approx((0.5 + 1.5) / (2.0 + 3.0))
    assert h0.loc[3, "h_surf_sf_best"] == pytest.approx(18.0)
    assert h0.loc[3, "h_surf_fpct_delta"] == pytest.approx((2.0 / 5.0) - (2.0 / 6.0))
    assert h0.loc[3, "h_dist_n"] == pytest.approx(2.0)
    assert h0.loc[3, "h_dist_fpct"] == pytest.approx(2.0 / 5.0)
    assert h0.loc[3, "h_dist_sf_best"] == pytest.approx(18.0)
    assert h0.loc[3, "h_city_fpct"] == pytest.approx(2.0 / 5.0)


def _make_synthetic_v7_dataset():
    dates = [
        ("2025-02-10", "Ankara", "Maiden", 1200, "Kum"),
        ("2025-05-15", "İstanbul", "Handikap 15", 1500, "Sentetik"),
        ("2025-08-20", "Ankara", "ŞARTLI 4", 1400, "Çim"),
        ("2026-05-01", "İzmir", "KV-6", 1600, "Kum"),
        ("2026-05-25", "Ankara", "Handikap 16", 1300, "Kum"),
        ("2026-06-14", "Ankara", "Handikap 14", 1200, "Kum"),  # Target day D
        ("2026-06-22", "İstanbul", "G 1", 2000, "Çim"),       # Future > D
        ("2026-07-05", "Adana", "ŞARTLI 5", 1900, "Kum"),     # Future > D
    ]
    horses = [f"SIRE_{i}|DAM_{i}|2021" for i in range(16)]
    jockeys = ["J_0", "J_0 AP", "J_1", "J_2", "J_3 AP"]
    eq_cycle = ["", " KG", " KG DB", " K", " DB SK"]

    rng = np.random.default_rng(707)
    rows = []
    for d_i, (d, city, cls_s, dist, surf) in enumerate(dates):
        for r_no in (1, 2):
            rid = f"{d}_{city}_{r_no}"
            sub = horses[:8] if r_no == 1 else horses[8:]
            fins = rng.permutation(np.arange(1, 9))
            for pos, (hk, fin) in enumerate(zip(sub, fins)):
                idx = int(hk.split("_")[1].split("|")[0])
                eq_tok = eq_cycle[(idx + d_i) % len(eq_cycle)]
                rows.append({
                    "race_id": rid,
                    "date": d,
                    "city": city,
                    "race_no": r_no,
                    "prog_no": pos + 1,
                    "horse_key": hk,
                    "name": f"AT {idx}",
                    "name_raw": f"AT {idx}{eq_tok}",
                    "age": 4,
                    "sex": "d" if idx % 2 == 0 else "e",
                    "sire": f"SIRE_{idx}",
                    "dam": f"DAM_{idx}",
                    "weight": 54.0 + ((idx + d_i) % 6) * 0.5,
                    "jockey": jockeys[(idx + d_i) % len(jockeys)],
                    "owner": f"OWN_{idx % 4}",
                    "trainer": f"TRN_{idx % 3}",
                    "gate": pos + 1,
                    "hp": 40.0 + idx * 2.0 + d_i,
                    "cls": cls_s,
                    "breed": "Ingiliz" if r_no == 1 else "Arap",
                    "distance": dist if r_no == 1 else dist + 200,
                    "surface": surf,
                    "son6": "K1K2",
                    "kgs": 20,
                    "s20": 17,
                    "best_time_s": 85.0,
                    "finish": int(fin),
                    "time_s": 74.0 + fin * 0.4 + d_i * 0.1,
                    "ganyan": 2.0 + fin * 1.3,
                    "agf_close": 40.0 / fin,
                    "agf_close_rank": int(fin),
                    "scratched": 0,
                })
    return pd.DataFrame(rows)


@pytest.mark.parametrize("block", ["T", "C", "J", "P"])
def test_strict_temporal_leakage(block):
    runners_df = _make_synthetic_v7_dataset()
    target_day = pd.Timestamp("2026-06-14")
    ref_end = "2026-01-01"

    full_base = attach_v5(build_features(runners_df, ref_end=ref_end), {}, blocks=("S", "R"))
    full_v7 = attach_v7(full_base, blocks=(block,))
    day_full = (
        full_v7[full_v7["date"] == target_day]
        .sort_values(["race_id", "horse_key"])
        .reset_index(drop=True)
    )

    r_dt = pd.to_datetime(runners_df["date"])
    trunc_df = runners_df[r_dt <= target_day].copy()
    mask_d = pd.to_datetime(trunc_df["date"]) == target_day
    for col in ("finish", "time_s", "ganyan", "agf_close", "agf_close_rank"):
        trunc_df.loc[mask_d, col] = np.nan
    trunc_df = trunc_df.sample(frac=1.0, random_state=42).reset_index(drop=True)

    trunc_base = attach_v5(build_features(trunc_df, ref_end=ref_end), {}, blocks=("S", "R"))
    trunc_v7 = attach_v7(trunc_base, blocks=(block,))
    day_trunc = (
        trunc_v7[trunc_v7["date"] == target_day]
        .sort_values(["race_id", "horse_key"])
        .reset_index(drop=True)
    )

    assert len(day_full) == len(day_trunc) == 16
    for col in V7_BLOCK_COLS[block]:
        np.testing.assert_allclose(
            day_full[col].to_numpy(dtype=np.float64),
            day_trunc[col].to_numpy(dtype=np.float64),
            rtol=1e-12,
            atol=1e-12,
            equal_nan=True,
            err_msg=f"Block {block} column '{col}' leaked future or same-day info!",
        )


def test_sameday_multi_entry_isolation():
    runners_df = _make_synthetic_v7_dataset()
    target_day = "2026-06-14"
    # Force shared horse AND shared jockey between race 1 and race 2 on day D
    mod_a = runners_df.copy()
    mask_d_r2 = (mod_a["date"] == target_day) & (mod_a["race_no"] == 2)
    first_r2_idx = mod_a.index[mask_d_r2][0]
    shared_hk = mod_a.loc[mod_a["date"] == target_day, "horse_key"].iloc[0]
    mod_a.loc[first_r2_idx, "horse_key"] = shared_hk
    mod_a.loc[mod_a["date"] == target_day, "jockey"] = np.where(
        mod_a.loc[mod_a["date"] == target_day, "prog_no"] <= 4, "J_0", "J_1"
    )

    mod_b = mod_a.copy()
    mask_d_r1 = (mod_b["date"] == target_day) & (mod_b["race_no"] == 1)
    mod_b.loc[mask_d_r1, "finish"] = 9 - mod_b.loc[mask_d_r1, "finish"]

    mod_c = mod_a.copy()
    mod_c.loc[mask_d_r1, "finish"] = np.nan

    res_a = attach_v7(attach_v5(build_features(mod_a, ref_end="2026-01-01"), {}, blocks=("S", "R")))
    res_b = attach_v7(attach_v5(build_features(mod_b, ref_end="2026-01-01"), {}, blocks=("S", "R")))
    res_c = attach_v7(attach_v5(build_features(mod_c, ref_end="2026-01-01"), {}, blocks=("S", "R")))

    r2_a = res_a[(res_a["date"] == pd.Timestamp(target_day)) & (res_a["race_no"] == 2)].sort_values("prog_no").reset_index(drop=True)
    r2_b = res_b[(res_b["date"] == pd.Timestamp(target_day)) & (res_b["race_no"] == 2)].sort_values("prog_no").reset_index(drop=True)
    r2_c = res_c[(res_c["date"] == pd.Timestamp(target_day)) & (res_c["race_no"] == 2)].sort_values("prog_no").reset_index(drop=True)

    for blk in ("T", "C", "J", "P"):
        for col in V7_BLOCK_COLS[blk]:
            np.testing.assert_allclose(
                r2_a[col].to_numpy(dtype=np.float64),
                r2_b[col].to_numpy(dtype=np.float64),
                rtol=1e-12,
                atol=1e-12,
                equal_nan=True,
                err_msg=f"Same-day race 1 inverted finish leaked into race 2 '{col}'!",
            )
            np.testing.assert_allclose(
                r2_a[col].to_numpy(dtype=np.float64),
                r2_c[col].to_numpy(dtype=np.float64),
                rtol=1e-12,
                atol=1e-12,
                equal_nan=True,
                err_msg=f"Same-day race 1 NaN finish leaked into race 2 '{col}'!",
            )


def test_empty_and_missing_cols():
    empty_df = pd.DataFrame(columns=["race_id", "date", "city", "race_no", "horse_key"])
    res_empty = attach_v7(empty_df)
    for blk in ("T", "C", "J", "P"):
        for col in V7_BLOCK_COLS[blk]:
            assert col in res_empty.columns
            assert len(res_empty[col]) == 0

    minimal_df = pd.DataFrame([
        {"race_id": "2026-01-01_Ankara_1", "date": "2026-01-01", "city": None, "race_no": 1, "horse_key": "H0"},
        {"race_id": "2026-01-01_Ankara_1", "date": "2026-01-01", "city": None, "race_no": 1, "horse_key": "H1"},
    ])
    res_min = attach_v7(minimal_df)
    for blk in ("T", "C", "J", "P"):
        for col in V7_BLOCK_COLS[blk]:
            assert col in res_min.columns
            assert res_min[col].isna().all()

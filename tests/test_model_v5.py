"""Unit and end-to-end tests for Model v5 (`features_v5`, `model_v5`, `run_v5_backtest`)."""
import numpy as np
import pandas as pd
import pytest

from ganyan.db import init_db, upsert_results
from ganyan.features_v5 import BLOCK_COLS, attach_G, attach_R, load_v5_tables
from ganyan.model_v5 import (
    BASE_COLS,
    BenterCombiner,
    PROGRAM_COLS,
    compute_edge_buckets,
    compute_top1_roi,
    to_log_prob,
)
from scripts.run_v5_backtest import run_v5_backtest


def test_base_and_block_col_definitions():
    for pcol in PROGRAM_COLS:
        assert pcol not in BASE_COLS
    assert set(BLOCK_COLS.keys()) == {"S", "G", "R"}
    assert len(BLOCK_COLS["S"]) == 7
    assert len(BLOCK_COLS["G"]) == 11
    assert len(BLOCK_COLS["R"]) == 5


def test_benter_combiner_recovers_known_weights():
    rng = np.random.default_rng(2026)
    n_races = 4000
    field = 8

    u_fund = rng.normal(0.0, 1.0, size=(n_races, field))
    u_agf = rng.normal(0.0, 1.0, size=(n_races, field))

    ef = np.exp(u_fund - u_fund.max(axis=1, keepdims=True))
    p_fund = ef / ef.sum(axis=1, keepdims=True)

    ea = np.exp(u_agf - u_agf.max(axis=1, keepdims=True))
    p_agf = ea / ea.sum(axis=1, keepdims=True)

    lp_fund = to_log_prob(p_fund, 1e-6)
    lp_agf = to_log_prob(p_agf, 1e-6)

    true_a, true_b = 0.7, 0.4
    logits = true_a * lp_fund + true_b * lp_agf
    ez = np.exp(logits - logits.max(axis=1, keepdims=True))
    p_true = ez / ez.sum(axis=1, keepdims=True)

    cdf = np.cumsum(p_true, axis=1)
    cdf[:, -1] = 1.0
    draws = rng.random((n_races, 1))
    win_col = (draws > cdf).sum(axis=1)
    winners = np.zeros((n_races, field), dtype=bool)
    winners[np.arange(n_races), win_col] = True

    race_ids = np.repeat([f"R_{i}" for i in range(n_races)], field)

    comb = BenterCombiner(clip_min=1e-6).fit(
        lp_fund.ravel(),
        lp_agf.ravel(),
        race_ids,
        winners.ravel(),
    )
    assert abs(comb.a - true_a) <= 0.1
    assert abs(comb.b - true_b) <= 0.1

    p_hat = comb.predict(lp_fund.ravel(), lp_agf.ravel(), race_ids)
    assert p_hat.shape == (n_races * field,)
    assert np.all(p_hat > 0.0)
    assert np.allclose(p_hat.reshape(n_races, field).sum(axis=1), 1.0)


def test_attach_G_hand_calculated_boundaries_14_30_60():
    # Race day D = 2026-06-30:
    #   D - 14 = 2026-06-16
    #   D - 30 = 2026-05-31
    #   D - 60 = 2026-05-01
    #   D - 61 = 2026-04-30 (excluded: >60 days old)
    df = pd.DataFrame(
        [
            {"race_id": "2026-06-30_Ankara_1", "date": "2026-06-30", "city": "Ankara", "race_no": 1, "horse_key": "H_A"},
            {"race_id": "2026-06-30_Ankara_1", "date": "2026-06-30", "city": "Ankara", "race_no": 1, "horse_key": "H_60"},
            {"race_id": "2026-06-30_Ankara_1", "date": "2026-06-30", "city": "Ankara", "race_no": 1, "horse_key": "H_61"},
            {"race_id": "2026-06-30_Ankara_1", "date": "2026-06-30", "city": "Ankara", "race_no": 1, "horse_key": "H_NONE"},
        ]
    )

    workouts_rows = [
        # H_A has 3 workouts at exact boundaries D-60, D-30, D-14
        {
            "source": "liderform",
            "horse_key": "H_A",
            "date": "2026-05-01",
            "city": "Ankara",
            "kind": "SPRINT",
            "d400": 23.8,
            "d600": 36.5,
            "d800": 49.5,
            "effort": "ALLOUT",
        },
        {
            "source": "liderform",
            "horse_key": "H_A",
            "date": "2026-05-31",
            "city": "Ankara",
            "kind": "GALOP",
            "d400": 24.4,
            "d600": 37.2,
            "d800": 50.8,
            "effort": "ALLOUT",
        },
        {
            "source": "liderform",
            "horse_key": "H_A",
            "date": "2026-06-16",
            "city": "Ankara",
            "kind": "SPRINT",
            "d400": 25.0,
            "d600": np.nan,
            "d800": 51.6,
            "effort": "CANTER",
        },
        # H_60 only has a workout at exact D-60 (and <5 workouts on 2026-05-01 -> rel is NaN)
        {
            "source": "liderform",
            "horse_key": "H_60",
            "date": "2026-05-01",
            "city": "Ankara",
            "kind": "SPRINT",
            "d400": 24.6,
            "d600": 38.0,
            "d800": 52.0,
            "effort": "ALLOUT",
        },
        # H_61 only has a workout at D-61 (must not count)
        {
            "source": "liderform",
            "horse_key": "H_61",
            "date": "2026-04-30",
            "city": "Ankara",
            "kind": "SPRINT",
            "d400": 24.0,
            "d600": 36.0,
            "d800": 50.0,
            "effort": "ALLOUT",
        },
    ]
    # Add 4 more workouts on (2026-06-16, Ankara) so total d400 count = 5 -> median([24.0, 24.2, 24.4, 25.0, 26.0]) = 24.4
    for i, d4 in enumerate([24.0, 24.2, 24.4, 26.0]):
        workouts_rows.append(
            {
                "source": "liderform",
                "horse_key": f"BG_{i}",
                "date": "2026-06-16",
                "city": "Ankara",
                "kind": "GALOP",
                "d400": d4,
                "d600": 37.0,
                "d800": 51.0,
                "effort": "CANTER",
            }
        )

    out = attach_G(df, pd.DataFrame(workouts_rows)).set_index("horse_key")

    ha = out.loc["H_A"]
    assert ha["g_n14"] == 1.0
    assert ha["g_n30"] == 2.0
    assert ha["g_days_last"] == 14.0
    assert ha["g_last_d400"] == pytest.approx(25.0)
    assert np.isnan(ha["g_last_d600"])
    assert ha["g_last_d800"] == pytest.approx(51.6)
    assert ha["g_best_d400_30"] == pytest.approx(24.4)
    assert ha["g_best_d800_30"] == pytest.approx(50.8)
    assert ha["g_allout_30"] == 1.0
    assert ha["g_sprint_30"] == 1.0
    assert ha["g_last_d400_rel"] == pytest.approx(0.6)

    h60 = out.loc["H_60"]
    assert h60["g_n14"] == 0.0
    assert h60["g_n30"] == 0.0
    assert h60["g_days_last"] == 60.0
    assert h60["g_last_d400"] == pytest.approx(24.6)
    assert np.isnan(h60["g_best_d400_30"])
    assert np.isnan(h60["g_last_d400_rel"])

    for hk in ("H_61", "H_NONE"):
        row = out.loc[hk]
        assert row["g_n14"] == 0.0
        assert row["g_n30"] == 0.0
        assert row["g_allout_30"] == 0.0
        assert row["g_sprint_30"] == 0.0
        assert np.isnan(row["g_days_last"])
        assert np.isnan(row["g_last_d400"])


def test_attach_R_two_races_hand_calculated():
    df = pd.DataFrame(
        [
            # Race 1 (2026-01-01): 3 active runners + 1 scratched runner; T1 trains both H1 and H2
            {
                "race_id": "2026-01-01_Ankara_1",
                "date": "2026-01-01",
                "city": "Ankara",
                "race_no": 1,
                "horse_key": "H1",
                "jockey": "J1",
                "trainer": "T1",
                "finish": 1,
                "scratched": 0,
            },
            {
                "race_id": "2026-01-01_Ankara_1",
                "date": "2026-01-01",
                "city": "Ankara",
                "race_no": 1,
                "horse_key": "H2",
                "jockey": "J2",
                "trainer": "T1",
                "finish": 2,
                "scratched": 0,
            },
            {
                "race_id": "2026-01-01_Ankara_1",
                "date": "2026-01-01",
                "city": "Ankara",
                "race_no": 1,
                "horse_key": "H3",
                "jockey": "J3",
                "trainer": "T2",
                "finish": 3,
                "scratched": 0,
            },
            {
                "race_id": "2026-01-01_Ankara_1",
                "date": "2026-01-01",
                "city": "Ankara",
                "race_no": 1,
                "horse_key": "H4",
                "jockey": "J4",
                "trainer": "T2",
                "finish": np.nan,
                "scratched": 1,
            },
            # Race 2 (2026-01-10): H1, H2, H3 meet again
            {
                "race_id": "2026-01-10_Ankara_1",
                "date": "2026-01-10",
                "city": "Ankara",
                "race_no": 1,
                "horse_key": "H1",
                "jockey": "J1",
                "trainer": "T1",
                "finish": 2,
                "scratched": 0,
            },
            {
                "race_id": "2026-01-10_Ankara_1",
                "date": "2026-01-10",
                "city": "Ankara",
                "race_no": 1,
                "horse_key": "H2",
                "jockey": "J2",
                "trainer": "T1",
                "finish": 1,
                "scratched": 0,
            },
            {
                "race_id": "2026-01-10_Ankara_1",
                "date": "2026-01-10",
                "city": "Ankara",
                "race_no": 1,
                "horse_key": "H3",
                "jockey": "J3",
                "trainer": "T2",
                "finish": 3,
                "scratched": 0,
            },
        ]
    )

    out = attach_R(df)
    r1 = out[(out["race_id"] == "2026-01-01_Ankara_1") & (out["scratched"] == 0)].set_index("horse_key")
    assert np.allclose(r1["elo_h"], [0.0, 0.0, 0.0])
    assert np.allclose(r1["elo_j"], [0.0, 0.0, 0.0])
    assert np.allclose(r1["elo_t"], [0.0, 0.0, 0.0])
    assert np.allclose(r1["elo_h_rel"], [0.0, 0.0, 0.0])
    assert np.allclose(r1["elo_h_rk"], [2.0 / 3.0, 2.0 / 3.0, 2.0 / 3.0])

    # After Race 1 (3 active runners -> p = 1/3 each):
    #   elo_h: H1 = +0.25*(2/3) = 1/6, H2 = -1/12, H3 = -1/12
    #   elo_j: J1 = +0.05*(2/3) = 1/30, J2 = -1/60, J3 = -1/60
    #   elo_t: T1 = +0.04*((1-1/3)+(0-1/3)) = +0.04/3, T2 = -0.04/3
    r2 = out[out["race_id"] == "2026-01-10_Ankara_1"].set_index("horse_key")
    assert r2.loc["H1", "elo_h"] == pytest.approx(1.0 / 6.0)
    assert r2.loc["H2", "elo_h"] == pytest.approx(-1.0 / 12.0)
    assert r2.loc["H3", "elo_h"] == pytest.approx(-1.0 / 12.0)
    assert r2.loc["H1", "elo_j"] == pytest.approx(1.0 / 30.0)
    assert r2.loc["H2", "elo_j"] == pytest.approx(-1.0 / 60.0)
    assert r2.loc["H1", "elo_t"] == pytest.approx(0.04 / 3.0)
    assert r2.loc["H2", "elo_t"] == pytest.approx(0.04 / 3.0)
    assert r2.loc["H3", "elo_t"] == pytest.approx(-0.04 / 3.0)
    assert r2.loc["H1", "elo_h_rel"] == pytest.approx(1.0 / 6.0)
    assert r2.loc["H2", "elo_h_rel"] == pytest.approx(-1.0 / 12.0)
    assert r2.loc["H1", "elo_h_rk"] == pytest.approx(1.0 / 3.0)
    assert r2.loc["H2", "elo_h_rk"] == pytest.approx(5.0 / 6.0)
    assert r2.loc["H3", "elo_h_rk"] == pytest.approx(5.0 / 6.0)


def test_edge_buckets_and_top1_roi_hand_calculated():
    # Two 2-horse races with ganyan = 2.0 on all runners -> inv = 0.5, p_mkt = 0.5 everywhere
    df = pd.DataFrame(
        [
            {"race_id": "R1", "horse_key": "A", "ganyan": 2.0, "win": 1.0, "agf_share": 0.40, "p_m": 0.80},  # edge=1.60 (>1.5)
            {"race_id": "R1", "horse_key": "B", "ganyan": 2.0, "win": 0.0, "agf_share": 0.60, "p_m": 0.20},  # edge=0.40 (<0.8)
            {"race_id": "R2", "horse_key": "C", "ganyan": 2.0, "win": 0.0, "agf_share": 0.70, "p_m": 0.55},  # edge=1.10 (1.05–1.2)
            {"race_id": "R2", "horse_key": "D", "ganyan": 2.0, "win": 1.0, "agf_share": 0.30, "p_m": 0.45},  # edge=0.90 (0.8–0.95)
        ]
    )
    buckets = compute_edge_buckets(df, "p_m").set_index("bucket")

    assert buckets.loc["<0.8", "bets"] == 1
    assert buckets.loc["<0.8", "win_rate"] == pytest.approx(0.0)
    assert buckets.loc["<0.8", "roi"] == pytest.approx(-1.0)

    assert buckets.loc["0.8–0.95", "bets"] == 1
    assert buckets.loc["0.8–0.95", "win_rate"] == pytest.approx(1.0)
    assert buckets.loc["0.8–0.95", "roi"] == pytest.approx(1.0)

    assert buckets.loc["0.95–1.05", "bets"] == 0
    assert np.isnan(buckets.loc["0.95–1.05", "roi"])

    assert buckets.loc["1.05–1.2", "bets"] == 1
    assert buckets.loc["1.05–1.2", "roi"] == pytest.approx(-1.0)

    assert buckets.loc["1.2–1.5", "bets"] == 0

    assert buckets.loc[">1.5", "bets"] == 1
    assert buckets.loc[">1.5", "win_rate"] == pytest.approx(1.0)
    assert buckets.loc[">1.5", "roi"] == pytest.approx(1.0)

    top_mod = compute_top1_roi(df, "p_m")
    assert top_mod["bets"] == 2
    assert top_mod["win_rate"] == pytest.approx(0.5)
    assert top_mod["roi"] == pytest.approx(0.0)

    top_agf = compute_top1_roi(df, "agf_share")
    assert top_agf["bets"] == 2
    assert top_agf["win_rate"] == pytest.approx(0.0)
    assert top_agf["roi"] == pytest.approx(-1.0)


def _populate_synthetic_v5_sqlite(db_path):
    """Create a synthetic multi-year SQLite DB (2022..2025 + 2026) with races, runners, ext_ratings, workouts."""
    conn = init_db(db_path)
    rng = np.random.default_rng(7)
    horses = [f"SIRE_{i}|DAM_{i}|2018" for i in range(12)]
    years_dates = {
        2022: ["2022-03-10", "2022-06-15", "2022-09-20", "2022-11-10"],
        2023: ["2023-03-10", "2023-06-15", "2023-09-20", "2023-11-10"],
        2024: ["2024-03-10", "2024-06-15", "2024-09-20", "2024-11-10"],
        2025: ["2025-03-10", "2025-06-15", "2025-09-20", "2025-11-10"],
        2026: ["2026-02-10", "2026-04-15"],
    }

    races = []
    runners = []
    ext_rows = []
    w_rows = []

    for _yr, d_list in sorted(years_dates.items()):
        for d_str in d_list:
            w_date = (pd.Timestamp(d_str) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
            for h_i, hk in enumerate(horses):
                w_rows.append(
                    (
                        "liderform",
                        hk,
                        f"AT {h_i}",
                        w_date,
                        "Ankara",
                        "SPRINT" if h_i % 2 == 0 else "GALOP",
                        50.5 + h_i * 0.1,
                        37.5 + h_i * 0.1,
                        24.5 + h_i * 0.1,
                        "ALLOUT" if h_i % 3 == 0 else "CANTER",
                    )
                )

            for r_no in (1, 2):
                rid = f"{d_str}_Ankara_{r_no}"
                races.append(
                    {
                        "race_id": rid,
                        "date": d_str,
                        "city": "Ankara",
                        "race_no": r_no,
                        "post_time": "14:00",
                        "yg_no": r_no,
                        "cls": "ŞARTLI",
                        "breed": "Ingiliz",
                        "distance": 1400,
                        "surface": "Çim",
                        "status": "result",
                    }
                )
                sub_h = horses[:6] if r_no == 1 else horses[6:]
                fins = rng.permutation(np.arange(1, 7))
                for pos, (hk, fin) in enumerate(zip(sub_h, fins)):
                    idx = int(hk.split("_")[1].split("|")[0])
                    runners.append(
                        {
                            "race_id": rid,
                            "prog_no": pos + 1,
                            "horse_key": hk,
                            "name": f"AT {idx}",
                            "name_raw": f"AT {idx}",
                            "age": 4,
                            "sex": "d" if idx % 2 == 0 else "e",
                            "sire": f"SIRE_{idx}",
                            "dam": f"DAM_{idx}",
                            "weight": 56.0 + pos * 0.5,
                            "jockey": f"J_{idx % 4}",
                            "owner": f"O_{idx % 3}",
                            "trainer": f"T_{idx % 3}",
                            "gate": pos + 1,
                            "hp": 50.0 + idx,
                            "finish": int(fin),
                            "time_s": 85.0 + float(fin) * 0.3,
                            "ganyan": 1.6 + float(fin) * 1.2,
                            "agf_close": 42.0 / float(fin),
                            "agf_close_rank": int(fin),
                            "scratched": 0,
                        }
                    )
                    ext_rows.append(("yenibeygir", rid, hk, "hiz", float(75 - fin * 3)))

    upsert_results(conn, {"races": races, "runners": runners, "bets": [], "altili": []})
    for pos_row in runners:
        conn.execute(
            "UPDATE runners SET prog_no = ? WHERE race_id = ? AND horse_key = ?",
            (pos_row["prog_no"], pos_row["race_id"], pos_row["horse_key"]),
        )
    conn.executemany(
        "INSERT OR REPLACE INTO ext_ratings (source, race_id, horse_key, name, value) VALUES (?, ?, ?, ?, ?)",
        ext_rows,
    )
    conn.executemany(
        """
        INSERT OR IGNORE INTO workouts (
            source, horse_key, horse_name, date, city, kind, d800, d600, d400, effort
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        w_rows,
    )
    conn.commit()

    loaded = load_v5_tables(conn)
    assert len(loaded["ext"]) == len(ext_rows)
    assert len(loaded["workouts"]) > 0
    assert pd.api.types.is_datetime64_any_dtype(loaded["workouts"]["date"])
    conn.close()


def test_load_v5_tables_empty_db(tmp_path):
    import sqlite3

    empty_db = tmp_path / "empty.db"
    conn = sqlite3.connect(str(empty_db))
    res = load_v5_tables(conn)
    conn.close()
    assert list(res["ext"].columns) == ["race_id", "horse_key", "value"]
    assert len(res["ext"]) == 0
    assert len(res["workouts"]) == 0
    assert pd.api.types.is_datetime64_any_dtype(res["workouts"]["date"])


def test_run_v5_backtest_end_to_end_synthetic_db(tmp_path):
    db_path = tmp_path / "syn_v5.db"
    _populate_synthetic_v5_sqlite(db_path)

    out_md = tmp_path / "V5.md"
    cache_dir = tmp_path / "v5_cache"

    res = run_v5_backtest(
        db_path=str(db_path),
        out_path=str(out_md),
        start_year=2022,
        first_test_year=2023,
        end_date="2025-12-31",
        cache_dir=str(cache_dir),
    )

    assert out_md.exists()
    md = res["report_markdown"]
    assert "kapanış AGF" in md
    assert "## 1. Veri Özeti ve Blok Doluluk Oranları" in md
    assert "### Blok Doluluk Oranları" in md
    assert "## 2. Toplam Performans Özeti" in md
    assert "## 3. Yıllık İleri-Yürüyen Performans" in md
    assert "## 4. Benter Birleşimi Katsayıları" in md
    assert "## 5. Kenar Kovası (Edge) ROI Tablosu" in md
    assert "`F_SGR+B`" in md
    assert "`B1`" in md
    assert "Yalnız AGF 1. Tercihi" in md
    assert (cache_dir / "pred_F_SGR_2023.pkl").exists()
    assert (cache_dir / "pred_F_SGR+B_2024.pkl").exists()
    assert (cache_dir / "pred_F_SGR+B_2025.pkl").exists()

    # Guardrail: --end-date > 2025-12-31 must fail without --locked
    with pytest.raises(ValueError):
        run_v5_backtest(
            db_path=str(db_path),
            out_path=str(tmp_path / "bad.md"),
            start_year=2022,
            first_test_year=2023,
            end_date="2026-01-15",
            cache_dir=str(cache_dir),
        )

    # Guardrail: --locked evaluates >= 2026-01-01 and refuses overwrite without --force
    locked_md = tmp_path / "V5_LOCKED.md"
    locked_res = run_v5_backtest(
        db_path=str(db_path),
        out_path=str(locked_md),
        start_year=2022,
        first_test_year=2023,
        cache_dir=str(cache_dir),
        locked=True,
    )
    assert locked_md.exists()
    assert set(locked_res["overall_df"]["variant"]) == {"B0", "B1", "F_SGR+B"}
    assert set(locked_res["yearly_df"]["year"]) == {2026}

    with pytest.raises(FileExistsError):
        run_v5_backtest(
            db_path=str(db_path),
            out_path=str(locked_md),
            start_year=2022,
            first_test_year=2023,
            cache_dir=str(cache_dir),
            locked=True,
            force=False,
        )

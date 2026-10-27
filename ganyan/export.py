"""Export JSON data contract for the mobile app (§5): index.json, race_<race_id>.json, payout_model.json."""
import datetime
import json
import os
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from ganyan.features import build_features, get_feature_cols
from ganyan.model import fit_predict_df
from ganyan.parse_program import parse_son6
from ganyan.payout import PayoutModel, build_altili_dataset

IST_TZ = ZoneInfo("Europe/Istanbul")
MODEL_VERSION = "v1_agf"


def _infer_altili_legs_for_city(city_races, db_altili_rows):
    """Return [{'which': w, 'races': [r1..r6]}] from DB altili table or standard TJK race count rules."""
    if db_altili_rows:
        out = []
        for w, s_r, e_r in sorted(db_altili_rows, key=lambda x: x[0]):
            out.append({"which": int(w), "races": list(range(int(s_r), int(e_r) + 1))})
        return out

    n = len(city_races)
    if n < 6:
        return []
    if n == 6:
        return [{"which": 1, "races": [1, 2, 3, 4, 5, 6]}]
    if n == 7:
        return [{"which": 1, "races": [2, 3, 4, 5, 6, 7]}]
    # 8, 9, 10+ races have two 6'lı Ganyans (1st starts at race 1; 2nd ends at race n)
    return [
        {"which": 1, "races": [1, 2, 3, 4, 5, 6]},
        {"which": 2, "races": list(range(n - 5, n + 1))},
    ]


def export_day(conn, date_str, out_root="data/export"):
    """Export JSON files for date_str into out_root/YYYY-MM-DD/."""
    out_dir = os.path.join(out_root, date_str)
    os.makedirs(out_dir, exist_ok=True)
    generated_at = datetime.datetime.now(IST_TZ).strftime("%Y-%m-%dT%H:%M:%S")

    # Load all historical + target day runners
    query = """
    SELECT
        r.race_id, r.date, r.city, r.race_no, r.post_time, r.yg_no,
        r.cls, r.breed, r.distance, r.surface, r.status,
        run.prog_no, run.horse_key, run.name, run.name_raw, run.age, run.sex,
        run.sire, run.dam, run.weight, run.jockey, run.owner, run.trainer,
        run.gate, run.hp, run.son6, run.kgs, run.s20, run.best_time_s,
        run.finish, run.time_s, run.ganyan, run.agf_close, run.agf_close_rank, run.scratched
    FROM races r
    JOIN runners run ON r.race_id = run.race_id
    WHERE r.date <= ?
    """
    df = pd.read_sql_query(query, conn, params=(date_str,))
    if df.empty or not (df["date"] == date_str).any():
        return out_dir

    # Load latest live AGF snapshots for date_str
    snaps = pd.read_sql_query(
        """
        SELECT s.race_id, s.prog_no, s.agf_pct, s.agf_rank
        FROM agf_snapshots s
        JOIN races r ON s.race_id = r.race_id
        WHERE r.date = ?
        ORDER BY s.captured_at ASC
        """,
        conn,
        params=(date_str,),
    )
    snap_pct_map = {}
    snap_rk_map = {}
    if not snaps.empty:
        latest = snaps.groupby(["race_id", "prog_no"], as_index=False).last()
        for _, srow in latest.iterrows():
            k = (srow["race_id"], int(srow["prog_no"]))
            snap_pct_map[k] = float(srow["agf_pct"]) if pd.notna(srow["agf_pct"]) else None
            snap_rk_map[k] = int(srow["agf_rank"]) if pd.notna(srow["agf_rank"]) else None

    # Load pre-logged predictions for date_str if available
    logged_preds = pd.read_sql_query(
        """
        SELECT p.race_id, p.prog_no, p.p_win
        FROM predictions p
        JOIN races r ON p.race_id = r.race_id
        WHERE r.date = ? AND p.model_version = ?
        """,
        conn,
        params=(date_str, MODEL_VERSION),
    )
    pred_map = {}
    if not logged_preds.empty:
        for _, prow in logged_preds.iterrows():
            pred_map[(prow["race_id"], int(prow["prog_no"]))] = float(prow["p_win"])

    # Compute prior form (starts, wins, last_finish) strictly before date_str
    hist_active = df[(df["date"] < date_str) & (df["scratched"].fillna(0) == 0) & (df["status"] == "result")].copy()
    hist_active = hist_active.sort_values(["date", "race_no"])
    form_map = {}
    if not hist_active.empty:
        for hk, grp in hist_active.groupby("horse_key"):
            fin = grp["finish"].dropna()
            form_map[hk] = {
                "starts": int(len(fin)),
                "wins": int((fin == 1).sum()),
                "last_finish": int(fin.iloc[-1]) if len(fin) > 0 else None,
            }

    # If any active runner on date_str lacks a pre-logged prediction, run model on the fly
    day_df = df[(df["date"] == date_str) & (df["scratched"].fillna(0) == 0)].copy()
    if len(pred_map) < len(day_df):
        work_df = df[df["scratched"].fillna(0) == 0].copy()
        mask_d = work_df["date"] == date_str
        for idx in work_df[mask_d].index:
            rid = work_df.at[idx, "race_id"]
            pno = int(work_df.at[idx, "prog_no"]) if pd.notna(work_df.at[idx, "prog_no"]) else -1
            if (rid, pno) in snap_pct_map and snap_pct_map[(rid, pno)] is not None:
                work_df.at[idx, "agf_close"] = snap_pct_map[(rid, pno)]
        work_df.loc[mask_d, ["finish", "time_s", "ganyan"]] = np.nan
        feat_df = build_features(work_df, ref_end="2025-07-01")
        base_cols, with_agf_cols = get_feature_cols(feat_df)
        rg = feat_df.groupby("race_id")
        ok_tr = (
            (feat_df["date"] >= pd.Timestamp("2025-01-01"))
            & (feat_df["date"] < pd.Timestamp(date_str))
            & rg["agf_close"].transform(lambda s: s.notna().all())
            & rg["ganyan"].transform(lambda s: s.notna().all())
            & (rg["win"].transform("sum") == 1)
            & (feat_df["field"] >= 4)
        )
        tr_df = feat_df[ok_tr]
        te_df = feat_df[feat_df["date"] == pd.Timestamp(date_str)].copy()
        if not tr_df.empty and not te_df.empty:
            use_cols = with_agf_cols if te_df["agf_close"].notna().any() else base_cols
            probs = fit_predict_df(tr_df, te_df, use_cols)
            for idx_i, (_, r_row) in enumerate(te_df.iterrows()):
                pno = int(r_row["prog_no"]) if pd.notna(r_row["prog_no"]) else idx_i + 1
                if (r_row["race_id"], pno) not in pred_map:
                    pred_map[(r_row["race_id"], pno)] = float(probs[idx_i])

    # Build index.json and race_<race_id>.json
    races_meta = pd.read_sql_query(
        "SELECT * FROM races WHERE date = ? ORDER BY city, race_no", conn, params=(date_str,)
    )
    cities_list = []
    for city, c_races in races_meta.groupby("city", sort=False):
        yg_no = int(c_races["yg_no"].dropna().iloc[0]) if not c_races["yg_no"].dropna().empty else None
        race_summaries = []
        for _, r_meta in c_races.iterrows():
            rid = r_meta["race_id"]
            r_runners = day_df[day_df["race_id"] == rid].copy()
            r_runners = r_runners.sort_values(["prog_no", "horse_key"]).reset_index(drop=True)
            field_size = int(len(r_runners))
            race_summaries.append({
                "race_id": rid,
                "race_no": int(r_meta["race_no"]),
                "post_time": r_meta["post_time"],
                "cls": r_meta["cls"],
                "breed": r_meta["breed"],
                "distance": int(r_meta["distance"]) if pd.notna(r_meta["distance"]) else None,
                "surface": r_meta["surface"],
                "field_size": field_size,
                "status": r_meta["status"],
            })

            # Normalize p_model across active runners in this race so sum == 1.0
            raw_ps = []
            for idx_i, (_, run_row) in enumerate(r_runners.iterrows()):
                pno = int(run_row["prog_no"]) if pd.notna(run_row["prog_no"]) else idx_i + 1
                raw_ps.append(pred_map.get((rid, pno), 1.0 / max(field_size, 1)))
            p_sum = sum(raw_ps)
            norm_ps = [p / p_sum if p_sum > 0 else 1.0 / max(field_size, 1) for p in raw_ps]

            runners_json = []
            for idx_i, (_, run_row) in enumerate(r_runners.iterrows()):
                pno = int(run_row["prog_no"]) if pd.notna(run_row["prog_no"]) else idx_i + 1
                hk = run_row["horse_key"]
                s6_parsed = [[s, int(pos)] for s, pos in parse_son6(run_row["son6"] or "")]
                agf_l = snap_pct_map.get((rid, pno))
                if agf_l is None and pd.notna(run_row["agf_close"]):
                    agf_l = float(run_row["agf_close"])
                agf_r = snap_rk_map.get((rid, pno))
                if agf_r is None and pd.notna(run_row["agf_close_rank"]):
                    agf_r = int(run_row["agf_close_rank"])

                item = {
                    "prog_no": pno,
                    "name": run_row["name"],
                    "age": int(run_row["age"]) if pd.notna(run_row["age"]) else None,
                    "sex": run_row["sex"],
                    "jockey": run_row["jockey"],
                    "trainer": run_row["trainer"],
                    "weight": float(run_row["weight"]) if pd.notna(run_row["weight"]) else None,
                    "gate": int(run_row["gate"]) if pd.notna(run_row["gate"]) else None,
                    "hp": float(run_row["hp"]) if pd.notna(run_row["hp"]) else None,
                    "son6": s6_parsed,
                    "kgs": int(run_row["kgs"]) if pd.notna(run_row["kgs"]) else None,
                    "best_time_s": float(run_row["best_time_s"]) if pd.notna(run_row["best_time_s"]) else None,
                    "agf_live": agf_l,
                    "agf_live_rank": agf_r,
                    "p_model": round(float(norm_ps[idx_i]), 8),
                    "form": form_map.get(hk, {"starts": 0, "wins": 0, "last_finish": None}),
                }
                if runners_json and idx_i == len(r_runners) - 1:
                    # Adjust last runner by residual so sum is exact to 1e-8
                    item["p_model"] = round(1.0 - sum(x["p_model"] for x in runners_json), 8)
                if r_meta["status"] == "result":
                    item["finish"] = int(run_row["finish"]) if pd.notna(run_row["finish"]) else None
                    item["ganyan"] = float(run_row["ganyan"]) if pd.notna(run_row["ganyan"]) else None
                runners_json.append(item)

            race_payload = {
                "race": race_summaries[-1],
                "runners": runners_json,
            }
            with open(os.path.join(out_dir, f"race_{rid}.json"), "w", encoding="utf-8") as f:
                json.dump(race_payload, f, ensure_ascii=False, indent=2)

        db_alt = conn.execute(
            "SELECT which, start_race, end_race FROM altili WHERE date = ? AND city = ?",
            (date_str, city),
        ).fetchall()
        cities_list.append({
            "city": city,
            "yg_no": yg_no,
            "races": race_summaries,
            "altili": _infer_altili_legs_for_city(race_summaries, db_alt),
        })

    index_payload = {
        "date": date_str,
        "generated_at": generated_at,
        "model_version": MODEL_VERSION,
        "cities": cities_list,
    }
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index_payload, f, ensure_ascii=False, indent=2)

    # Fit PayoutModel strictly through yesterday (or all available prior data)
    hist_all = df[df["date"] < date_str].copy()
    alt_prev = pd.read_sql_query("SELECT * FROM altili WHERE date < ?", conn, params=(date_str,))
    pm = PayoutModel(trained_through=date_str)
    if not alt_prev.empty and not hist_all.empty:
        alt_ds = build_altili_dataset(alt_prev, hist_all)
        if not alt_ds.empty:
            pm.fit(alt_ds)
    with open(os.path.join(out_dir, "payout_model.json"), "w", encoding="utf-8") as f:
        json.dump(pm.to_dict(), f, ensure_ascii=False, indent=2)

    return out_dir

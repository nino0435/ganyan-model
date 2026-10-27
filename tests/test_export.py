"""Tests for ganyan.export JSON contract (§5)."""
import json
import os
import pytest
from ganyan.db import init_db, upsert_program, upsert_results
from ganyan.export import export_day
from ganyan.parse_program import parse_program_file
from ganyan.parse_results import parse_results_file

RES_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "results_2026-10-24_Ankara.csv")
PROG_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "program_2026-10-27_Adana.csv")


def test_export_day_schema_and_probabilities(tmp_path):
    conn = init_db(tmp_path / "export_test.db")
    upsert_results(conn, parse_results_file(RES_FIX, date="2026-10-24", city="Ankara"))
    upsert_program(conn, parse_program_file(PROG_FIX, date="2026-10-27", city="Adana"))

    out_dir = export_day(conn, "2026-10-27", out_root=str(tmp_path / "export"))
    assert os.path.isdir(out_dir)

    index_path = os.path.join(out_dir, "index.json")
    payout_path = os.path.join(out_dir, "payout_model.json")
    assert os.path.exists(index_path)
    assert os.path.exists(payout_path)

    idx = json.load(open(index_path, encoding="utf-8"))
    assert idx["date"] == "2026-10-27"
    assert "generated_at" in idx
    assert idx["model_version"] == "v1_agf"
    assert len(idx["cities"]) == 1
    city_obj = idx["cities"][0]
    assert city_obj["city"] == "Adana"
    assert city_obj["yg_no"] == 21
    assert len(city_obj["races"]) == 8
    assert len(city_obj["altili"]) == 2

    pm = json.load(open(payout_path, encoding="utf-8"))
    assert "a_by_city" in pm
    assert "b" in pm
    assert "trained_through" in pm

    for r_summary in city_obj["races"]:
        rid = r_summary["race_id"]
        r_file = os.path.join(out_dir, f"race_{rid}.json")
        assert os.path.exists(r_file)
        r_data = json.load(open(r_file, encoding="utf-8"))
        assert "race" in r_data
        assert "runners" in r_data
        runners = r_data["runners"]
        assert len(runners) == r_summary["field_size"]
        p_sum = sum(x["p_model"] for x in runners)
        assert abs(p_sum - 1.0) <= 1e-6
        for runner in runners:
            for req_key in [
                "prog_no",
                "name",
                "age",
                "sex",
                "jockey",
                "trainer",
                "weight",
                "gate",
                "hp",
                "son6",
                "kgs",
                "best_time_s",
                "agf_live",
                "agf_live_rank",
                "p_model",
                "form",
            ]:
                assert req_key in runner
            assert set(runner["form"].keys()) == {"starts", "wins", "last_finish"}

    conn.close()


def test_forward_log_and_report_respects_post_time(tmp_path):
    from scripts.forward_log import forward_log
    from scripts.forward_report import build_forward_report

    db_path = tmp_path / "fwd.db"
    conn = init_db(db_path)
    upsert_results(conn, parse_results_file(RES_FIX, date="2026-10-24", city="Ankara"))
    upsert_program(conn, parse_program_file(PROG_FIX, date="2026-10-27", city="Adana"))
    conn.close()

    # Log predictions with created_at BEFORE post_time (14:30)
    n1 = forward_log("2026-10-27", db_path=str(db_path), do_snapshot=False, created_at="2026-10-27T12:00:00")
    assert n1 > 0
    # Second call should not overwrite existing predictions
    n2 = forward_log("2026-10-27", db_path=str(db_path), do_snapshot=False, created_at="2026-10-27T13:00:00")
    assert n2 == 0

    conn = init_db(db_path)
    md = build_forward_report(conn)
    assert "Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `8` koşu" in md
    conn.close()


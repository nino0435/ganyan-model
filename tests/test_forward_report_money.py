"""İleri test raporu para (ganyan + altılı), bootstrap GA ve çoklu sürüm testleri."""
import json
import re

from ganyan.db import init_db
from scripts.forward_report import ROI_NOTE, build_forward_report, forward_report, paired_bootstrap_ci

D = "2026-11-10"


def _seed(tmp_path, races_spec, db_name="t.db"):
    conn = init_db(tmp_path / db_name)
    for i, spec in enumerate(races_spec, start=1):
        d = spec.get("date", D)
        city = spec.get("city", "Bursa")
        rno = spec.get("race_no", i)
        rid = f"{d}_{city}_{rno}"
        conn.execute(
            "INSERT INTO races (race_id, date, city, race_no, post_time, status) VALUES (?,?,?,?,?,?)",
            (rid, d, city, rno, "14:00", spec.get("status", "result")),
        )
        agfs = spec["agfs"]
        winner = spec.get("winner", 1)
        other_fin = 2
        for no, a in enumerate(agfs, start=1):
            if no == winner:
                fin = 1
            else:
                fin = other_fin
                other_fin += 1
            conn.execute(
                "INSERT INTO runners (race_id, prog_no, horse_key, name, finish, scratched, agf_close) VALUES (?,?,?,?,?,?,?)",
                (rid, no, f"h_{d}_{rno}_{no}", f"H{no}", fin, 0, a),
            )

        models = spec.get("models")
        if models is None:
            p_wins = spec.get("p_wins", [1.0 / len(agfs)] * len(agfs))
            models = {"v1_agf": p_wins}

        for mv, p_list in models.items():
            for no, (a, pw) in enumerate(zip(agfs, p_list), start=1):
                conn.execute(
                    "INSERT INTO predictions (race_id, prog_no, model_version, created_at, p_win, agf_used) VALUES (?,?,?,?,?,?)",
                    (rid, no, mv, f"{d}T09:00:00", pw, a),
                )

        if spec.get("ganyan") is not None:
            combo, payout = spec["ganyan"]
            conn.execute(
                "INSERT INTO bets (race_id, bet, combo, payout) VALUES (?,?,?,?)",
                (rid, "GANYAN", str(combo), float(payout)),
            )
    conn.commit()
    return conn


def test_three_races_known_payouts_roi_and_disagreement(tmp_path):
    """(a) Bilinen ödemeli 3 koşuda AGF/model favorisi ROI'si elle hesaplanan değere eşit."""
    conn = _seed(
        tmp_path,
        [
            # Koşu 1: AGF fav=1, Model fav=1, kazanan=1 (2.40 TL) -> AGF=2.40, Model=2.40
            {"agfs": [50.0, 30.0, 20.0], "p_wins": [0.60, 0.25, 0.15], "winner": 1, "ganyan": ("1", 2.40)},
            # Koşu 2: AGF fav=1, Model fav=2, kazanan=2 (4.50 TL) -> AGF=0.00, Model=4.50
            {"agfs": [50.0, 30.0, 20.0], "p_wins": [0.25, 0.55, 0.20], "winner": 2, "ganyan": ("2", 4.50)},
            # Koşu 3: AGF fav=1, Model fav=2, kazanan=3 (6.00 TL) -> AGF=0.00, Model=0.00
            {"agfs": [50.0, 30.0, 20.0], "p_wins": [0.20, 0.50, 0.30], "winner": 3, "ganyan": ("3", 6.00)},
        ],
    )
    md = build_forward_report(conn)
    conn.close()

    # AGF: yatırılan=3.00, dönüş=2.40, ROI = 2.40/3 - 1 = -20.0%
    # Model: yatırılan=3.00, dönüş=6.90, ROI = 6.90/3 - 1 = +130.0%
    # Fark: dönüş=+4.50, ROI=+150.0%
    assert "## 3. Para (1 TL ganyan)" in md
    assert "GANYAN satırı olmayan (hesaptan çıkarılan) koşu:** `0`" in md
    assert "| Anlık AGF Favorisi | 3 | 3.00 | 2.40 | -20.0% |" in md
    assert "| Model (`v1_agf`) | 3 | 3.00 | 6.90 | +130.0% |" in md
    assert "| **Fark (Model − AGF)** | — | — | **+4.50** | **+150.0%** |" in md

    # Model != AGF: 2 koşu (Koşu 2 ve 3); AGF kazanan=0, Model kazanan=1
    assert "Model ≠ AGF Favorisi:** `2` koşu (AGF favorisi kazandı: `0`, Model favorisi kazandı: `1`)" in md
    assert ROI_NOTE in md


def test_comma_separated_combo_matches(tmp_path):
    """(b) Virgüllü combo (ör. '3,5') ölü yarış / eküri durumunda her iki prog_no ile eşleşir."""
    conn = _seed(
        tmp_path,
        [
            # Koşu 1: AGF fav=1, Model fav=5, combo="3,5" (3.80 TL) -> AGF=0, Model=3.80
            {
                "agfs": [40.0, 20.0, 15.0, 15.0, 10.0],
                "p_wins": [0.15, 0.15, 0.15, 0.15, 0.40],
                "winner": 3,
                "ganyan": ("3,5", 3.80),
            },
            # Koşu 2: AGF fav=3, Model fav=1, combo="3,5" (2.20 TL) -> AGF=2.20, Model=0
            {
                "agfs": [15.0, 20.0, 40.0, 15.0, 10.0],
                "p_wins": [0.40, 0.20, 0.15, 0.15, 0.10],
                "winner": 5,
                "ganyan": ("3,5", 2.20),
            },
        ],
    )
    md = build_forward_report(conn)
    conn.close()

    # AGF: 2.20 / 2.00 - 1 = +10.0%; Model: 3.80 / 2.00 - 1 = +90.0%
    assert "| Anlık AGF Favorisi | 2 | 2.00 | 2.20 | +10.0% |" in md
    assert "| Model (`v1_agf`) | 2 | 2.00 | 3.80 | +90.0% |" in md


def test_race_without_ganyan_row_excluded(tmp_path):
    """(c) GANYAN satırı olmayan koşu para hesabından çıkarılır ve sayısı yazılır."""
    conn = _seed(
        tmp_path,
        [
            {"agfs": [50.0, 30.0, 20.0], "p_wins": [0.60, 0.25, 0.15], "winner": 1, "ganyan": ("1", 3.00)},
            {"agfs": [50.0, 30.0, 20.0], "p_wins": [0.20, 0.60, 0.20], "winner": 2, "ganyan": None},
            {"agfs": [50.0, 30.0, 20.0], "p_wins": [0.20, 0.60, 0.20], "winner": 2, "ganyan": ("2", 2.00)},
        ],
    )
    # İKİLİ satırı olsa bile GANYAN olmadığı için 2. koşu yine dışlanmalı
    conn.execute(
        "INSERT INTO bets (race_id, bet, combo, payout) VALUES (?,?,?,?)",
        (f"{D}_Bursa_2", "İKİLİ", "1/2", 14.50),
    )
    conn.commit()

    md = build_forward_report(conn)
    conn.close()

    assert "Sonuçlanmış Geçerli Koşu:** `3`" in md
    assert "GANYAN satırı olmayan (hesaptan çıkarılan) koşu:** `1`" in md
    assert "| Anlık AGF Favorisi | 2 | 2.00 | 3.00 | +50.0% |" in md
    assert "| Model (`v1_agf`) | 2 | 2.00 | 5.00 | +150.0% |" in md


def test_two_model_versions_produce_two_ordered_sections(tmp_path):
    """(d) İki model_version varken iki bölüm üretilir (v1_agf önce, diğerleri alfabetik); tek sürümde başlık düzeni korunur."""
    db_path = tmp_path / "multi.db"
    conn = _seed(
        tmp_path,
        [
            {
                "agfs": [50.0, 30.0, 20.0],
                "models": {
                    "a_deneme": [0.20, 0.60, 0.20],
                    "v1_agf": [0.60, 0.25, 0.15],
                },
                "winner": 1,
                "ganyan": ("1", 2.50),
            },
            {
                "agfs": [50.0, 30.0, 20.0],
                "models": {
                    "a_deneme": [0.20, 0.60, 0.20],
                    "v1_agf": [0.25, 0.55, 0.20],
                },
                "winner": 2,
                "ganyan": ("2", 3.50),
            },
        ],
        db_name="multi.db",
    )

    # Tek sürüm açıkça istendiğinde bugünkü başlık düzeni (## 1., ## 2., ## 3.) korunur
    md_single = build_forward_report(conn, model_version="v1_agf")
    assert "## Model Sürümü:" not in md_single
    assert "## 1. Koşu Bazında Performans" in md_single
    assert "## 2. Altılı Karşılaştırması" in md_single
    assert "## 3. Para (1 TL ganyan)" in md_single
    assert "a_deneme" not in md_single
    conn.close()

    # Varsayılan forward_report çağrısında tüm sürümler (v1_agf önce, sonra alfabetik) yer alır
    out_file = tmp_path / "FORWARD.md"
    md_all = forward_report(db_path=str(db_path), out_path=str(out_file))
    assert out_file.read_text(encoding="utf-8") == md_all
    assert "## Model Sürümü: `v1_agf`" in md_all
    assert "## Model Sürümü: `a_deneme`" in md_all
    assert md_all.index("## Model Sürümü: `v1_agf`") < md_all.index("## Model Sürümü: `a_deneme`")
    assert md_all.count("### 3. Para (1 TL ganyan)") == 2


def test_bootstrap_ci_bounds_and_fixed_seed_determinism(tmp_path):
    """(e) Bootstrap GA alt sınırı <= üst sınır ve sabit tohumla birebir aynı sonucu verir."""
    vals = [-1.0, 0.0, 2.5, -0.5, 1.5, 0.0, 3.0, -1.0]
    m1, lo1, hi1 = paired_bootstrap_ci(vals, n_boot=2000, seed=0)
    m2, lo2, hi2 = paired_bootstrap_ci(vals, n_boot=2000, seed=0)
    assert lo1 <= m1 <= hi1
    assert lo1 < hi1
    assert (m1, lo1, hi1) == (m2, lo2, hi2)

    assert paired_bootstrap_ci([], n_boot=2000, seed=0) == (0.0, 0.0, 0.0)
    assert paired_bootstrap_ci([1.25], n_boot=2000, seed=0) == (1.25, 1.25, 1.25)

    conn = _seed(
        tmp_path,
        [
            {"agfs": [50.0, 30.0, 20.0], "p_wins": [0.60, 0.25, 0.15], "winner": 1, "ganyan": ("1", 2.10)},
            {"agfs": [50.0, 30.0, 20.0], "p_wins": [0.20, 0.60, 0.20], "winner": 2, "ganyan": ("2", 4.40)},
            {"agfs": [50.0, 30.0, 20.0], "p_wins": [0.25, 0.55, 0.20], "winner": 1, "ganyan": ("1", 1.90)},
            {"agfs": [50.0, 30.0, 20.0], "p_wins": [0.15, 0.35, 0.50], "winner": 3, "ganyan": ("3", 6.20)},
            {"agfs": [50.0, 30.0, 20.0], "p_wins": [0.55, 0.30, 0.15], "winner": 2, "ganyan": ("2", 3.30)},
        ],
    )
    md1 = build_forward_report(conn)
    md2 = build_forward_report(conn)
    conn.close()

    assert md1 == md2
    intervals = re.findall(r"`\[([+-]?\d+\.\d+)%?, ([+-]?\d+\.\d+)%?\]`", md1)
    assert len(intervals) == 3  # 1. tercih, log-loss, ganyan ROI
    for lo_s, hi_s in intervals:
        assert float(lo_s) <= float(hi_s)


def test_altili_money_known_vs_unknown_unit_price(tmp_path):
    """Altılıda Sabit-k, AGF — Amaç A ve Model — Amaç A para hesabı ve bilinmeyen dönem davranışı."""
    # Bütçe 10 TL, birim 1.25 TL -> en fazla 8 kombinasyon:
    # Sabit-k: k=[1,1,1,1,1,1] -> maliyet 1.25 TL
    # AGF — Amaç A ve Model — Amaç A: k=[2,2,2,1,1,1] -> maliyet 10.00 TL
    # 6. ayakta Model favorisi 2, AGF favorisi 1; resmi sonuç 6. ayakta [2] -> yalnız Model Amaç A 6/6 tutturur.
    specs_2026 = [
        {
            "date": "2026-11-10",
            "race_no": r,
            "agfs": [50.0, 30.0, 20.0],
            "p_wins": [0.30, 0.50, 0.20] if r == 6 else [0.50, 0.30, 0.20],
            "winner": 2 if r == 6 else 1,
            "ganyan": ("2" if r == 6 else "1", 2.50),
        }
        for r in range(1, 7)
    ]
    conn = _seed(tmp_path, specs_2026, db_name="alt2026.db")
    conn.execute(
        "INSERT INTO altili (date, city, which, start_race, end_race, legs, payout) VALUES (?,?,?,?,?,?,?)",
        ("2026-11-10", "Bursa", 1, 1, 6, json.dumps([[1], [1], [1], [1], [1], [2]]), 50.0),
    )
    conn.commit()
    md_2026 = build_forward_report(conn, budget_tl=10.0)
    conn.close()

    assert "| Sabit-k (AGF) | 0 / 1 | 1.25 | 0.00 | -100.0% |" in md_2026
    assert "| AGF — Amaç A | 0 / 1 | 10.00 | 0.00 | -100.0% |" in md_2026
    assert "| Model (`v1_agf`) — Amaç A | 1 / 1 | 10.00 | 50.00 | +400.0% |" in md_2026

    # Bilinmeyen birim fiyat dönemi (2025): yalnız 6/6 yazılır, para sütunları '—' olur
    specs_2025 = [{**s, "date": "2025-11-10"} for s in specs_2026]
    conn2 = _seed(tmp_path, specs_2025, db_name="alt2025.db")
    conn2.execute(
        "INSERT INTO altili (date, city, which, start_race, end_race, legs, payout) VALUES (?,?,?,?,?,?,?)",
        ("2025-11-10", "Bursa", 1, 1, 6, json.dumps([[1], [1], [1], [1], [1], [2]]), 50.0),
    )
    conn2.commit()
    md_2025 = build_forward_report(conn2, budget_tl=10.0)
    conn2.close()

    assert "| Sabit-k (AGF) | 0 / 1 | — | — | — |" in md_2025
    assert "| AGF — Amaç A | 0 / 1 | — | — | — |" in md_2025
    assert "| Model (`v1_agf`) — Amaç A | 1 / 1 | — | — | — |" in md_2025

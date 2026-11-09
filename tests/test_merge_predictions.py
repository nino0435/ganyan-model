"""merge_predictions.py ve karsilastir.py geçiş araçları testleri (§5, §6)."""
from ganyan.db import init_db
from scripts.karsilastir import compare_databases
from scripts.merge_predictions import merge_predictions

D = "2026-11-09"


def _setup_pair(tmp_path):
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"
    conn_a = init_db(db_a)
    conn_b = init_db(db_b)

    for conn in (conn_a, conn_b):
        for rno, pt in ((1, "14:00"), (2, "14:30"), (3, "15:00"), (4, "15:30")):
            conn.execute(
                "INSERT INTO races (race_id, date, city, race_no, post_time, status) VALUES (?,?,?,?,?,?)",
                (f"{D}_Bursa_{rno}", D, "Bursa", rno, pt, "scheduled"),
            )

    # Koşu 1: her ikisinde var, A daha ERKEN -> B güncellenmeli (değişen)
    conn_a.execute(
        "INSERT INTO predictions VALUES (?,?,?,?,?,?)",
        (f"{D}_Bursa_1", 1, "v1_agf", f"{D}T09:05:00", 0.40, 32.0),
    )
    conn_b.execute(
        "INSERT INTO predictions VALUES (?,?,?,?,?,?)",
        (f"{D}_Bursa_1", 1, "v1_agf", f"{D}T10:02:00", 0.38, 31.0),
    )

    # Koşu 2: her ikisinde var, B daha ERKEN -> B korunmalı (aynı)
    conn_a.execute(
        "INSERT INTO predictions VALUES (?,?,?,?,?,?)",
        (f"{D}_Bursa_2", 1, "v1_agf", f"{D}T11:00:00", 0.25, 20.0),
    )
    conn_b.execute(
        "INSERT INTO predictions VALUES (?,?,?,?,?,?)",
        (f"{D}_Bursa_2", 1, "v1_agf", f"{D}T09:10:00", 0.27, 21.0),
    )

    # Koşu 3: yalnız A'da var -> B'ye eklenmeli (eklenen)
    conn_a.execute(
        "INSERT INTO predictions VALUES (?,?,?,?,?,?)",
        (f"{D}_Bursa_3", 1, "v1_agf", f"{D}T12:00:00", 0.30, 25.0),
    )

    # Koşu 4: yalnız B'de var -> B'de korunmalı
    conn_b.execute(
        "INSERT INTO predictions VALUES (?,?,?,?,?,?)",
        (f"{D}_Bursa_4", 1, "v1_agf", f"{D}T12:05:00", 0.22, 18.0),
    )

    conn_a.commit()
    conn_b.commit()
    conn_a.close()
    conn_b.close()
    return db_a, db_b


def test_merge_predictions_dry_run_and_earliest_wins(tmp_path):
    """merge_predictions: erken created_at kazanır, tek tarafta olan eklenir/korunur, --dry-run yazmaz."""
    db_a, db_b = _setup_pair(tmp_path)

    # 1. dry-run: sayıları doğru döndürür ama B'yi değiştirmez
    res_dry = merge_predictions(str(db_a), str(db_b), dry_run=True)
    assert res_dry["added"] == 1
    assert res_dry["updated"] == 1
    assert res_dry["same"] == 1

    conn_b = init_db(db_b)
    rows_before = dict(
        conn_b.execute("SELECT race_id, created_at FROM predictions ORDER BY race_id").fetchall()
    )
    conn_b.close()
    assert f"{D}_Bursa_3" not in rows_before
    assert rows_before[f"{D}_Bursa_1"] == f"{D}T10:02:00"

    # 2. Gerçek birleştirme
    res = merge_predictions(str(db_a), str(db_b), dry_run=False)
    assert (res["added"], res["updated"], res["same"]) == (1, 1, 1)

    conn_b = init_db(db_b)
    merged = {
        r[0]: (r[1], r[2])
        for r in conn_b.execute("SELECT race_id, created_at, p_win FROM predictions").fetchall()
    }
    conn_b.close()

    # Koşu 1: A'nın erken kaydı kazandı
    assert merged[f"{D}_Bursa_1"] == (f"{D}T09:05:00", 0.40)
    # Koşu 2: B'nin erken kaydı korundu
    assert merged[f"{D}_Bursa_2"] == (f"{D}T09:10:00", 0.27)
    # Koşu 3: A'dan eklendi
    assert merged[f"{D}_Bursa_3"] == (f"{D}T12:00:00", 0.30)
    # Koşu 4: B'deki mevcut kayıt korundu
    assert merged[f"{D}_Bursa_4"] == (f"{D}T12:05:00", 0.22)


def test_karsilastir_markdown_table_is_readonly_and_accurate(tmp_path):
    """karsilastir.py: yalnız Mac / yalnız Actions / ikisi / hiçbiri sayılarını doğru hesaplar."""
    db_mac, db_act = _setup_pair(tmp_path)
    # 5. koşu: hiçbirinde tahmin yok
    for p in (db_mac, db_act):
        c = init_db(p)
        c.execute(
            "INSERT INTO races (race_id, date, city, race_no, post_time, status) VALUES (?,?,?,?,?,?)",
            (f"{D}_Bursa_5", D, "Bursa", 5, "16:00", "scheduled"),
        )
        c.commit()
        c.close()

    md = compare_databases(str(db_mac), str(db_act), from_date=D)
    assert f"| {D} | 5 | 1 | 1 | 2 | 1 |" in md

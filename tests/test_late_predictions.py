"""Geç (kapanış-AGF'li) tahmin (`v1_agf_late`) seçimi, kaydı ve raporu testleri."""
import datetime
import os

import pytest

from ganyan.db import init_db, upsert_program, upsert_results
from ganyan.parse_program import parse_program_file
from ganyan.parse_results import parse_results_file
from scripts import gozcu
from scripts.forward_log import LATE_MODEL_VERSION, MODEL_VERSION, forward_log
from scripts.forward_report import build_forward_report

D = "2026-11-09"
RES_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "results_2026-10-24_Ankara.csv")
PROG_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "program_2026-10-27_Adana.csv")


def _insert_card(conn, date_str, city, n_races, base_hour=13, cancelled_nos=()):
    for r in range(1, n_races + 1):
        hh = base_hour + (r - 1) // 2
        mm = 30 if (r - 1) % 2 else 0
        pt = f"{hh:02d}:{mm:02d}"
        st = "cancelled" if r in cancelled_nos else "scheduled"
        conn.execute(
            "INSERT INTO races (race_id, date, city, race_no, post_time, status) VALUES (?,?,?,?,?,?)",
            (f"{date_str}_{city}_{r}", date_str, city, r, pt, st),
        )
    conn.commit()


def test_agf_final_hm_table_and_cancelled(tmp_path):
    """(a) N=5/6/7/8/9/10 için AGF kesinleşme saati tablosu ve iptal koşuların N'den düşülmesi."""
    conn = init_db(tmp_path / "cards.db")
    try:
        # r=1 -> 13:00, r=2 -> 13:30, r=3 -> 14:00, r=4 -> 14:30, r=5 -> 15:00
        _insert_card(conn, D, "Elazığ", 5)
        _insert_card(conn, D, "Şanlıurfa", 6)
        _insert_card(conn, D, "Bursa", 7)
        _insert_card(conn, D, "Adana", 8)
        _insert_card(conn, D, "Ankara", 9)
        _insert_card(conn, D, "İstanbul", 10)
        # 7 satırlı ama 7. koşusu iptal kart -> aktif N=6
        _insert_card(conn, D, "İzmir", 7, cancelled_nos=(7,))

        # N=5 -> tüm koşular None
        for r in range(1, 6):
            assert gozcu.agf_final_hm(conn, D, f"{D}_Elazığ_{r}") is None

        # N=6 -> tüm r için 1. koşunun saati (13:00)
        for r in range(1, 7):
            assert gozcu.agf_final_hm(conn, D, f"{D}_Şanlıurfa_{r}") == "13:00"

        # N=7 -> r=1 None; r>=2 için 2. koşunun saati (13:30)
        assert gozcu.agf_final_hm(conn, D, f"{D}_Bursa_1") is None
        for r in range(2, 8):
            assert gozcu.agf_final_hm(conn, D, f"{D}_Bursa_{r}") == "13:30"

        # N=8 -> r<=2 None; r>=3 için 3. koşunun saati (14:00)
        assert gozcu.agf_final_hm(conn, D, f"{D}_Adana_1") is None
        assert gozcu.agf_final_hm(conn, D, f"{D}_Adana_2") is None
        assert gozcu.agf_final_hm(conn, D, f"{D}_Adana_5") == "14:00"
        for r in range(3, 9):
            assert gozcu.agf_final_hm(conn, D, f"{D}_Adana_{r}") == "14:00"

        # N=9 -> r=1..6 için 1. koşunun saati (13:00); r=7..9 için 4. koşunun saati (14:30)
        for r in range(1, 7):
            assert gozcu.agf_final_hm(conn, D, f"{D}_Ankara_{r}") == "13:00"
        for r in range(7, 10):
            assert gozcu.agf_final_hm(conn, D, f"{D}_Ankara_{r}") == "14:30"

        # N=10 -> r=1..6 için 1. koşunun saati (13:00); r=7..10 için 5. koşunun saati (15:00)
        for r in range(1, 7):
            assert gozcu.agf_final_hm(conn, D, f"{D}_İstanbul_{r}") == "13:00"
        for r in range(7, 11):
            assert gozcu.agf_final_hm(conn, D, f"{D}_İstanbul_{r}") == "15:00"

        # İptal koşu N'ye sayılmaz (7 - 1 = 6 -> başlangıç 1. koşu 13:00; iptal koşunun kendisi None)
        for r in range(1, 7):
            assert gozcu.agf_final_hm(conn, D, f"{D}_İzmir_{r}") == "13:00"
        assert gozcu.agf_final_hm(conn, D, f"{D}_İzmir_7") is None

        # Başlangıç koşusunun post_time'ı NULL ise veya olmayan race_id verilirse None
        conn.execute("UPDATE races SET post_time = NULL WHERE race_id = ?", (f"{D}_Şanlıurfa_1",))
        conn.commit()
        assert gozcu.agf_final_hm(conn, D, f"{D}_Şanlıurfa_3") is None
        assert gozcu.agf_final_hm(conn, D, f"{D}_Yok_1") is None
    finally:
        conn.close()


def test_pending_late_races_filters_time_started_and_existing(tmp_path):
    """(b) pending_late_races: kesinleşme öncesi boş, sonrası yalnız başlamamış ve geç tahmini olmayanlar."""
    conn = init_db(tmp_path / "t.db")
    try:
        # Bursa N=7 kartı: r=2..7 için kesinleşme saati 2. koşunun saati (13:30); r=1 için None
        _insert_card(conn, D, "Bursa", 7)
        # r=6 sonuçlanmış ('result') -> N yine 7 kalır ama r=6 bekleyen sayılmaz
        conn.execute("UPDATE races SET status = 'result' WHERE race_id = ?", (f"{D}_Bursa_6",))
        # r=4 için zaten v1_agf_late tahmini yazılmış -> hariç
        conn.execute(
            "INSERT INTO predictions (race_id, prog_no, model_version, created_at, p_win, agf_used) VALUES (?,?,?,?,?,?)",
            (f"{D}_Bursa_4", 1, LATE_MODEL_VERSION, f"{D}T13:31:00", 0.30, 30.0),
        )
        # r=5 için yalnız erken (v1_agf) tahmini var -> geç tahmin listesine GİRMELİ
        conn.execute(
            "INSERT INTO predictions (race_id, prog_no, model_version, created_at, p_win, agf_used) VALUES (?,?,?,?,?,?)",
            (f"{D}_Bursa_5", 1, MODEL_VERSION, f"{D}T09:00:00", 0.25, 25.0),
        )
        conn.commit()

        # Kesinleşme saati (13:30) öncesi -> boş
        assert gozcu.pending_late_races(conn, D, "13:20") == []

        # Tam kesinleşme saatinde (13:30): r=1 (None) ve r=2 (13:30 <= 13:30, başlamış) hariç; r=4 (geç var), r=6 (result) hariç
        assert gozcu.pending_late_races(conn, D, "13:30") == [
            (f"{D}_Bursa_3", "Bursa", "14:00"),
            (f"{D}_Bursa_5", "Bursa", "15:00"),
            (f"{D}_Bursa_7", "Bursa", "16:00"),
        ]

        # 14:05'te r=3 (14:00) de başlamış olduğundan yalnız r=5 ve r=7 kalır
        assert gozcu.pending_late_races(conn, D, "14:05") == [
            (f"{D}_Bursa_5", "Bursa", "15:00"),
            (f"{D}_Bursa_7", "Bursa", "16:00"),
        ]
    finally:
        conn.close()


def test_gozcu_run_late_predictions_and_fail_soft(tmp_path, monkeypatch, capsys):
    """gozcu.run: erken bekleyen yokken geç adayları atlamaz; geç blok hata atarsa ::warning:: basıp bozmaz."""
    db_path = tmp_path / "run.db"
    conn = init_db(db_path)
    _insert_card(conn, D, "Şanlıurfa", 6)  # N=6 -> kesinleşme 13:00 (r=1)
    for r in range(1, 7):
        rid = f"{D}_Şanlıurfa_{r}"
        conn.execute(
            "INSERT INTO agf_snapshots (race_id, prog_no, captured_at, agf_pct, agf_rank) VALUES (?,?,?,?,?)",
            (rid, 1, f"{D}T13:05:00+03:00", 40.0, 1),
        )
        if r <= 5:
            conn.execute(
                "INSERT INTO predictions (race_id, prog_no, model_version, created_at, p_win, agf_used) VALUES (?,?,?,?,?,?)",
                (rid, 1, MODEL_VERSION, f"{D}T09:00:00", 0.40, 40.0),
            )
    conn.commit()
    conn.close()

    # 13:17 -> r=1 başladı, r=6 erken+geç bekliyor, r=2..5 yalnız geç bekliyor; dakika 17 (keşif penceresi dışı)
    now = datetime.datetime(2026, 11, 9, 13, 17)

    # 1) Geç tahmin bloğu istisna fırlatsa bile erken tahmin ve dönüş bozulmaz (KURAL 2)
    def fake_fl_boom(date_str, db_path=None, prog_dir=None, do_snapshot=False, race_ids=None, model_version=MODEL_VERSION):
        if model_version == LATE_MODEL_VERSION:
            raise RuntimeError("sentetik geç hata")
        c = init_db(db_path)
        for rid in race_ids:
            c.execute(
                "INSERT OR IGNORE INTO predictions (race_id, prog_no, model_version, created_at, p_win, agf_used) VALUES (?,?,?,?,?,?)",
                (rid, 1, model_version, f"{date_str}T13:17:00", 0.40, 40.0),
            )
        c.commit()
        c.close()
        return len(race_ids)

    monkeypatch.setattr(gozcu, "forward_log", fake_fl_boom)
    assert gozcu.run(D, now, db_path=str(db_path), fetch=False, notify=False) == 1
    out1 = capsys.readouterr().out
    assert "::warning::" in out1 and "sentetik geç hata" in out1

    # 2) Artık tüm erken tahminler (r=1..6) yazılmış durumda (pend == [], discover == False).
    #    Erken çıkış geç adayları (r=2..6) atlamamalı; fetch=False yolunda geç tahminler yazılmalı.
    def fake_fl_ok(date_str, db_path=None, prog_dir=None, do_snapshot=False, race_ids=None, model_version=MODEL_VERSION):
        c = init_db(db_path)
        n = 0
        for rid in race_ids:
            cur = c.execute(
                "INSERT OR IGNORE INTO predictions (race_id, prog_no, model_version, created_at, p_win, agf_used) VALUES (?,?,?,?,?,?)",
                (rid, 1, model_version, f"{date_str}T13:17:00", 0.42, 42.0),
            )
            n += cur.rowcount
        c.commit()
        c.close()
        return n

    monkeypatch.setattr(gozcu, "forward_log", fake_fl_ok)
    assert gozcu.run(D, now, db_path=str(db_path), fetch=False, notify=False) == 5
    out2 = capsys.readouterr().out
    assert "KAPANIŞ-AGF'li (geç) tahmin: 5 koşu için 5 kayıt" in out2


def test_forward_log_late_version_writes_separate_pk_without_touching_early(tmp_path):
    """(c) forward_log(..., model_version='v1_agf_late') ayrı PK ile yazar, v1_agf satırlarını değiştirmez."""
    db_path = tmp_path / "fwd_late.db"
    conn = init_db(db_path)
    upsert_results(conn, parse_results_file(RES_FIX, date="2026-10-24", city="Ankara"))
    upsert_program(conn, parse_program_file(PROG_FIX, date="2026-10-27", city="Adana"))

    rid = "2026-10-27_Adana_3"
    prog_nos = [
        r[0]
        for r in conn.execute("SELECT prog_no FROM runners WHERE race_id = ? ORDER BY prog_no", (rid,)).fetchall()
    ]
    assert len(prog_nos) == 13

    # Sabah (erken) AGF anlık görüntüsü: 1 numaralı at %40, diğer 12 at %5 (toplam %100)
    for pno in prog_nos:
        agf = 40.0 if pno == 1 else 5.0
        conn.execute(
            "INSERT INTO agf_snapshots (race_id, prog_no, captured_at, agf_pct, agf_rank) VALUES (?,?,?,?,?)",
            (rid, pno, "2026-10-27T09:00:00+03:00", agf, 1 if pno == 1 else 2),
        )
    conn.commit()
    conn.close()

    n_early = forward_log(
        "2026-10-27",
        db_path=str(db_path),
        do_snapshot=False,
        created_at="2026-10-27T09:05:00",
        race_ids=[rid],
    )
    assert n_early == 13

    conn = init_db(db_path)
    early_before = conn.execute(
        "SELECT prog_no, created_at, p_win, agf_used FROM predictions WHERE race_id = ? AND model_version = ? ORDER BY prog_no",
        (rid, MODEL_VERSION),
    ).fetchall()

    # Kapanış AGF anlık görüntüsü: 1 numara %15'e düştü, 2 numara %30'a çıktı, diğer 11 at %5 (toplam %100)
    for pno in prog_nos:
        agf = 15.0 if pno == 1 else (30.0 if pno == 2 else 5.0)
        conn.execute(
            "INSERT INTO agf_snapshots (race_id, prog_no, captured_at, agf_pct, agf_rank) VALUES (?,?,?,?,?)",
            (rid, pno, "2026-10-27T15:31:00+03:00", agf, 1 if pno == 2 else 2),
        )
    conn.commit()
    conn.close()

    n_late = forward_log(
        "2026-10-27",
        db_path=str(db_path),
        do_snapshot=False,
        created_at="2026-10-27T15:32:00",
        race_ids=[rid],
        model_version=LATE_MODEL_VERSION,
    )
    assert n_late == 13
    # Aynı model_version için ikinci çağrı INSERT OR IGNORE ile 0 döner
    assert (
        forward_log(
            "2026-10-27",
            db_path=str(db_path),
            do_snapshot=False,
            created_at="2026-10-27T15:40:00",
            race_ids=[rid],
            model_version=LATE_MODEL_VERSION,
        )
        == 0
    )

    conn = init_db(db_path)
    try:
        early_after = conn.execute(
            "SELECT prog_no, created_at, p_win, agf_used FROM predictions WHERE race_id = ? AND model_version = ? ORDER BY prog_no",
            (rid, MODEL_VERSION),
        ).fetchall()
        late_rows = conn.execute(
            "SELECT prog_no, created_at, p_win, agf_used FROM predictions WHERE race_id = ? AND model_version = ? ORDER BY prog_no",
            (rid, LATE_MODEL_VERSION),
        ).fetchall()
    finally:
        conn.close()

    assert early_after == early_before
    assert len(late_rows) == 13
    early_agf = {pno: agf for pno, _, _, agf in early_after}
    late_agf = {pno: agf for pno, _, _, agf in late_rows}
    assert early_agf[1] == pytest.approx(40.0)
    assert late_agf[1] == pytest.approx(15.0)
    assert late_agf[2] == pytest.approx(30.0)


def test_forward_report_dual_version_section_and_single_version_omission(tmp_path):
    """(d) Rapor: tek sürümde yeni bölüm yok; iki sürümde ortak geçerli koşular tablosu ve sayıları doğru."""
    rd = "2026-11-10"
    conn = init_db(tmp_path / "rep.db")
    try:
        post_times = {1: "13:30", 2: "14:00", 3: "14:30", 4: "15:00", 5: "15:30"}
        for r_no, pt in post_times.items():
            rid = f"{rd}_Bursa_{r_no}"
            conn.execute(
                "INSERT INTO races (race_id, date, city, race_no, post_time, status) VALUES (?,?,?,?,?,?)",
                (rid, rd, "Bursa", r_no, pt, "result"),
            )
            for pno in (1, 2, 3):
                conn.execute(
                    "INSERT INTO runners (race_id, prog_no, horse_key, name, finish, scratched, agf_close) VALUES (?,?,?,?,?,?,?)",
                    (rid, pno, f"h_{r_no}_{pno}", f"H{pno}", pno, 0, 33.33),
                )

        # Erken tahminler (v1_agf): 5 koşunun tümü geçerli ve koşu öncesi
        early_specs = {
            1: ([50.0, 30.0, 20.0], [0.50, 0.30, 0.20]),
            2: ([20.0, 50.0, 30.0], [0.25, 0.45, 0.30]),  # kazanan (1) favori değil
            3: ([50.0, 30.0, 20.0], [0.50, 0.30, 0.20]),  # kazanan (1) favori
            4: ([50.0, 30.0, 20.0], [0.50, 0.30, 0.20]),
            5: ([50.0, 30.0, 20.0], [0.50, 0.30, 0.20]),
        }
        for r_no, (agfs, ps) in early_specs.items():
            rid = f"{rd}_Bursa_{r_no}"
            for pno, agf, pw in zip((1, 2, 3), agfs, ps):
                conn.execute(
                    "INSERT INTO predictions (race_id, prog_no, model_version, created_at, p_win, agf_used) VALUES (?,?,?,?,?,?)",
                    (rid, pno, MODEL_VERSION, f"{rd}T09:00:00", pw, agf),
                )
        conn.commit()

        # Tek sürüm varken yeni bölüm eklenmemeli
        md_single = build_forward_report(conn)
        assert "## Erken ve Geç Tahmin (aynı koşular)" not in md_single

        # Geç tahminler (v1_agf_late):
        # - Koşu 1: geç tahmin yok
        # - Koşu 2 & 3: geçerli koşu öncesi (ortak 2 koşu)
        # - Koşu 4: created_at >= post_time (15:05 >= 15:00) -> dışlanmalı
        # - Koşu 5: AGF %0 içeriyor -> dışlanmalı
        late_specs = {
            2: (f"{rd}T13:35:00", [50.0, 30.0, 20.0], [0.60, 0.25, 0.15]),
            3: (f"{rd}T13:35:00", [25.0, 45.0, 30.0], [0.50, 0.30, 0.20]),
            4: (f"{rd}T15:05:00", [50.0, 30.0, 20.0], [0.50, 0.30, 0.20]),
            5: (f"{rd}T13:35:00", [50.0, 50.0, 0.0], [0.50, 0.30, 0.20]),
        }
        for r_no, (ts, agfs, ps) in late_specs.items():
            rid = f"{rd}_Bursa_{r_no}"
            for pno, agf, pw in zip((1, 2, 3), agfs, ps):
                conn.execute(
                    "INSERT INTO predictions (race_id, prog_no, model_version, created_at, p_win, agf_used) VALUES (?,?,?,?,?,?)",
                    (rid, pno, LATE_MODEL_VERSION, ts, pw, agf),
                )
        conn.commit()

        md_dual = build_forward_report(conn)
        assert f"## Model Sürümü: `{MODEL_VERSION}`" in md_dual
        assert f"## Model Sürümü: `{LATE_MODEL_VERSION}`" in md_dual
        assert "## Erken ve Geç Tahmin (aynı koşular)" in md_dual

        sec = md_dual.split("## Erken ve Geç Tahmin (aynı koşular)", 1)[1]
        assert "**Ortak Sonuçlanmış Geçerli Koşu:** `2`" in sec
        assert f"| AGF (erken, `{MODEL_VERSION}`) | 2 | 50.0% | 1.1513 |" in sec
        assert f"| Model (erken, `{MODEL_VERSION}`) | 2 | 50.0% | 1.0397 |" in sec
        assert f"| AGF (geç, `{LATE_MODEL_VERSION}`) | 2 | 50.0% | 1.0397 |" in sec
        assert f"| Model (geç, `{LATE_MODEL_VERSION}`) | 2 | 100.0% | 0.6020 |" in sec
        assert "| **Fark (Model_geç − AGF_geç)** | 2 | **+50.0%** | **-0.4377** |" in sec
        assert "Koşu-Eşli Bootstrap %95 GA (Model_geç − AGF_geç, 2000 tekrar):" in sec
    finally:
        conn.close()

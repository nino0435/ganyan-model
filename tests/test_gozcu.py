"""Gözcü: bekleyen/kaçan koşu seçimi ve saat kapısı (ağsız, sahte DB)."""
import datetime

from ganyan.db import init_db
from scripts import gozcu

D = "2026-11-09"


def _db(tmp_path):
    conn = init_db(tmp_path / "t.db")
    races = [
        # race_id, city, no, post_time, status
        (f"{D}_Bursa_1", "Bursa", 1, "14:00", "scheduled"),  # AGF var, tahmin yok, gelecek -> bekleyen
        (f"{D}_Bursa_2", "Bursa", 2, "14:30", "scheduled"),  # tahmini var -> bekleyen değil
        (f"{D}_Bursa_3", "Bursa", 3, "09:00", "scheduled"),  # saati geçti, AGF var, tahmin yok -> KAÇTI
        (f"{D}_Bursa_4", "Bursa", 4, "09:10", "scheduled"),  # saati geçti ama AGF hiç yok -> kaçmış sayılmaz
        (f"{D}_Urfa_1", "Şanlıurfa", 1, "17:00", "cancelled"),  # iptal -> hiçbiri
        (f"{D}_Urfa_2", "Şanlıurfa", 2, "17:30", "scheduled"),  # AGF henüz yok -> bekleyen ama hazır değil
    ]
    for rid, city, no, pt, st in races:
        conn.execute(
            "INSERT INTO races (race_id, date, city, race_no, post_time, status) VALUES (?,?,?,?,?,?)",
            (rid, D, city, no, pt, st),
        )
    for rid in (f"{D}_Bursa_1", f"{D}_Bursa_2", f"{D}_Bursa_3"):
        conn.execute(
            "INSERT INTO agf_snapshots (race_id, prog_no, captured_at, agf_pct, agf_rank) VALUES (?,?,?,?,?)",
            (rid, 1, f"{D}T08:00:00+03:00", 30.0, 1),
        )
    conn.execute(
        "INSERT INTO predictions (race_id, prog_no, model_version, created_at, p_win, agf_used) VALUES (?,?,?,?,?,?)",
        (f"{D}_Bursa_2", 1, "v1_agf", f"{D}T08:05:00", 0.3, 30.0),
    )
    conn.commit()
    return conn


def test_pending_races_lists_unpredicted_future_noncancelled(tmp_path):
    conn = _db(tmp_path)
    ids = [r[0] for r in gozcu.pending_races(conn, D, "10:00")]
    assert ids == [f"{D}_Bursa_1", f"{D}_Urfa_2"]


def test_agf_ready_ids_only_races_with_agf_rows(tmp_path):
    conn = _db(tmp_path)
    assert gozcu.agf_ready_ids(conn, [f"{D}_Bursa_1", f"{D}_Urfa_2"]) == [f"{D}_Bursa_1"]
    assert gozcu.agf_ready_ids(conn, []) == []


def test_missed_races_requires_agf_and_past_post_time(tmp_path):
    conn = _db(tmp_path)
    assert [m[0] for m in gozcu.missed_races(conn, D, "10:00")] == [f"{D}_Bursa_3"]
    # saat 08:00'de hiçbiri henüz geçmedi
    assert gozcu.missed_races(conn, D, "08:00") == []


def test_run_is_quiet_before_start_hour(tmp_path):
    _db(tmp_path)
    now = datetime.datetime(2026, 11, 9, 6, 0)
    assert gozcu.run(D, now, db_path=str(tmp_path / "t.db"), fetch=False, notify=False) == 0


def test_run_without_pending_or_discovery_does_not_touch_network(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO races (race_id, date, city, race_no, post_time, status) VALUES (?,?,?,?,?,?)",
        (f"{D}_Bursa_1", D, "Bursa", 1, "09:00", "result"),
    )
    conn.commit()
    conn.close()
    called = []
    monkeypatch.setattr(gozcu, "snapshot_agf", lambda *a, **k: called.append("snap"))
    monkeypatch.setattr(gozcu, "domestic_cities", lambda *a, **k: called.append("disc") or [])
    now = datetime.datetime(2026, 11, 9, 10, 17)  # dakika 17: keşif penceresi dışında, bekleyen yok
    assert gozcu.run(D, now, db_path=str(tmp_path / "t.db")) == 0
    assert called == []


def test_run_force_discover_triggers_discovery_outside_window(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO races (race_id, date, city, race_no, post_time, status) VALUES (?,?,?,?,?,?)",
        (f"{D}_Bursa_1", D, "Bursa", 1, "09:00", "result"),
    )
    conn.commit()
    conn.close()
    called = []
    monkeypatch.setattr(gozcu, "domestic_cities", lambda *a, **k: called.append("disc") or ["Bursa"])
    monkeypatch.setattr(gozcu, "snapshot_agf", lambda *a, **k: called.append("snap"))
    now = datetime.datetime(2026, 11, 9, 10, 17)  # dakika 17: normalde keşif yok, force_discover ile var
    assert gozcu.run(D, now, db_path=str(tmp_path / "t.db"), notify=False, force_discover=True) == 0
    assert called == ["disc", "snap"]


def test_notify_missed_skips_osascript_off_darwin(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(gozcu.sys, "platform", "linux")
    monkeypatch.setattr(gozcu.subprocess, "run", lambda *a, **k: calls.append(a))
    gozcu._notify_missed(D, [(f"{D}_Bursa_3", "Bursa 3. koşu 09:00")], str(tmp_path))
    assert calls == []
    assert not (tmp_path / f".gozcu_missed_{D}").exists()

    monkeypatch.setattr(gozcu.sys, "platform", "darwin")
    gozcu._notify_missed(D, [(f"{D}_Bursa_3", "Bursa 3. koşu 09:00")], str(tmp_path))
    assert len(calls) == 1
    assert calls[0][0][0] == "osascript"


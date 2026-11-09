"""scripts/actions_run.py ve durum sağlama testleri (§2.2, §2.3, §5)."""
import csv
import datetime
import json
import pytest

from ganyan.db import init_db
from scripts import actions_run as ar
from scripts.actions_restore_predictions import restore_predictions

D = "2026-11-09"


def _make_valid_db(db_path, n_races=1005, n_preds=10):
    conn = init_db(db_path)
    races = [
        (f"2026-01-01_Bursa_{i}", "2026-01-01", "Bursa", i, "14:00", "result")
        for i in range(1, n_races + 1)
    ]
    conn.executemany(
        "INSERT INTO races (race_id, date, city, race_no, post_time, status) VALUES (?,?,?,?,?,?)",
        races,
    )
    preds = [
        (f"2026-01-01_Bursa_{i}", 1, "v1_agf", "2026-01-01T10:00:00", 0.25, 22.0)
        for i in range(1, n_preds + 1)
    ]
    if preds:
        conn.executemany(
            "INSERT INTO predictions (race_id, prog_no, model_version, created_at, p_win, agf_used) VALUES (?,?,?,?,?,?)",
            preds,
        )
    conn.commit()
    conn.close()


def test_ensure_state_fails_on_missing_or_empty_db(tmp_path):
    """Boş ya da olmayan veritabanında ensure_state hata fırlatır ve main() exit 1 döner."""
    missing_db = tmp_path / "missing.db"
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    with pytest.raises(ar.StateValidationError, match="bulunamadı"):
        ar.ensure_state(db_path=str(missing_db), state_dir=str(state_dir))
    assert not missing_db.exists()  # asla boş DB oluşturmamalı

    empty_db = tmp_path / "empty.db"
    empty_db.write_bytes(b"")
    with pytest.raises(ar.StateValidationError, match="boş"):
        ar.ensure_state(db_path=str(empty_db), state_dir=str(state_dir))

    # CLI main() de 1 ile çıkmalı
    rc = ar.main(["tahmin", "--db", str(empty_db), "--state-dir", str(state_dir), "--dry-run"])
    assert rc == 1


def test_ensure_state_fails_on_low_races_count(tmp_path):
    """races < 1000 ise ensure_state hata fırlatır."""
    db_path = tmp_path / "low_races.db"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _make_valid_db(db_path, n_races=50, n_preds=5)

    with pytest.raises(ar.StateValidationError, match="races satır sayısı yetersiz"):
        ar.ensure_state(db_path=str(db_path), state_dir=str(state_dir))

    rc = ar.main(["aksam", "--db", str(db_path), "--state-dir", str(state_dir), "--dry-run"])
    assert rc == 1


def test_ensure_state_fails_below_predictions_high_water(tmp_path):
    """predictions satır sayısı state/budget.json içindeki predictions_high_water altındaysa hata verir."""
    db_path = tmp_path / "valid.db"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _make_valid_db(db_path, n_races=1005, n_preds=20)

    budget_file = state_dir / "budget.json"
    budget_file.write_text(
        json.dumps({"month": "2026-11", "used_min": 10, "runs": [], "predictions_high_water": 25}),
        encoding="utf-8",
    )

    with pytest.raises(ar.StateValidationError, match="predictions_high_water"):
        ar.ensure_state(db_path=str(db_path), state_dir=str(state_dir))

    # high_water <= 20 olduğunda doğrulama geçer
    budget_file.write_text(
        json.dumps({"month": "2026-11", "used_min": 10, "runs": [], "predictions_high_water": 20}),
        encoding="utf-8",
    )
    info = ar.ensure_state(db_path=str(db_path), state_dir=str(state_dir))
    assert info["ok"] is True
    assert info["races"] == 1005
    assert info["predictions"] == 20


def test_append_predictions_csv_no_duplicate_pks_and_restore(tmp_path):
    """Yeni tahmin CSV ekleme: başlıklı yazar ve aynı (race_id, prog_no, model_version) iki kez yazılmaz."""
    db_path = tmp_path / "t.db"
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO races (race_id, date, city, race_no, post_time, status) VALUES (?,?,?,?,?,?)",
        (f"{D}_Ankara_1", D, "Ankara", 1, "14:00", "scheduled"),
    )
    conn.execute(
        "INSERT INTO predictions (race_id, prog_no, model_version, created_at, p_win, agf_used) VALUES (?,?,?,?,?,?)",
        (f"{D}_Ankara_1", 1, "v1_agf", f"{D}T10:05:00", 0.35, 28.5),
    )
    conn.execute(
        "INSERT INTO predictions (race_id, prog_no, model_version, created_at, p_win, agf_used) VALUES (?,?,?,?,?,?)",
        (f"{D}_Ankara_1", 2, "v1_agf", f"{D}T10:05:00", 0.20, 15.0),
    )
    conn.commit()

    csv_path = tmp_path / "state" / "predictions" / f"{D}.csv"
    added1, races1 = ar.append_predictions_csv(conn, D, str(csv_path), since_iso=f"{D}T10:00:00")
    assert (added1, races1) == (2, 1)

    # Aynı veriyi tekrar eklemeye çalışınca aynı PK tekrar yazılmaz
    added2, races2 = ar.append_predictions_csv(conn, D, str(csv_path), since_iso=f"{D}T10:00:00")
    assert (added2, races2) == (0, 0)

    # Yeni bir at tahmini eklendiğinde yalnız yeni satır CSV'ye eklenir
    conn.execute(
        "INSERT INTO predictions (race_id, prog_no, model_version, created_at, p_win, agf_used) VALUES (?,?,?,?,?,?)",
        (f"{D}_Ankara_1", 3, "v1_agf", f"{D}T11:02:00", 0.15, 12.0),
    )
    conn.commit()
    added3, races3 = ar.append_predictions_csv(conn, D, str(csv_path), since_iso=f"{D}T11:00:00")
    assert (added3, races3) == (1, 1)
    conn.close()

    with open(csv_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    assert list(rows[0].keys()) == ["race_id", "prog_no", "model_version", "created_at", "p_win", "agf_used"]

    # Kurtarma betiği CSV'den boş bir veritabanına tüm satırları geri yükler
    restored_db = tmp_path / "restored.db"
    res = restore_predictions(db_path=str(restored_db), predictions_dir=str(csv_path.parent))
    assert res["inserted"] == 3
    # İkinci kez çalıştırıldığında INSERT OR IGNORE sayesinde 0 ekler
    res_again = restore_predictions(db_path=str(restored_db), predictions_dir=str(csv_path.parent))
    assert res_again["inserted"] == 0


def test_dry_run_does_not_touch_network_or_write_db(tmp_path, monkeypatch):
    """--dry-run modunda ağ çağrılmaz, DB ve state dosyaları değiştirilmez."""
    db_path = tmp_path / "valid.db"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _make_valid_db(db_path, n_races=1005, n_preds=15)

    before_fp = ar.db_fingerprint(str(db_path))
    calls = []
    monkeypatch.setattr(ar.gozcu, "run", lambda *a, **k: calls.append("gozcu.run"))
    monkeypatch.setattr(ar, "update_daily", lambda *a, **k: calls.append("update_daily"))

    rc_tahmin = ar.main([
        "tahmin",
        "--date", D,
        "--now", f"{D}T10:00:00",
        "--db", str(db_path),
        "--state-dir", str(state_dir),
        "--dry-run",
    ])
    assert rc_tahmin == 0

    rc_aksam = ar.main([
        "aksam",
        "--date", D,
        "--now", f"{D}T00:45:00",
        "--db", str(db_path),
        "--state-dir", str(state_dir),
        "--dry-run",
    ])
    assert rc_aksam == 0

    assert calls == []
    assert ar.db_fingerprint(str(db_path)) == before_fp
    assert not (state_dir / "budget.json").exists()
    assert not (state_dir / "FORWARD.md").exists()


def _parse_github_output(path):
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def test_tahmin_no_new_predictions_persists_budget_and_bekleyen_yok_msg(tmp_path, monkeypatch):
    """T2-1 & T2-3: Yeni tahmin yazılmasa bile gerçek çalışmada budget.json kaydedilir,
    state_changed=true ve commit_msg='tahmin D HH:MM: bekleyen yok' döner, +40 sn ek süre uygulanır."""
    db_path = tmp_path / "valid.db"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _make_valid_db(db_path, n_races=1005, n_preds=15)

    gh_out = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    monkeypatch.setattr(ar.gozcu, "run", lambda *a, **k: 0)
    # 25 sn betik süresi + 40 sn OVERHEAD_SEC_TAHMIN = 65 sn -> ceil = 2 dk
    monkeypatch.setattr(ar, "_elapsed_seconds", lambda _s: 25.0)

    rc = ar.main([
        "tahmin",
        "--date", D,
        "--now", f"{D}T10:00:00",
        "--db", str(db_path),
        "--state-dir", str(state_dir),
    ])
    assert rc == 0

    budget_data = json.loads((state_dir / "budget.json").read_text(encoding="utf-8"))
    assert budget_data["used_min"] == 2
    assert budget_data["runs"][-1]["billed_min"] == 2

    outputs = _parse_github_output(gh_out)
    assert outputs["state_changed"] == "true"
    assert outputs["new_predictions"] == "0"
    assert outputs["commit_msg"] == f"tahmin {D} 10:00: bekleyen yok"


def test_tahmin_budget_gate_skip_records_run_and_sets_state_changed(tmp_path, monkeypatch):
    """T2-2: karar=='atla' yolunda da record_run ile ~1 dk kaydedilir ve state_changed=true döner."""
    db_path = tmp_path / "valid.db"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _make_valid_db(db_path, n_races=1005, n_preds=15)

    budget_file = state_dir / "budget.json"
    budget_file.write_text(
        json.dumps({"month": "2026-11", "used_min": 1450, "runs": [], "predictions_high_water": 15}),
        encoding="utf-8",
    )

    gh_out = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    monkeypatch.setattr(ar, "_elapsed_seconds", lambda _s: 5.0)  # 5s + 40s = 45s -> 1 dk
    called = []
    monkeypatch.setattr(ar.gozcu, "run", lambda *a, **k: called.append(1))

    # 09:00 isteğe bağlı slot -> 1450 >= 1400 olduğu için atlanır
    rc = ar.main([
        "tahmin",
        "--date", D,
        "--now", f"{D}T09:00:00",
        "--db", str(db_path),
        "--state-dir", str(state_dir),
    ])
    assert rc == 0
    assert called == []

    budget_after = json.loads(budget_file.read_text(encoding="utf-8"))
    assert budget_after["used_min"] == 1451
    assert len(budget_after["runs"]) == 1
    assert budget_after["runs"][0]["billed_min"] == 1

    outputs = _parse_github_output(gh_out)
    assert outputs["state_changed"] == "true"
    assert outputs["skipped_budget"] == "true"
    assert outputs["commit_msg"] == f"tahmin {D} 09:00: bekleyen yok"


def test_aksam_applies_overhead_sec_aksam(tmp_path, monkeypatch):
    """T2-3: aksam modunda OVERHEAD_SEC_AKSAM (+90 sn) eklenerek ceil uygulanır."""
    db_path = tmp_path / "valid.db"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _make_valid_db(db_path, n_races=1005, n_preds=15)

    monkeypatch.setattr(ar, "update_daily", lambda *a, **k: None)
    monkeypatch.setattr(ar, "forward_report", lambda *a, **k: None)
    # 40 sn betik süresi + 90 sn OVERHEAD_SEC_AKSAM = 130 sn -> ceil(130/60) = 3 dk
    monkeypatch.setattr(ar, "_elapsed_seconds", lambda _s: 40.0)

    rc = ar.main([
        "aksam",
        "--date", D,
        "--now", f"{D}T00:45:00",
        "--db", str(db_path),
        "--state-dir", str(state_dir),
    ])
    assert rc == 0

    budget_data = json.loads((state_dir / "budget.json").read_text(encoding="utf-8"))
    assert budget_data["used_min"] == 3
    assert budget_data["runs"][-1]["billed_min"] == 3

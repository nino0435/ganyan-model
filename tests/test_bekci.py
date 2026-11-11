"""Bekçi: beklenen tetik saatlerinde çalışma yoksa/hata varsa sorun üretir (ağsız)."""
import datetime as dt

from scripts import bekci

IST = bekci.IST


def _run(wf, y, mo, d, h, m, conclusion="success"):
    ts = dt.datetime(y, mo, d, h, m, tzinfo=IST).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    return {"workflowName": wf, "createdAt": ts, "conclusion": conclusion}


def _now(h, m):
    return dt.datetime(2026, 11, 11, h, m, tzinfo=IST)


def test_no_problem_when_every_slot_ran():
    runs = [_run(bekci.TAHMIN, 2026, 11, 11, h, 0) for h in (9, 10, 11)]
    assert bekci.find_problems(_now(11, 15), runs) == []


def test_missing_slot_is_reported():
    runs = [_run(bekci.TAHMIN, 2026, 11, 11, 9, 0), _run(bekci.TAHMIN, 2026, 11, 11, 11, 0)]  # 10:00 yok
    p = bekci.find_problems(_now(11, 15), runs)
    assert len(p) == 1 and "10:00" in p[0]


def test_slot_not_yet_due_is_not_reported():
    # 11:10'da 11:00 tetiği için ek süre (20 dk) daha dolmadı
    runs = [_run(bekci.TAHMIN, 2026, 11, 11, h, 0) for h in (9, 10)]
    assert bekci.find_problems(_now(11, 10), runs) == []


def test_old_slots_beyond_lookback_ignored():
    p = bekci.find_problems(_now(15, 15), [])
    assert not any("12:00" in x or "11:00" in x for x in p)  # 3 saatten eski tetikler bakılmaz
    assert any("14:30" in x for x in p)


def test_aksam_slot_checked_next_night():
    p = bekci.find_problems(dt.datetime(2026, 11, 12, 2, 15, tzinfo=IST), [])
    assert any("Akşam" in x and "00:45" in x for x in p)


def test_failed_run_and_budget_are_reported():
    runs = [_run(bekci.TAHMIN, 2026, 11, 11, 9, 0, "failure"), _run(bekci.TAHMIN, 2026, 11, 11, 10, 0)]
    p = bekci.find_problems(_now(10, 40), runs, budget_used=1800)
    assert any("failure" in x for x in p) and any("1800" in x for x in p)


def test_pat_expiry_warns_in_last_week():
    runs = [_run(bekci.TAHMIN, 2026, 12, 6, 9, 0), _run(bekci.TAHMIN, 2026, 12, 6, 10, 0)]
    now = dt.datetime(2026, 12, 6, 10, 10, tzinfo=IST)
    assert any("erişim anahtarı" in x for x in bekci.find_problems(now, runs))
    assert not any("erişim anahtarı" in x for x in bekci.find_problems(_now(10, 10), runs[:1] + []))

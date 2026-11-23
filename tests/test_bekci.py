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
    runs = [
        _run(bekci.V6_CANLI, 2026, 11, 10, 13, 45),
        _run(bekci.V6_CANLI, 2026, 11, 10, 17, 34),
        _run(bekci.V6_CANLI, 2026, 11, 11, 9, 40),
    ]
    assert bekci.find_problems(_now(11, 15), runs) == []


def test_missing_slot_is_reported():
    runs = [
        _run(bekci.V6_CANLI, 2026, 11, 10, 13, 45),
        _run(bekci.V6_CANLI, 2026, 11, 10, 17, 34),
    ]
    p = bekci.find_problems(_now(10, 15), runs)  # 09:40 yok
    assert len(p) == 1 and "09:40" in p[0]


def test_slot_not_yet_due_is_not_reported():
    # 09:50'de 09:40 tetiği için ek süre (20 dk) daha dolmadı; 10.11 09:40 ise 24 saatten eski
    runs = [
        _run(bekci.V6_CANLI, 2026, 11, 10, 13, 45),
        _run(bekci.V6_CANLI, 2026, 11, 10, 17, 34),
    ]
    assert bekci.find_problems(_now(9, 50), runs) == []


def test_old_slots_beyond_lookback_ignored():
    p = bekci.find_problems(_now(15, 15), [])
    assert not any("10.11 09:40" in x or "10.11 13:45" in x for x in p)  # 24 saatten eski tetikler bakılmaz
    assert any("10.11 17:34" in x for x in p)
    assert any("11.11 09:40" in x for x in p)
    assert any("11.11 13:45" in x for x in p)


def test_evening_and_overnight_checks_catch_daytime_misses():
    # Akşam 19:15'te yalnız 17:34 çalıştıysa gündüz (09:40 ve 13:45) eksikleri yakalanmalı
    evening_now = _now(19, 15)
    p_evening = bekci.find_problems(evening_now, [_run(bekci.V6_CANLI, 2026, 11, 11, 17, 34)])
    assert any("11.11 09:40" in x for x in p_evening)
    assert any("11.11 13:45" in x for x in p_evening)
    assert not any("17:34" in x for x in p_evening)

    # Gece 02:30'da 11.11 öğle ve akşam çalışıp sabah (09:40) atlandıysa yine yakalanmalı
    overnight_now = dt.datetime(2026, 11, 12, 2, 30, tzinfo=IST)
    overnight_runs = [
        _run(bekci.V6_CANLI, 2026, 11, 11, 13, 45),
        _run(bekci.V6_CANLI, 2026, 11, 11, 17, 34),
    ]
    p_overnight = bekci.find_problems(overnight_now, overnight_runs)
    assert len(p_overnight) == 1 and "11.11 09:40" in p_overnight[0]


def test_evening_slot_checked():
    p = bekci.find_problems(_now(18, 15), [_run(bekci.V6_CANLI, 2026, 11, 11, 13, 45)])
    assert any("17:34" in x for x in p)


def test_failed_run_and_budget_are_reported():
    runs = [_run(bekci.V6_CANLI, 2026, 11, 11, 9, 40, "failure")]
    p = bekci.find_problems(_now(10, 15), runs, budget_used=1800)
    assert any("failure" in x for x in p) and any("1800" in x for x in p)


def test_pat_expiry_warns_in_last_week():
    runs = [_run(bekci.V6_CANLI, 2026, 12, 6, 9, 40)]
    now = dt.datetime(2026, 12, 6, 10, 10, tzinfo=IST)
    assert any("erişim anahtarı" in x for x in bekci.find_problems(now, runs))
    assert not any("erişim anahtarı" in x for x in bekci.find_problems(_now(10, 10), [_run(bekci.V6_CANLI, 2026, 11, 11, 9, 40)]))

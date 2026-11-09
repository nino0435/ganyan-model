"""GitHub Actions dakika bütçesi ve kapı kuralı testleri (§3, §5)."""
import datetime

from scripts import actions_budget as ab


def test_gate_thresholds_1399_1400_1799_1800():
    """Kapı eşikleri: 1399 (hepsi), 1400 (yalnız kritik), 1799 (yalnız kritik), 1800 (tahmin atla, aksam çalışır)."""
    crit_time = datetime.datetime(2026, 11, 9, 10, 0)  # TR 10:00 -> kritik
    opt_time = datetime.datetime(2026, 11, 9, 9, 0)    # TR 09:00 -> isteğe bağlı

    # 1399 dk: hem kritik hem isteğe bağlı çalışır
    r_1399_c = ab.karar(crit_time, "tahmin", {"month": "2026-11", "used_min": 1399})
    r_1399_o = ab.karar(opt_time, "tahmin", {"month": "2026-11", "used_min": 1399})
    assert r_1399_c["karar"] == "calis" and r_1399_c["allow"] is True
    assert r_1399_o["karar"] == "calis" and r_1399_o["allow"] is True

    # 1400 dk: yalnız kritik çalışır, isteğe bağlı atlanır
    r_1400_c = ab.karar(crit_time, "tahmin", {"month": "2026-11", "used_min": 1400})
    r_1400_o = ab.karar(opt_time, "tahmin", {"month": "2026-11", "used_min": 1400})
    assert r_1400_c["karar"] == "calis" and r_1400_c["sinif"] == "kritik"
    assert r_1400_o["karar"] == "atla" and r_1400_o["sinif"] == "istege_bagli" and r_1400_o["error"] is False

    # 1799 dk: yalnız kritik çalışır, isteğe bağlı atlanır
    r_1799_c = ab.karar(crit_time, "tahmin", {"month": "2026-11", "used_min": 1799})
    r_1799_o = ab.karar(opt_time, "tahmin", {"month": "2026-11", "used_min": 1799})
    assert r_1799_c["karar"] == "calis"
    assert r_1799_o["karar"] == "atla"

    # 1800 dk: tahmin (kritik dahil) atlanır ve error=True; aksam yine çalışır
    r_1800_c = ab.karar(crit_time, "tahmin", {"month": "2026-11", "used_min": 1800})
    r_1800_o = ab.karar(opt_time, "tahmin", {"month": "2026-11", "used_min": 1800})
    r_1800_a = ab.karar(crit_time, "aksam", {"month": "2026-11", "used_min": 1800})
    assert r_1800_c["karar"] == "atla" and r_1800_c["error"] is True and "bütçe doldu" in r_1800_c["reason"]
    assert r_1800_o["karar"] == "atla" and r_1800_o["error"] is True
    assert r_1800_a["karar"] == "calis" and r_1800_a["allow"] is True and r_1800_a["error"] is False


def test_slot_rounding_delayed_cron_runs():
    """Sınıf yuvarlama: ±40 dk toleransla gecikmiş çalışmalar doğru sınıfa düşer."""
    # Kritik: 10:00, 12:00, 14:30, 18:30
    assert ab.classify_slot("10:22") == ("10:00", "kritik")
    assert ab.classify_slot("12:30") == ("12:00", "kritik")  # tam ortada erken olan 12:00 seçilir
    assert ab.classify_slot("15:05") == ("14:30", "kritik")  # +35 dk gecikmiş 14:30
    assert ab.classify_slot("19:08") == ("18:30", "kritik")  # +38 dk gecikmiş 18:30

    # İsteğe bağlı: 09:00, 11:00, 13:00, 16:30, 20:30
    assert ab.classify_slot("09:18") == ("09:00", "istege_bagli")
    assert ab.classify_slot("11:25") == ("11:00", "istege_bagli")
    assert ab.classify_slot("13:35") == ("13:00", "istege_bagli")
    assert ab.classify_slot("17:05") == ("16:30", "istege_bagli")
    assert ab.classify_slot("21:05") == ("20:30", "istege_bagli")

    # ±40 dk dışında kalan saat -> cron-dışı isteğe bağlı
    assert ab.classify_slot("23:00") == (None, "istege_bagli")


def test_month_rollover_preserves_high_water_and_moves_history():
    """Ay devri: yeni ayda used_min ve runs sıfırlanır, eski ay history'ye taşınır, high_water korunur."""
    nov_state = {
        "month": "2026-11",
        "used_min": 1450,
        "runs": [{"ts": "2026-11-30T18:31:00", "mode": "tahmin", "billed_min": 2}],
        "predictions_high_water": 840,
    }
    dec_state = ab.ensure_month(nov_state, "2026-12")
    assert dec_state["month"] == "2026-12"
    assert dec_state["used_min"] == 0
    assert dec_state["runs"] == []
    assert dec_state["predictions_high_water"] == 840
    assert len(dec_state["history"]) == 1
    assert dec_state["history"][0]["month"] == "2026-11"
    assert dec_state["history"][0]["used_min"] == 1450

    # karar() da eski ay durumu verildiğinde yeni ay başında sıfırlanmış kabul eder
    dec_now = datetime.datetime(2026, 12, 1, 9, 5)
    res = ab.karar(dec_now, "tahmin", nov_state)
    assert res["karar"] == "calis"
    assert res["used_min"] == 0


def test_ceil_billed_min():
    """Faturalanan dakika: saniyeden dakikaya yukarı yuvarlanır, en az 1 dk."""
    assert ab.ceil_billed_min(0) == 1
    assert ab.ceil_billed_min(1) == 1
    assert ab.ceil_billed_min(59.9) == 1
    assert ab.ceil_billed_min(60.0) == 1
    assert ab.ceil_billed_min(60.1) == 2
    assert ab.ceil_billed_min(120) == 2
    assert ab.ceil_billed_min(121) == 3


def test_projection_warning_above_1700():
    """Kalan gün/ay projeksiyonu: used_min / geçen_gün * ay_gün_sayısı > 1700 ise UYARI verir."""
    # Kasım 30 gün: 10. günde 600 dk -> 600 / 10 * 30 = 1800 > 1700 -> UYARI
    now_10 = datetime.datetime(2026, 11, 10, 12, 0)
    proj_high = ab.project_month_min(now_10, 600)
    assert proj_high["warn"] is True
    assert proj_high["projected_min"] == 1800.0
    assert "UYARI" in proj_high["warning_text"]

    summary = ab.format_budget_summary({"month": "2026-11", "used_min": 600, "predictions_high_water": 100}, now=now_10)
    assert "UYARI" in summary

    # 10. günde 500 dk -> 500 / 10 * 30 = 1500 <= 1700 -> uyarı yok
    proj_ok = ab.project_month_min(now_10, 500)
    assert proj_ok["warn"] is False
    assert proj_ok["warning_text"] == ""


def test_record_run_overhead_constants():
    """T2-3: record_run tahmin için +40 sn, aksam için +90 sn (OVERHEAD_SEC_*) ekler ve ceil uygular."""
    assert ab.OVERHEAD_SEC_TAHMIN == 40
    assert ab.OVERHEAD_SEC_AKSAM == 90

    st = ab.default_budget_state("2026-11")
    # tahmin: 15 sn + 40 sn = 55 sn -> ceil(55/60) = 1 dk
    st = ab.record_run(st, "2026-11-09T09:00:00", "tahmin", elapsed_sec=15.0)
    assert st["runs"][-1]["billed_min"] == 1
    assert st["used_min"] == 1

    # tahmin: 25 sn + 40 sn = 65 sn -> ceil(65/60) = 2 dk
    st = ab.record_run(st, "2026-11-09T10:00:00", "tahmin", elapsed_sec=25.0, predictions_count=42)
    assert st["runs"][-1]["billed_min"] == 2
    assert st["used_min"] == 3
    assert st["predictions_high_water"] == 42

    # aksam: 40 sn + 90 sn = 130 sn -> ceil(130/60) = 3 dk
    st = ab.record_run(st, "2026-11-10T00:45:00", "aksam", elapsed_sec=40.0)
    assert st["runs"][-1]["billed_min"] == 3
    assert st["used_min"] == 6

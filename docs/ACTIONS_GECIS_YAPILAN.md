# Ganyan → GitHub Actions Geçişi — Yapılanlar Raporu (Tur 1 + Tur 2)

Tur 2 çalışması başladı, Tur 1 ve Tur 2 maddeleri inceleniyor ve uygulanıyor...

DURUM: TAKILDIM

## Claude denetimi (9 Kas 2026, Tur 1 + Tur 2 sonrası)
Gemini Tur 2'de rapor dosyasını tamamlamadan kapandı (reddedilen kabuk komutu); aşağıdakiler Claude tarafından doğrulandı:
- Tur 1: 2 workflow, `actions_run/actions_budget/actions_restore_predictions/merge_predictions/karsilastir`, `requirements*.txt`, `ACTIONS_PLAN.md`; 45 test yeşil. Boş/küçük DB → çıkış kodu 1.
- Tur 2: T2-1 (bütçe her çalışmada commit), T2-2 (atlanan çalışma kaydı), T2-3 (OVERHEAD_SEC_TAHMIN=40, AKSAM=90), T2-4 (önbellek yalnız new_predictions>0 / aksam her gece) yerinde; 49 test yeşil.
- Mac dosyaları (`scripts/daily_job.sh`, `ops/`) değişmedi; `gozcu.py`/`forward_report.py` değişiklikleri geriye uyumlu.
- Doğrulanmamış: Actions üzerinde gerçek çalışma (Python 3.14 kurulumu, paket sürümleri, önbellek/Release dönüşü) — ilk çalışmayla denenecek.

DURUM: TAMAM

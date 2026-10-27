# Ganyan Model — Veri, Değerlendirme, İleri Test ve Kupon Dağıtıcı

TJK resmi sonuç ve koşu öncesi program CSV'lerinden kurulan veri katmanı (`data/ganyan.db`), aylık ileri-yürüyen değerlendirme motoru, kupon dağıtıcı (Amaç A / Amaç B) ve mobil uygulama için JSON dışa aktarıcı.

## Kurulum ve Testler

```bash
venv/bin/python -m pytest -q
```

## Günlük Komutlar (Kullanıcı Tarafından Çalıştırılır — Otomatik Zamanlayıcı Yoktur)

1. **Günlük Güncelleme (dün/bugün sonuçları + yarın programı):**
   ```bash
   venv/bin/python scripts/update_daily.py --date $(date +%Y-%m-%d)
   ```
2. **Canlı AGF Anlık Görüntüsü (koşudan önce):**
   ```bash
   venv/bin/python scripts/snapshot_agf.py --date $(date +%Y-%m-%d)
   ```
3. **İleri Test Tahmin Kaydı (ilk koşudan en geç 30 dk önce; gece koşuları için ~17:30'da tekrar çalıştırılabilir):**
   ```bash
   venv/bin/python scripts/forward_log.py --date $(date +%Y-%m-%d)
   ```
4. **İleri Test Raporu Üretimi (`reports/FORWARD.md`):**
   ```bash
   venv/bin/python scripts/forward_report.py
   ```
5. **Mobil Uygulama JSON Dışa Aktarımı (`data/export/YYYY-MM-DD/`):**
   ```bash
   venv/bin/python scripts/export_day.py --date $(date +%Y-%m-%d)
   ```
6. **Aylık İleri-Yürüyen Backtest ve Kupon Raporu (`reports/BACKTEST.md`):**
   ```bash
   venv/bin/python scripts/run_backtest.py
   ```

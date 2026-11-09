# Ganyan — GitHub Actions İleri Test Planı

8 haftalık ileri testin (`v1_agf` vs anlık AGF favorisi) Mac (`launchd`) ile paralel ("gölge") olarak GitHub Actions üzerinde çalıştırılması ve doğrulama sonunda tek kaynağa geçiş planıdır.

---

## 1. Mimari (Kısa)

- **İki Workflow (`.github/workflows/`):**
  - `ganyan-tahmin.yml`: Gün içi 9 zamanlanmış çalışma (`schedule`) + `workflow_dispatch` (`mode=tahmin|test`, `dry_run`).
  - `ganyan-aksam.yml`: Gece `TR 00:45` (`UTC 21:45`) sonuç/rapor/yedek çalışması + `workflow_dispatch` (`date`).
  - Ortak koruma: `concurrency: { group: ganyan-state, cancel-in-progress: false }`, `permissions: contents: write`, `push`/`pull_request` tetikleyicisi **yoktur**.
- **Tek Giriş Betiği (`scripts/actions_run.py`):**
  - `tahmin`: `ensure_state` doğrulaması → `actions_budget.karar` bütçe kapısı → `gozcu.run(..., force_discover=True, notify=False)` → yeni tahminleri `state/predictions/YYYY-MM-DD.csv` dosyasına ekleme → kaçan koşuları `::warning::` ile bildirme → `GITHUB_STEP_SUMMARY` ve `state/budget.json` güncelleme.
  - `aksam`: `ensure_state` doğrulaması → `update_daily(Y)` ve telafi için `update_daily(Y-1)` → `forward_report` (`state/FORWARD.md`) → `ganyan-state.tar.zst` yedek paketi → `state/budget.json` güncelleme (`export_day` çalıştırılmaz).

---

## 2. Cron Zamanlama Tablosu

Türkiye saati sabit `UTC+3`'tür (yaz saati uygulaması yoktur).

| İş | TR Saati | UTC Saati | Cron İfadesi (UTC) | Bütçe Sınıfı | Açıklama |
|---|---|---|---|---|---|
| `tahmin` #1 | 09:00 | 06:00 | `0 6 * * *` | İsteğe bağlı | Sabah erken program/AGF kontrolü |
| `tahmin` #2 | **10:00** | **07:00** | `0 7 * * *` | **Kritik** | Sabah ana tahmin kaydı |
| `tahmin` #3 | 11:00 | 08:00 | `0 8 * * *` | İsteğe bağlı | Öğle öncesi kontrol |
| `tahmin` #4 | **12:00** | **09:00** | `0 9 * * *` | **Kritik** | Öğle seansı öncesi |
| `tahmin` #5 | 13:00 | 10:00 | `0 10 * * *` | İsteğe bağlı | İlk koşular öncesi ara kontrol |
| `tahmin` #6 | **14:30** | **11:30** | `30 11 * * *` | **Kritik** | Öğleden sonra seansı |
| `tahmin` #7 | 16:30 | 13:30 | `30 13 * * *` | İsteğe bağlı | İkindi/akşamüstü kontrolü |
| `tahmin` #8 | **18:30** | **15:30** | `30 15 * * *` | **Kritik** | Gece/akşam yarışları öncesi |
| `tahmin` #9 | 20:30 | 17:30 | `30 17 * * *` | İsteğe bağlı | Geç başlayan koşular / son kontrol |
| `aksam` | **00:45** | **21:45** *(önceki gün)* | `45 21 * * *` | **Zorunlu (Akşam)** | Dünün sonuçları (`Y` ve `Y-1`), `FORWARD.md`, gece yedeği |

---

## 3. Dakika Bütçesi Formülü ve Aylık Harcama Tablosu

- **Kısıt:** Ücretsiz plan, özel depo, ayda **en fazla 2000 Actions dakikası (Linux)**; tasarım hedefi **≤ 1400 dk/ay**, sert koruma **1800 dk/ay**.
- **Faturalama kuralı ve ek süre sabitleri (`OVERHEAD_SEC_*`):**
  - Betik çalışma süresi (`elapsed_sec`), betik bittikten sonraki workflow adımlarını (`actions/cache/save`, `git commit/push`, `gh release upload`) kapsamaz.
  - Bu nedenle `record_run` çağrılarında betik süresine sabit ek süre eklenir (`scripts/actions_budget.py`):
    - `OVERHEAD_SEC_TAHMIN = 40` sn (`tahmin` modu için `+40 sn`)
    - `OVERHEAD_SEC_AKSAM = 90` sn (`aksam` modu için `+90 sn`)
  - Faturalanan dakika formülü: `billed_min = max(1, ceil((elapsed_sec + OVERHEAD_SEC_*) / 60))`
- **Bütçe kapısı (`karar(now, mode, month_state)`):**
  - Çalışma saati `±40 dk` toleransla en yakın cron saatine yuvarlanarak sınıfı (`kritik` / `istege_bagli`) belirlenir.
  - `used_min < 1400`: Tüm çalışmalar (`kritik` + `istege_bagli` + `aksam`) çalışır.
  - `1400 ≤ used_min < 1800`: Gün içinde yalnız **kritik** (`10:00, 12:00, 14:30, 18:30`) çalışmalar ve `aksam` çalışır; `istege_bagli` çalışmalar atlanır.
  - `used_min ≥ 1800`: Tüm `tahmin` çalışmaları atlanır ve `::error::` ile bütçe doldu uyarısı basılır; `aksam` her zaman çalışır.
  - **Atlanan çalışmaların kaydı:** `karar == "atla"` yolunda da iş başlatıldığı için `record_run` ile `~1 dk` (`elapsed_sec + OVERHEAD_SEC_TAHMIN`) kaydedilir ve `state_changed=true` döndürülerek `state/budget.json` kalıcı olarak commit edilir.
  - **Projeksiyon uyarısı:** `used_min / geçen_gün × ay_gün_sayısı > 1700` olduğunda özet satırına `UYARI` eklenir.

### Beklenen Aylık Harcama Tablosu (Varsayım ve Formül)

> Not: Aşağıdaki rakamlar tasarım varsayımıdır (`OVERHEAD_SEC_TAHMIN = +40 sn`, `OVERHEAD_SEC_AKSAM = +90 sn` dahil); ilk gerçek Actions çalışmalarından sonra Claude tarafından güncellenecektir.

| Senaryo | Günlük `tahmin` (`+40 sn` ek süre dahil) | Günlük `aksam` (`+90 sn` ek süre dahil) | Günlük Toplam Formülü | 30 Günlük Toplam | 31 Günlük Toplam |
|---|---|---|---|---:|---:|
| **Beklenen (Normal)** | 1 dolu (`~60s + 40s → 2–3 dk`) + 8 erken çıkış (`8 × (20–40s + 40s) → 8 × 2 dk`) ≈ `18–21 dk/gün` (ort. `9 × 2–2.3 dk`) | `1 × 8–12 dk` (`+90 sn` dahil) | `9 × ceil((t_tahmin + 40)/60) + ceil((t_aksam + 90)/60)` | **~800 – 1200 dk** | **~830 – 1250 dk** |
| **Kritik Korumalı (`1400 ≤ used_min < 1800`)** | 4 kritik (`4 × 2–3 dk = 8–12 dk`) + 5 atlanan (`karar=="atla"`, `5 × ceil((~15s + 40s)/60) = 5 × 1 dk = 5 dk`) | `1 × 8–12 dk` | `4 × T_kritik + 5 × 1 + T_aksam` | **~630 – 870 dk** | **~650 – 900 dk** |
| **En Kötü Durum (31 gün, kapısız hepsi 3 dk + akşam 12 dk)** | `9 × 3 dk = 27 dk/gün` | `1 × 12 dk = 12 dk/gün` | `31 × (9 × 3 + 12) = 1209 dk` (sert tavan `≤ 1800 dk`) | **1170 dk (≤ 1800)** | **1209 dk (≤ 1800)** |

En kötü durumda dahi (31 gün boyunca `+40 sn` ek süre dahil 9 tahmin çalışmasının tamamı `3 dk` ve `+90 sn` ek süre dahil akşam işi `12 dk` sürse bile: `31 × (27 + 12) = 1209 dk`, hatta daha yüksek sürelerde `1400 dk` eşiğinde isteğe bağlı 5 çalışma `1 dk`'lık erken çıkışa düşürüldüğünden ve `1800 dk` eşiğinde tüm tahminler durdurulduğundan) aylık tüketim **1800 dk sert koruma sınırının altında (≤ 1800 dk)** kalır.

---

## 4. Üç Katmanlı Durum (State) Mimarisi

1. **Hızlı Katman (`actions/cache`):**
   - `data/ganyan.db` ve `data/raw/` klasörü `ganyan-state-${run_id}` anahtarıyla (`restore-keys: ganyan-state-`) önbelleklenir.
   - `ganyan-tahmin.yml` içinde `actions/cache/save` yalnız yeni tahmin yazıldığında (`new_predictions > 0`) çalışır; salt `agf_snapshots` güncellemeleri için her saat ~70 MB önbellek girişi açılmaz. `ganyan-aksam.yml` ise yarış sonuçları geldiği için her gece önbelleği kaydeder (`db_changed` çıktısı bilgi amaçlı korunur).
2. **Tohum / Gece Yedeği Katmanı (GitHub Release):**
   - İlk kurulum tohumu: `state-seed` Release etiketi altındaki `ganyan-state.tar.zst`.
   - Gece yedeği: `ganyan-aksam.yml` her gece güncel paketi `state-backup` Release etiketine (`gh release upload --clobber`) yükler.
   - Önbellek boşsa sırasıyla `state-backup` → `state-seed` Release varlığından indirilir.
3. **Kalıcı Kanıt Katmanı (`actions-state` orphan dalı):**
   - `state/predictions/YYYY-MM-DD.csv`, `state/FORWARD.md` ve `state/budget.json` dosyalarını tutar.
   - `main` dalına **asla** commit atılmaz; yalnız `actions-state` dalına `github-actions[bot]` kimliğiyle her gerçek (dry-run olmayan) çalışmada commit+push yapılır (`new_predictions > 0` ise `tahmin YYYY-MM-DD HH:MM: N koşu`, yeni tahmin yoksa veya bütçe kapısında atlandıysa `tahmin YYYY-MM-DD HH:MM: bekleyen yok`).

---

## 5. Durum Sağlama (`ensure_state`) ve Kayıp Kurtarma

- **Doğrulama (`ensure_state`):**
  1. Veritabanı dosyası mevcut ve boyutu `> 0` olmalı (boş veritabanıyla asla sessizce başlamaz).
  2. `PRAGMA integrity_check` sonucu `ok` olmalı.
  3. `races` tablosunda en az `1000` satır bulunmalı.
  4. `predictions` tablosu satır sayısı, `state/budget.json` içindeki `predictions_high_water` değerinden **küçük olmamalı** (veri kaybı alarmı).
  - Herhangi biri başarısızsa betik `::error::` basar ve `exit 1` ile çıkar.
- **Kayıp Kurtarma (`scripts/actions_restore_predictions.py`):**
  - Hem `actions/cache` hem de Release yedeği (`state-backup`) bozulur veya silinirse, `state-seed` (veya temel DB) üzerine `actions-state` dalındaki tüm günlük CSV kayıtları geri yüklenir:
    ```bash
    venv/bin/python -I scripts/actions_restore_predictions.py \
      --db data/ganyan.db \
      --predictions-dir state/predictions
    ```
  - Betik tüm `state/predictions/*.csv` dosyalarını tarar ve `INSERT OR IGNORE` ile `predictions` tablosunu eksiksiz yeniden kurar.

---

## 6. Mac'ten GitHub Actions'a Geçiş Adımları

1. **Tohum Yükleme (İlk Kurulum):**
   - Mac'teki güncel `data/ganyan.db` ve `data/raw/` klasörü `ganyan-state.tar.zst` olarak paketlenir ve özel depoda `state-seed` Release etiketine yüklenir.
2. **Gölge (Paralel) Çalışma (1 Hafta):**
   - Mac `launchd` işleri dokunulmadan çalışmaya devam ederken GitHub Actions workflow'ları paralel çalışır.
3. **Günlük Karşılaştırma (`scripts/karsilastir.py`):**
   - Actions'tan indirilen `ACTIONS.db` ile Mac'teki `data/ganyan.db` salt okunur olarak karşılaştırılır:
     ```bash
     venv/bin/python -I scripts/karsilastir.py \
       --mac data/ganyan.db \
       --actions /tmp/actions_ganyan.db \
       --from 2026-11-09
     ```
   - Gün bazında koşu sayısı, `yalnız Mac`, `yalnız Actions`, `ikisi`, `hiçbiri`, ortalama `|p_win farkı|` ve yazım saatleri farkı kontrol edilir.
4. **Tahminleri Birleştirme (`scripts/merge_predictions.py`):**
   - İki veritabanındaki tahminler birleştirilir; aynı `(race_id, prog_no, model_version)` için **`created_at` en erken olan** korunur:
     ```bash
     venv/bin/python -I scripts/merge_predictions.py \
       --from data/ganyan.db \
       --into /tmp/actions_ganyan.db \
       --dry-run
     ```
5. **Mac İşlerini Kapatma:**
   - Actions'ın kesintisiz ve bütçe sınırları içinde çalıştığı doğrulandıktan sonra birleştirilmiş DB `state-backup` olarak yüklenir ve Mac üzerindeki `launchd` görevleri durdurulur.

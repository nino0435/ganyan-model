# Ganyan → GitHub Actions geçişi — A Takımı şartnamesi (Tur 1)

Yazan/denetleyen: Claude. Uygulayan: Gemini (Antigravity). Tarih: 9 Kas 2026. Proje: bu depo (`~/AndroidStudioProjects/ganyan`),
derspilot ile İLGİSİZ. Bu belge ve `docs/ACTIONS_GECIS_YAPILAN.md` depoda kalır (silinmez).

## 0. Amaç

8 haftalık ileri test (`v1_agf` vs AGF favorisi) şu an Mac'te launchd ile çalışıyor (Mac sık kapanıyor: 6–9 Kas'ta 3 kez).
Aynı işi **GitHub Actions**'a taşıyan bir prototip hazırla. Mac sistemi **şimdilik aynen çalışmaya devam eder** (dokunma);
Actions "gölge" olarak paralel çalışır, başarılı olursa Mac kapatılır.

**Sert kısıt: ücretsiz plan, özel depo, ayda EN FAZLA 2000 Actions dakikası (Linux).**
Tasarım hedefi ≤ 1400 dk/ay; sert koruma 1800 dk. Bunu aşan hiçbir zamanlama kabul edilmez.

## 1. Ölçülmüş/bilinen gerçekler (yeniden keşfetme)

- Mevcut mantık hazır: `scripts/gozcu.py` (`run()` — bekleyen koşuları bulur, `snapshot_agf` ile taze program+AGF çeker,
  AGF'si hazır koşular için `forward_log(..., race_ids=...)` ile tahmin yazar), `scripts/forward_log.py`,
  `scripts/update_daily.py`, `scripts/forward_report.py`, `scripts/snapshot_agf.py`, `ganyan/tjk.py`.
- `predictions` PK = (race_id, prog_no, model_version), `INSERT OR IGNORE` → **ilk yazan kazanır**. Geçerli tahmin:
  `created_at < tarih+post_time` (İstanbul saati, `created_at` naive yerel string).
- Geçmiş günlerde bir günün TÜM tahminleri günün ilk başarılı çalışmasında yazıldı (AGF sabah toplu yayınlanıyor).
  Bu yüzden 5 dk'lık yoklama gerekmez; saatlik toplu çalışma yeter. Ama sürpriz seans / geç eklenen koşu ≤ ~2 saatte yakalanmalı.
- TJK, GitHub Actions makinesinden (ABD/Azure IP) açılıyor: www.tjk.org, program sayfası ve medya-cdn CSV → 200 (9 Kas 2026 denendi).
- Boyutlar: `data/ganyan.db` 72 MB, `data/raw` 71 MB, toplam `data/` 220 MB (gitignore'lu). Python 3.14.6 (venv); doğrudan
  bağımlılıklar numpy, pandas, scipy (+ test için pytest). `requirements.txt` YOK → oluştur. SÜRÜMLER (Claude doğruladı, pip KULLANMA — headless modda pip izni yok):
  `numpy==2.5.4`, `pandas==3.1.0`, `scipy==1.18.1`, `scikit-learn==1.9.1`, `python-dateutil==3.0.0`, `tzdata==2026.5`;
  test bağımlılığı ayrı dosya `requirements-dev.txt`: `-r requirements.txt` + `pytest==9.1.1`. Import ettiğimiz üçüncü taraf modüller
  (doğrulandı): numpy, pandas, sklearn, pytest (+ scipy ve dateutil/tzdata dolaylı). Başka paket ekleme.
- GitHub'da cron yalnız **varsayılan dal (main)**'deki workflow'lar için tetiklenir, UTC'dir, 5 dk altına inmez, 5–30 dk gecikebilir/atlanabilir.
  Türkiye UTC+3, yaz saati yok (TR 10:00 = 07:00 UTC).
- Ubuntu runner: 2 vCPU, 7 GB RAM. `tahmin` ≈ 36 sn CPU, tepe RAM ≈ 0,93 GB → sığar.
- İş (job) süresi **dakikaya yukarı yuvarlanır**; her iş en az 1 dk faturalanır.

## 2. Mimari

İki workflow, tek giriş betiği, üç katmanlı durum.

### 2.1 Workflow'lar (`.github/workflows/`)
1. `ganyan-tahmin.yml` — `schedule` (UTC; TR karşılıkları yorumda yaz): TR 09:00, 10:00, 11:00, 12:00, 13:00, 14:30, 16:30,
   18:30, 20:30 → UTC 06:00, 07:00, 08:00, 09:00, 10:00, 11:30, 13:30, 15:30, 17:30. + `workflow_dispatch`
   (girdi: `mode` = tahmin|test, `dry_run` bool). Mod `tahmin`.
2. `ganyan-aksam.yml` — `schedule` TR 00:45 = UTC 21:45 (önceki UTC günü), + `workflow_dispatch` (girdi: `date` isteğe bağlı). Mod `aksam`.
3. İkisi de: `permissions: contents: write`; `concurrency: { group: ganyan-state, cancel-in-progress: false }` (iki iş aynı anda
   durumu bozmasın); `timeout-minutes`: tahmin 7, aksam 25; ortam `TZ: Europe/Istanbul`, `PYTHONUTF8=1`; `runs-on: ubuntu-latest`.
4. Eylem sürümleri: bilinen en güncel ana sürüm etiketleri (`actions/checkout`, `actions/setup-python` (pip önbelleği açık),
   `actions/cache/restore` + `actions/cache/save`); kullandığın sürümü YAPILAN'a yaz. Python 3.14 — setup-python bunu
   sunmuyorsa 3.13'e düş ve nedenini yaz (testler her ikisinde geçmeli).
5. `schedule` dışında hiçbir tetikleyici (push/PR) YOK — yanlışlıkla dakika yemesin.

### 2.2 Giriş betiği `scripts/actions_run.py`
`python -I scripts/actions_run.py tahmin|aksam [--date YYYY-MM-DD] [--db PATH] [--state-dir PATH] [--dry-run]`.
Workflow adımları ince kalır; mantık Python'da (test edilebilir). Çıkış kodu ≠0 yalnız GERÇEK hatada (ör. durum yüklenemedi);
"yarış yok", "bekleyen yok" → 0.

**tahmin** (D = İstanbul bugünü):
1. Durum sağlama (bkz. 2.3) — başarısızsa `exit 1` (**asla boş veritabanıyla sessizce başlama**).
2. Bütçe kapısı (bkz. 3): `atla` kararı ise "bütçe" gerekçesini yazıp 0 ile çık.
3. `gozcu.run(D, now, ..., fetch=True)` — **keşif bu modda her zaman zorlanır** (yeni `force_discover=True` parametresi; mevcut
   Mac davranışı varsayılan olarak AYNEN kalmalı). Gün içi her çalışma tek geçiş: şehir keşfi + bekleyenler için taze program/AGF + tahmin yazma.
4. Yeni yazılan tahmin satırlarını (bu çalışmada eklenenleri; `created_at >= çalışma başlangıcı`) `state/predictions/D.csv`'ye EKLE
   (sütunlar: race_id,prog_no,model_version,created_at,p_win,agf_used; başlıklı; aynı PK iki kez yazılmaz).
5. `KAÇTI` koşular varsa `::warning::` ile yaz (macOS bildirimi YOK; bkz. 4).
6. Çıktı: tek satır özet (`GITHUB_STEP_SUMMARY`'e de: yazılan/bekleyen/kaçan, süre, bütçe durumu).

**aksam** (hedef gün Y = `--date` ya da İstanbul'da DÜN; 00:45'te çalıştığı için dün):
1. Durum sağlama; bütçe kapısı (aksam ASLA bütçe yüzünden atlanmaz).
2. `update_daily(Y)` ve telafi için `update_daily(Y-1)` (sonuçlar Y-2..Y ve Y, Y+1 programı gelir; mevcut fonksiyonu AYNEN kullan).
3. `forward_report` (mevcut betiğin işlevi; çıktı yolu `state/FORWARD.md` olacak şekilde parametrelendir — Mac varsayılanı `reports/FORWARD.md` KALSIN).
4. `export_day` ÇALIŞTIRMA (mobil sözleşme JSON'u, Actions'ta gereksiz ve yavaş).
5. Veritabanı yedeği için durum paketini hazırla (2.3-c). `state/budget.json` ay özetini yaz.

### 2.3 Durum (state) — üç katman
Çalıştırıcı geçicidir; durum şunlardır:
- **(a) Hızlı katman — `actions/cache`:** `data/ganyan.db` + `data/raw/` (tar.zst). Anahtar `ganyan-state-${run_id}`, `restore-keys: ganyan-state-`.
  Geri yükleme `actions/cache/restore`, kaydetme `actions/cache/save`; kaydetme yalnız veritabanı DEĞİŞTİYSE (satır sayısı/hash karşılaştır)
  — gereksiz 70 MB'lık giriş açma.
- **(b) Tohum/yedek — Release varlığı:** özel depoda `state-seed` etiketi, varlık `ganyan-state.tar.zst` (Claude yükler; ilk kurulum).
  Önbellek boşsa (7 gün kullanılmayan giriş silinir) buradan `gh release download` ile dön (`GH_TOKEN: ${{ github.token }}`).
  `aksam` işi her gece yedeği `state-backup` etiketine (`gh release upload --clobber`, etiket yoksa oluştur) yükler.
- **(c) Kalıcı kayıt — `actions-state` dalı (orphan):** `state/predictions/YYYY-MM-DD.csv`, `state/FORWARD.md`, `state/budget.json`.
  Her tahmin çalışmasında yeni tahmin varsa (ve aksam'da) bu dosyalar bu dala commit+push edilir (`github-actions[bot]`, mesaj
  `tahmin D HH:MM: N koşu`). **Bu dal ileri testin zaman damgalı kanıtıdır** (commit zamanı ≈ tahmin zamanı). `main`'e ASLA commit atma.
  Dal yoksa orphan olarak oluştur. Aynı dosyayı iki kez commit etme (değişiklik yoksa atla).
- **Sağlama (`ensure_state`):** sırayla (a) önbellek → (b) `state-backup` → (b) `state-seed`. Bulduktan sonra doğrula:
  `PRAGMA integrity_check = ok`, `races` ≥ 1000 satır, `predictions` satır sayısı `state/budget.json` içindeki
  `predictions_high_water`'dan KÜÇÜK değil (veri kaybı alarmı). Hiçbiri yoksa ya da doğrulama düşerse `exit 1` + açık hata.
- **Kayıp kurtarma (belgelenmiş, otomatik olmasa da yazılı):** önbellek + yedek kaybolursa `state/predictions/*.csv` ile
  `predictions` tablosu yeniden kurulabilir; bunun için `scripts/actions_restore_predictions.py` (CSV'lerden `INSERT OR IGNORE`) yaz.

## 3. Dakika bütçesi (kritik)

- `scripts/actions_budget.py` (saf fonksiyonlar + CLI): `state/budget.json` şeması
  `{"month": "2026-11", "used_min": 0, "runs": [{"ts","mode","billed_min"}], "predictions_high_water": N}`.
  Her çalışma sonunda **faturalanan dk = ceil(iş süresi sn / 60)** (checkout + kurulum + önbellek dahil, workflow başlangıç/bitiş
  zamanıyla) eklenir. Ay değişince sıfırla (yeni ay kaydı, eskiyi `history`'ye taşı).
- **Kapı kuralı (`karar(now, mode, month_state)`):**
  - Tahmin çalışmaları iki sınıf: *kritik* = TR 10:00, 12:00, 14:30, 18:30; *isteğe bağlı* = 09:00, 11:00, 13:00, 16:30, 20:30
    (saatleri `now`'dan en yakın cron'a yuvarla, ±40 dk toleransla; gecikmiş çalışma da doğru sınıfa düşsün).
  - `used_min < 1400` → hepsi çalışır. `1400 ≤ used_min < 1800` → yalnız kritik çalışır. `used_min ≥ 1800` → tahmin çalışmaları
    atlanır (aksam yine çalışır); `::error::` ile "bütçe doldu" yaz.
  - Kalan gün/ay projeksiyonu: `used_min / geçen_gün * ay_gün_sayısı` > 1700 ise özet satırına UYARI yaz.
- **Erken çıkış:** `tahmin` modunda bekleyen koşu YOKSA ve keşif yeni şey bulmadıysa, kurulum sonrası hemen çık (iş süresi kısa kalsın).
  Gün içinde hiç yarış olmayan günde (ör. TJK boş) çalışma ≈ 1 dk.
- Beklenen aylık harcama tablosunu `docs/ACTIONS_PLAN.md`'ye yaz: tahmin ≈ 9 çalışma × 2–3 dk, aksam ≈ 8–12 dk → ≈ 800–1250 dk/ay.
  Rakamları SEN ölçme; ilk gerçek çalışmalardan sonra Claude güncelleyecek. Tablo yalnız varsayımı ve formülü içersin.

## 4. Linux/Actions uyumu ve mevcut koda dokunma sınırı

- `scripts/gozcu.py`: `_notify_missed` yalnız `sys.platform == "darwin"` ise `osascript` çağırsın (Linux'ta hata atmasın);
  `run(...)` yeni isteğe bağlı `force_discover=False` parametresi alsın (varsayılan davranış DEĞİŞMEZ). Mac testleri
  (`tests/test_gozcu.py`) aynen geçmeli; yeni testler ekle (`force_discover`, darwin dışı bildirim atlaması).
- `scripts/forward_report.py`: çıktı yolunu CLI argümanıyla ver (yoksa mevcut yol). Mac işi (`daily_job.sh aksam`) aynen çalışmalı.
- `scripts/daily_job.sh`, `ops/launchd/*`, `~/Library/LaunchAgents/*`, `data/ganyan.db` (canlı Mac veritabanı): **DOKUNMA, okuma dışında**.
  Denemeler için veritabanının KOPYASINI oturum geçici klasörüne al (`cp data/ganyan.db <geçici>/test.db`).
- Başka derspilot dosyası YOK. Ağ: yalnız TJK'ya GET (mevcut kod yolları); başka dış servis, sır, anahtar YOK.

## 5. Testler (hepsi ağsız, `tests/`)

`venv/bin/python -m pytest -q` (`-I` yok) yeşil (şu an 31) + yenileri:
- `test_actions_budget.py`: kapı eşikleri (1399/1400/1799/1800), sınıf yuvarlama (gecikmiş çalışma), ay devri, ceil dakika,
  projeksiyon uyarısı.
- `test_actions_run.py`: `ensure_state` doğrulama düşme senaryoları (boş DB, düşük `races`, `predictions_high_water` altı),
  yeni-tahmin CSV ekleme (aynı PK iki kez yazılmaz), `--dry-run` ağ/DB yazımı yapmaz.
- `test_merge_predictions.py` (bkz. 6).
Ek doğrulama: `.github/workflows/*.yml` için `python -c "import yaml"` varsa YAML'ı ayrıştır; `actionlint` kuruluysa çalıştır
(kurulu değilse atla, yaz). Bir kopya DB üzerinde `actions_run.py tahmin --dry-run --db <kopya>` ve `aksam --dry-run` çalıştır.

## 6. Geçiş araçları ("başarılı olan yazsın")

- `scripts/merge_predictions.py --from A.db --into B.db [--model-version v1_agf]`: A'daki tahminleri B'ye al; aynı
  (race_id,prog_no,model_version) ikisinde de varsa **`created_at` EN ERKEN olan kalır** (yalnız yarıştan önce yazılmış olması
  fark etmez; erken olan kazanır); yalnız birinde varsa onu ekle. Yazmadan önce rapor sayıları (eklenen/değişen/aynı). `--dry-run`.
- `scripts/karsilastir.py --mac MAC.db --actions ACTIONS.db [--from YYYY-MM-DD]`: gün gün çıktı — koşu sayısı; geçerli tahmin
  (yarıştan önce) yalnız Mac / yalnız Actions / ikisi / hiçbiri; ikisinde olanlar için ort. |p_win farkı| ve yazım saatleri farkı.
  Salt okunur. Markdown tablo bas.

## 7. Yapılmayacaklar

`git add/commit/push/branch` (Claude yapar), `rm`, `launchctl`, `~/Library` altına yazmak, `data/ganyan.db`'yi değiştirmek,
`venv`'e paket kurmak (pip hiç çalıştırılmaz), `gh` komutları (Claude çalıştırır), `docs/SERVER_PLAN.md`'yi yeniden yazmak
(yalnız en sona "Actions seçeneği: docs/ACTIONS_PLAN.md'ye bak" notu), Mac sisteminin davranışını değiştirmek, bütçeyi
şartnamenin üstüne çıkaran bir zamanlama.

## 8. İzinli komutlar

`venv/bin/python -m pytest -q` (DİKKAT: `-I` YOK; `-I` ile `import ganyan` bulunamaz), `venv/bin/python -I scripts/...` (kopya DB ile), `cp` (yalnız
veritabanı kopyası → geçici klasör), `git status|diff|log` (salt okunur), `bash -n`, `python3 -c "import yaml…"`, `actionlint` (varsa).

## 9. Kabul ölçütleri (YAPILAN'da her biri için ✔/✘/◐ + kanıt)

1. İki workflow dosyası var; cron saatleri UTC ve TR karşılığı yorumda; `schedule`/`workflow_dispatch` dışı tetikleyici yok.
2. `scripts/actions_run.py tahmin|aksam` kopya DB üzerinde `--dry-run` ile 0 kodla çalışır; boş/bozuk durumda `exit 1`.
3. Bütçe kapısı testleri yeşil; en kötü durum hesabı (kritik+isteğe bağlı hepsi çalışsa, ay 31 gün) `docs/ACTIONS_PLAN.md`'de ≤ 1800.
4. Mevcut 31 test + yeni testler yeşil. `bash -n scripts/daily_job.sh` ve `git diff --stat` Mac dosyalarında (daily_job.sh, ops/) DEĞİŞİKLİK göstermez.
5. `requirements.txt` + `requirements-dev.txt` var, yukarıdaki sürümlerle; workflow bunları kurar (`pip install -r requirements.txt`; test adımı yalnız `workflow_dispatch` `mode=test` iken `requirements-dev.txt`). Pip'i SEN çalıştırma; Claude ilk Actions çalışmasında doğrular.
6. `docs/ACTIONS_PLAN.md`: mimari (kısa), cron tablosu, bütçe formülü, durum katmanları, kurtarma, Mac'ten geçiş adımları.

## 10. YAPILAN biçimi

`docs/ACTIONS_GECIS_YAPILAN.md`: madde başına ✔/✘/◐, dosya:satır, şartnameden sapma + nedeni, takıldığın yer, çalıştırdığın
komutlar + KISA çıktı kanıtı. Son satır tam olarak `DURUM: TAMAM` ya da `DURUM: TAKILDIM`. Sonraki turda silme, "Tur N" ekle.

---

# TUR 2 (Claude denetimi sonrası; Tur 1 çıktısı iyi: 45 test yeşil, Mac dosyaları değişmedi)

Yalnız aşağıdaki düzeltmeleri yap; çalışan hiçbir şeyi yeniden yazma. PIP/diğer reddedilen komutları ÇALIŞTIRMA.

**T2-1 (HATA, önemli): bütçe kaydı kalıcı olmuyor.** `ganyan-tahmin.yml` son adımı yalnız `new_predictions != '0'` iken
`state/budget.json`'u commit'liyor. Yeni tahmin yazmayan çalışmalarda bütçe kaydı (her çalışma ≥1 dk harcar) kaybolur →
`used_min` gerçeğin çok altında kalır, kapı hiç devreye girmez. Düzelt: her gerçek (dry-run olmayan) tahmin çalışmasında
`budget.json` commit+push edilsin (değişiklik varsa). `actions_run.py`'deki `"state_changed": "true" if (csv_rows > 0 or True) else "false"`
saçmalığını dürüst hâle getir (dry-run → false; gerçek çalışma → true). Workflow koşulu `state_changed == 'true'` kullansın;
commit mesajı yeni tahmin yoksa `tahmin D HH:MM: bekleyen yok`. Aksam adımı zaten her gece commit ediyor, bozma.

**T2-2: bütçe kapısı atlanan çalışmaları da kaydetsin.** `karar == "atla"` yolunda da `record_run` ile ~1 dk kaydet (bu çalışma da
faturalanır) ve `state_changed=true` döndür (budget.json commit edilsin).

**T2-3: bütçe eksik sayıyor.** Betik süresi, iş içindeki sonraki adımları (önbellek kaydı, commit/push, release yükleme) kapsamaz.
`record_run` çağrılarına sabit ek süre ekle: tahmin için +40 sn, aksam için +90 sn (`OVERHEAD_SEC_*` sabitleri, testle). `ceil` aynen.

**T2-4: gereksiz önbellek kaydı.** `db_changed` her çalışmada true çıkıyor (agf_snapshots satırları ekleniyor, dosya özeti değişiyor)
→ her çalışmada ~70 MB'lık yeni önbellek girişi. Düzelt: `ganyan-tahmin.yml` içinde önbellek yalnız `new_predictions` > 0 iken
kaydedilsin; `ganyan-aksam.yml` her gece kaydetsin (koşu sonuçları gelir). `db_changed` çıktısını silme (bilgi için kalsın).

**T2-5:** `docs/ACTIONS_PLAN.md` bütçe tablosunu T2-2/T2-3'e göre güncelle (ek süre sabitleri). Yeni/güncel testler (T2-1..T2-3 için)
ekle; `venv/bin/python -m pytest -q` yeşil kalsın.

**T2-6: `docs/ACTIONS_GECIS_YAPILAN.md`** — Tur 1'de yazılmadı. Tur 1 + Tur 2'yi kapsayacak şekilde yaz (biçim §10). Son satır
tam olarak `DURUM: TAMAM` ya da `DURUM: TAKILDIM`. Bu dosyayı EN SON yaz; ondan önce reddedilen bir komut yüzünden durursan
bile en azından yaptıklarını yazan kısa bir sürümünü İLK iş olarak oluştur, sonra güncelle.
